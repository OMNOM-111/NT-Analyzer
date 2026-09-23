from pathlib import Path
import subprocess


def test_inline_model_test_lifecycle():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', 'tests/model_inline_test_harness.cjs'], cwd=root,
        capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'PASS'
