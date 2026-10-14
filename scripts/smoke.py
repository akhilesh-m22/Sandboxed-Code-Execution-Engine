"""Exercise a running demo through HTTP, using only the Python standard library."""
import argparse
import json
import os
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5000')
    args = parser.parse_args()
    def request(path, body=None):
        headers = {'Content-Type': 'application/json'}
        if os.environ.get('API_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['API_TOKEN']
        req = urllib.request.Request(args.url.rstrip('/') + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)
    assert request('/ready')['ok'], 'No ready workers'
    jobs = [('Success', 'print(input().upper())', 'codeforge', 'CODEFORGE', 0),
            ('Runtime error', '1 / 0', '', None, None),
            ('Timeout', 'while True: pass', '', None, None)]
    for name, source, stdin, output, exit_code in jobs:
        submission = request('/submit', {'language': 'python', 'source': source, 'stdin': stdin})
        deadline = time.monotonic() + 60
        while request('/status/' + submission['id'])['status'] in ('queued', 'running'):
            if time.monotonic() > deadline:
                raise TimeoutError('Job did not finish')
            time.sleep(0.2)
        result = request('/result/' + submission['id'])
        if output is not None:
            assert result['stdout'].strip() == output, result
            assert result['exit_code'] == exit_code, result
        else:
            assert result['exit_code'] != 0, result
        if name == 'Timeout':
            assert result['resource_usage']['timed_out'], result
        print(f"PASS {name}: {submission['id']}")
    print('HTTP smoke check passed.')


if __name__ == '__main__':
    main()
