import subprocess
import sys
from pathlib import Path

from deploy.memfloor import PAGE, fill, parse_size_mb

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "memfloor.py"


def test_fill_touches_every_page_so_the_pages_become_resident():
    buffer = fill(3 * PAGE + 1)
    assert len(buffer) == 3 * PAGE + 1
    # 書き込んだページだけが実メモリに載る。先頭・途中・最後のページと端数のページをすべて触っている
    assert all(buffer[offset] == 1 for offset in (0, PAGE, 2 * PAGE, 3 * PAGE))


def test_size_is_megabytes_and_must_be_positive():
    assert parse_size_mb(["--size-mb", "2"]) == 2 * 1024 * 1024
    assert parse_size_mb([]) == 3 * 1024 * 1024 * 1024
    for bad in (["--size-mb", "0"], ["--size-mb", "-1"], ["--size-mb", "x"]):
        try:
            parse_size_mb(bad)
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError(f"{bad} を受け付けてしまった")


def test_once_fills_and_exits_without_sleeping():
    # --once は検証用。埋めたら眠らずに終わる (本番は眠り続けて systemd に止められる)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--size-mb", "1", "--once"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "1 MB" in result.stdout
