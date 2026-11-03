import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")


def test_frontend_javascript():
    if NODE is None:
        pytest.skip("Node.js is required for frontend JavaScript tests")
    test_file = Path(__file__).with_name("test_web_ui.cjs")
    result = subprocess.run(
        [NODE, "--test", str(test_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
