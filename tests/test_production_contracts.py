"""Regression coverage for the HTTP boundary, queue races and runtime limits."""
import concurrent.futures
import json
import sys
import time

import pytest

import config
import database
from api.app import create_app
from sandbox.runtime import run_command, run_language


@pytest.fixture
def client(tmp_db_path):
    return create_app().test_client()


@pytest.mark.parametrize("payload", [None, [], "hello", 42, {"language": []},
    {"language": "python", "source": 7}, {"language": "python", "source": "print(1)", "stdin": []}])
def test_malformed_payload_is_client_error(client, payload):
    response = client.post('/submit', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400
    assert response.is_json


def test_wrong_content_type(client):
    assert client.post('/submit', data='hello').status_code == 415


def test_stdin_byte_limit(client, monkeypatch):
    monkeypatch.setenv('MAX_STDIN_BYTES', '3')
    response = client.post('/submit', json={'language': 'python', 'source': 'print(input())', 'stdin': 'éé'})
    assert response.status_code == 413


def test_auth_and_public_config(client, monkeypatch):
    token = 'x' * 40
    monkeypatch.setenv('API_TOKEN', token)
    for path in ('/submissions', '/status/unknown', '/result/unknown'):
        assert client.get(path).status_code == 401
    assert client.post('/submit', json={}).status_code == 401
    assert client.get('/submissions', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    response = client.get('/api/config')
    assert response.json['authentication_required'] is True
    assert token not in response.get_data(as_text=True)
    assert 'db_path' not in response.json['limits']
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_queue_overload_returns_retry(client, monkeypatch):
    monkeypatch.setenv('MAX_PENDING_JOBS', '1')
    payload = {'language': 'python', 'source': 'print(1)'}
    assert client.post('/submit', json=payload).status_code == 201
    response = client.post('/submit', json=payload)
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '5'


def test_capacity_atomic_under_concurrency(tmp_db_path, monkeypatch):
    monkeypatch.setenv('MAX_PENDING_JOBS', '3')
    database.worker_health()  # initialize WAL before competing connections
    def submit(_):
        try:
            return database.create_submission('python', 'print(1)')
        except database.QueueFull:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(20)))
    assert sum(value is not None for value in results) == 3


def test_live_worker_survives_recovery_and_stale_write_is_ignored(tmp_db_path):
    job = database.create_submission('python', 'print(1)')
    database.heartbeat('original')
    database.claim_next('original')
    assert database.requeue_stuck() == 0
    database.expire_worker('original')
    assert database.requeue_stuck() == 1
    database.heartbeat('replacement')
    database.claim_next('replacement')
    database.store_result(job, {'stdout': 'stale', 'exit_code': 0}, worker_name='original')
    assert database.fetch(job)['status'] == 'running'
    database.store_result(job, {'stdout': 'fresh', 'exit_code': 0}, worker_name='replacement')
    assert database.fetch(job)['stdout'] == 'fresh'


def test_readiness_tracks_leases(client):
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 503
    database.heartbeat('live')
    assert client.get('/ready').json['workers']['active_workers'] == 1
    database.expire_worker('live')
    assert client.get('/ready').status_code == 503


def test_retention_keeps_pending_work(tmp_db_path, monkeypatch):
    monkeypatch.setenv('RESULT_RETENTION_SECONDS', '1')
    done = database.create_submission('python', 'print(1)')
    pending = database.create_submission('python', 'print(2)')
    database.store_result(done, {'exit_code': 0})
    with database._connect() as conn:
        conn.execute('UPDATE submissions SET submitted_at=?', (time.time() - 5,))
    assert database.prune_results() == 1
    assert database.fetch(done) is None
    assert database.fetch(pending)['status'] == 'queued'


@pytest.mark.parametrize('name,value', [('MAX_WORKERS','0'), ('TIMEOUT_SECONDS','nan'), ('SANDBOX_BACKEND','unknown')])
def test_invalid_config_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        config.validate()


def test_production_fails_closed(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SANDBOX_BACKEND', 'process')
    with pytest.raises(ValueError, match='Production requires'):
        config.validate()
    monkeypatch.setenv('SANDBOX_BACKEND', 'docker')
    monkeypatch.delenv('API_TOKEN', raising=False)
    with pytest.raises(ValueError, match='API_TOKEN'):
        config.validate()


def test_output_bounded_during_capture(tmp_path):
    result = run_command([sys.executable, '-c', 'while True: print("x" * 4096)'], cwd=str(tmp_path), max_output_bytes=2048, timeout=3)
    assert result['output_truncated'] is True
    assert result['exit_code'] != 0
    assert len(result['stdout'].encode()) + len(result['stderr'].encode()) <= 2048
    assert 'Output limit exceeded' in result['stderr']


def test_docker_never_falls_back(monkeypatch):
    monkeypatch.setenv('SANDBOX_BACKEND', 'docker')
    monkeypatch.setattr('sandbox.runtime.shutil.which', lambda _: None)
    result = run_language('python', 'print(42)')
    assert result['exit_code'] != 0
    assert result['stdout'] == ''
    assert 'No fallback' in result['stderr']


def test_python_classes_work():
    result = run_language('python', 'class Solution:\n    def answer(self):\n        return 42\nprint(Solution().answer())')
    assert result['stdout'].strip() == '42', result
    assert result['exit_code'] == 0


def test_docker_container_flags_and_cleanup(monkeypatch):
    import sandbox.runtime as runtime
    monkeypatch.setenv('SANDBOX_BACKEND', 'docker')
    monkeypatch.setattr(runtime.shutil, 'which', lambda _: 'docker')
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        result = {'stdout': '', 'stderr': '', 'exit_code': 0, 'timed_out': False, 'wall_time': 0.1, 'output_truncated': False}
        if argv[1] == 'start':
            result['stdout'] = json.dumps({**result, 'stdout': '42\n'})
        return result
    monkeypatch.setattr(runtime, 'run_command', command)
    assert runtime.run_language('python', 'print(42)')['stdout'] == '42\n'
    assert {'--network=none', '--read-only', '--cap-drop=ALL', '--user=65534:65534', '--rm'}.issubset(calls[0])
    assert '--privileged' not in calls[0]
    assert calls[-1][1:3] == ['rm', '--force']


def test_supervisor_recovers_crashed_worker(tmp_db_path, monkeypatch):
    from worker.pool import WorkerPool
    monkeypatch.setenv('TIMEOUT_SECONDS', '1')
    pool = WorkerPool(max_workers=1)
    pool.start()
    try:
        job = database.create_submission('python', 'while True: pass')
        deadline = time.monotonic() + 10
        while database.fetch(job)['status'] != 'running':
            assert time.monotonic() < deadline
            time.sleep(0.02)
        pool._procs[0].terminate()
        pool._procs[0].join(5)
        pool.watch()
        deadline = time.monotonic() + 15
        while database.fetch(job)['status'] != 'completed':
            assert time.monotonic() < deadline
            pool.watch()
            time.sleep(0.1)
        assert json.loads(database.fetch(job)['resource_usage'])['timed_out']
        assert pool.alive_count() == 1
    finally:
        pool.stop()
