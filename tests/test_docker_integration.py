"""Opt-in real Linux container tests, executed by the Docker CI job."""
import os

import pytest

import sandbox

pytestmark = pytest.mark.skipif(os.environ.get('RUN_DOCKER_TESTS') != '1', reason='Requires built Docker runner; set RUN_DOCKER_TESTS=1')


@pytest.fixture(autouse=True)
def docker_backend(monkeypatch):
    monkeypatch.setenv('SANDBOX_BACKEND', 'docker')


@pytest.mark.parametrize('language,source,expected', [
    ('python', 'print(input().upper())', 'HELLO'),
    ('c', '#include <stdio.h>\nint main(void) { puts("hello"); return 0; }', 'hello'),
])
def test_real_container(language, source, expected):
    result = sandbox.run_code(language, source, stdin='hello')
    assert result['exit_code'] == 0, result
    assert result['stdout'].strip() == expected


def test_real_container_timeout():
    result = sandbox.run_code('python', 'while True: pass', timeout=1)
    assert result['timed_out'] is True
    assert result['exit_code'] != 0


def test_container_has_no_host_project():
    from sandbox.runtime import _run_docker
    # Direct backend call bypasses the convenience source filters to test the boundary.
    source = '#include <stdio.h>\n#include <unistd.h>\nint main(void) { printf("%d\\n", access("/app/database.py", F_OK)); return 0; }'
    result = _run_docker('c', source, b'', 2, 2, 256, 4096)
    assert result['exit_code'] == 0, result
    assert result['stdout'].strip() == '-1'
