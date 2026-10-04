"""scripts/tts.py で実際に Gemini を呼ぶテスト。GEMINI_API_KEY があるときだけ動く。

実行: uv run --env-file .env pytest -m integration tests/test_tts_integration.py
"""

import os
import subprocess
import sys
import wave
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY が未設定"),
]

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_makes_24khz_mono_16bit_wav(tmp_path: Path):
    out = tmp_path / "hai.wav"
    result = subprocess.run(
        ["uv", "run", "scripts/tts.py", "はい", "--out", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with wave.open(str(out), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
        assert w.getnframes() > 0
    assert result.stdout.startswith(f"{out} (")
