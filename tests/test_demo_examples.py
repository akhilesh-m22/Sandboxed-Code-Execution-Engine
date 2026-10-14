"""Keep the exact starter programs shipped in the browser executable."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import sandbox

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def examples():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed to extract browser starter programs')
    script = """
const fs = require('fs'), vm = require('vm');
const context = { window: {}, document: { readyState: 'loading', addEventListener() {} } };
vm.runInNewContext(fs.readFileSync('frontend/js/app.js', 'utf8'), context);
process.stdout.write(JSON.stringify(context.window.CodeForge.PROBLEMS));
"""
    result = subprocess.run([node, '-e', script], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('name', ['two-sum', 'palindrome-number', 'valid-parentheses', 'max-subarray', 'prime-sieve'])
@pytest.mark.parametrize('language', ['python', 'c'])
def test_starter_passes_its_examples(examples, name, language):
    if language == 'c' and not any(shutil.which(c) for c in ('gcc', 'cc', 'clang')):
        pytest.skip('C compiler unavailable on this host')
    example = examples[name]
    for case in example['testcases']:
        result = sandbox.run_code(language, example['starter'][language], stdin=case['stdin'])
        assert result['exit_code'] == 0, result
        assert result['stdout'].strip() == case['expected'].strip(), result
