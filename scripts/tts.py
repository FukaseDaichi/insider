# /// script
# requires-python = ">=3.13"
# dependencies = ["google-genai>=2.25.0"]
# ///
"""Gemini TTS でセリフから WAV を作る。

実行: uv run scripts/tts.py "いいえ、違います！" --out assets/sounds/no-1.wav
        [--voice Zephyr] [--style "きっぱり、少し残念そうに"] [--takes 3] [--m4a]

API キーは環境変数 GEMINI_API_KEY か、リポジトリ直下の .env から読む。
返ってくる WAV（24kHz・モノラル・16bit）をそのまま書き、--m4a なら afconvert で配信用の AAC も作る。
"""

from __future__ import annotations

import argparse
import base64
import io
import subprocess
import sys
import wave
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Zephyr"
REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV = REPO_ROOT / ".env"
STATIC_SOUNDS = REPO_ROOT / "src" / "insider_bot" / "web" / "static" / "sounds"

NO_KEY = (
    "GEMINI_API_KEY がありません。\n"
    "AI Studio（https://aistudio.google.com/）の左下の鍵アイコンで API キーを作り、\n"
    ".env に GEMINI_API_KEY=... と書くか、環境変数で渡してください。"
)

Synthesize = Callable[[dict[str, Any]], bytes]
Convert = Callable[[Path, Path], None]


def read_api_key(env: Mapping[str, str], dotenv: Path) -> str | None:
    """環境変数を優先し、無ければ .env の GEMINI_API_KEY= の行から読む。空なら None。"""
    key = env.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if not dotenv.is_file():
        return None
    for line in dotenv.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == "GEMINI_API_KEY":
            value = value.strip().strip("'\"")
            return value or None
    return None


def output_paths(out: Path, takes: int) -> list[Path]:
    """1 本なら --out のまま。2 本以上なら no-1.wav → no-1-1.wav, no-1-2.wav, … と枝番を付ける。"""
    if takes <= 1:
        return [out]
    return [out.with_name(f"{out.stem}-{n}{out.suffix}") for n in range(1, takes + 1)]


def m4a_path(wav: Path, static_dir: Path) -> Path:
    return static_dir / f"{wav.stem}.m4a"


def afconvert_command(wav: Path, m4a: Path) -> list[str]:
    return ["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(m4a)]


def build_request(text: str, voice: str, style: str | None) -> dict[str, Any]:
    """Interactions API の引数。話し方は本文に混ぜず speech_metadata.style で渡す（本文は一字一句そのまま読まれる）。"""
    content: dict[str, Any] = {"type": "text", "text": text}
    if style:
        content["annotations"] = [{"type": "speech_metadata", "style": style}]
    return {
        "model": MODEL,
        "input": [{"type": "user_input", "content": [content]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }


def wav_duration(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / w.getframerate()


def synthesize_with_gemini(api_key: str) -> Synthesize:
    from google import genai  # 実行時にだけ要る。テストでは差し替える

    client = genai.Client(api_key=api_key)

    def synthesize(request: dict[str, Any]) -> bytes:
        interaction = client.interactions.create(**request)
        return base64.b64decode(interaction.output_audio.data)

    return synthesize


def convert_with_afconvert(wav: Path, m4a: Path) -> None:
    m4a.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(afconvert_command(wav, m4a), check=True, capture_output=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini TTS でセリフから WAV を作る")
    parser.add_argument("text", help="読み上げるセリフ（そのまま読まれる）")
    parser.add_argument("--out", required=True, type=Path, help="WAV の出力先（.wav）")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"話者名（既定 {DEFAULT_VOICE}）")
    parser.add_argument("--style", help="話し方（例: きっぱり、少し残念そうに）")
    parser.add_argument("--takes", type=int, default=1, help="作る本数。2 以上なら枝番を付ける")
    parser.add_argument("--m4a", action="store_true", help="配信用の AAC も src/insider_bot/web/static/sounds/ に作る")
    args = parser.parse_args(argv)
    if args.out.suffix.lower() != ".wav":
        parser.error("--out は .wav で終わるパスにしてください")
    if args.takes < 1:
        parser.error("--takes は 1 以上にしてください")
    return args


def main(
    argv: list[str],
    *,
    env: Mapping[str, str],
    dotenv: Path = DOTENV,
    static_dir: Path = STATIC_SOUNDS,
    synthesize: Synthesize | None = None,
    convert: Convert = convert_with_afconvert,
) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    api_key = read_api_key(env, dotenv)
    if api_key is None:
        print(NO_KEY, file=sys.stderr)
        return 1
    if synthesize is None:
        synthesize = synthesize_with_gemini(api_key)

    request = build_request(args.text, args.voice, args.style)
    for wav in output_paths(args.out, args.takes):
        try:
            data = synthesize(request)
        except Exception as e:  # 手作業の道具なので、API の失敗はそのまま見せて止まる
            print(f"生成に失敗しました: {e}", file=sys.stderr)
            return 1
        wav.parent.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(data)
        if args.m4a:
            try:
                convert(wav, m4a_path(wav, static_dir))
            except FileNotFoundError:
                print(f"afconvert が無いので {wav} の AAC は作りませんでした", file=sys.stderr)
        print(f"{wav} ({wav_duration(data):.2f} 秒)")
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main(sys.argv[1:], env=os.environ))
