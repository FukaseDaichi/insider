#!/usr/bin/env python3
"""アイドル回収を外すためのメモリ床の差し替え: 指定の大きさを確保してページを触り、眠り続ける。

insider-memfloor.service (3GB の tmpfs) を OCI の MemoryUtilization が使用中に数えなかったときだけ、
insider-memfloor-process.service から使う。標準ライブラリだけで動き、VM の /usr/bin/python3 で足りる。

使い方: python3 deploy/memfloor.py [--size-mb 3072] [--once]
  --once は検証用で、埋めたらすぐ終わる。
"""

from __future__ import annotations

import signal
import sys

PAGE = 4096
DEFAULT_MB = 3072


def fill(size_bytes: int) -> bytearray:
    """size_bytes の bytearray を作り、ページごとに 1 バイト書いて実メモリに載せる。

    bytearray(n) だけでは OS がページを遅延で割り当てるので RSS が増えない。
    """
    buffer = bytearray(size_bytes)
    for offset in range(0, size_bytes, PAGE):
        buffer[offset] = 1
    return buffer


def parse_size_mb(argv: list[str]) -> int:
    size_mb = DEFAULT_MB
    if "--size-mb" in argv:
        raw = argv[argv.index("--size-mb") + 1] if argv.index("--size-mb") + 1 < len(argv) else ""
        try:
            size_mb = int(raw)
        except ValueError:
            print(f"--size-mb は整数で指定してください（現在: {raw!r}）", file=sys.stderr)
            raise SystemExit(2) from None
    if size_mb <= 0:
        print(f"--size-mb は 1 以上にしてください（現在: {size_mb}）", file=sys.stderr)
        raise SystemExit(2)
    return size_mb * 1024 * 1024


def main(argv: list[str]) -> None:
    size_bytes = parse_size_mb(argv)
    held = fill(size_bytes)
    print(f"{size_bytes // (1024 * 1024)} MB を確保しました", flush=True)
    if "--once" in argv:
        return
    # SIGTERM (systemctl stop) で素直に終わる。確保したメモリはプロセスと一緒に返る
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        signal.pause()
    del held  # 到達しないが、確保した参照を関数の最後まで持つ意図を示す


if __name__ == "__main__":
    main(sys.argv[1:])
