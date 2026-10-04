"""scripts/tts.py の、Gemini を呼ばない部分のテスト。"""

import io
import wave
from pathlib import Path

import pytest

from scripts.tts import (
    DEFAULT_VOICE,
    MODEL,
    afconvert_command,
    build_request,
    m4a_path,
    main,
    output_paths,
    read_api_key,
    wav_duration,
)


def make_wav(seconds: float, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * seconds))
    return buffer.getvalue()


# --- API キー


def test_api_key_comes_from_environment_first(tmp_path: Path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=from-file\n")
    assert read_api_key({"GEMINI_API_KEY": "from-env"}, tmp_path / ".env") == "from-env"


def test_api_key_falls_back_to_dotenv_file(tmp_path: Path):
    (tmp_path / ".env").write_text('# コメント\nDISCORD_TOKEN=x\nGEMINI_API_KEY="from-file"\n')
    assert read_api_key({}, tmp_path / ".env") == "from-file"


def test_api_key_missing_everywhere(tmp_path: Path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=\n")
    assert read_api_key({}, tmp_path / ".env") is None
    assert read_api_key({}, tmp_path / "none.env") is None


# --- 出力先


def test_single_take_uses_out_as_is():
    assert output_paths(Path("assets/sounds/no-1.wav"), 1) == [Path("assets/sounds/no-1.wav")]


def test_multiple_takes_get_branch_numbers():
    assert output_paths(Path("assets/sounds/no-1.wav"), 3) == [
        Path("assets/sounds/no-1-1.wav"),
        Path("assets/sounds/no-1-2.wav"),
        Path("assets/sounds/no-1-3.wav"),
    ]


def test_m4a_goes_to_static_sounds_with_same_name():
    assert m4a_path(Path("assets/sounds/no-1-2.wav"), Path("static/sounds")) == Path("static/sounds/no-1-2.m4a")


def test_afconvert_command_makes_aac():
    assert afconvert_command(Path("a.wav"), Path("b.m4a")) == ["afconvert", "-f", "m4af", "-d", "aac", "a.wav", "b.m4a"]


# --- リクエスト


def test_request_puts_style_in_speech_metadata_not_in_text():
    request = build_request("いいえ、違います！", "Zephyr", "きっぱり")
    assert request["model"] == MODEL
    content = request["input"][0]["content"][0]
    assert content["text"] == "いいえ、違います！"
    assert content["annotations"] == [{"type": "speech_metadata", "style": "きっぱり"}]
    assert request["response_format"] == {"type": "audio"}
    assert request["generation_config"] == {"speech_config": [{"voice": "Zephyr"}]}


def test_request_without_style_has_no_annotations():
    content = build_request("はい", "Kore", None)["input"][0]["content"][0]
    assert "annotations" not in content


# --- WAV の長さ


def test_wav_duration_in_seconds():
    assert wav_duration(make_wav(1.5)) == pytest.approx(1.5)


# --- main


class Recorder:
    def __init__(self, wav: bytes = b""):
        self.wav = wav or make_wav(0.5)
        self.requests: list[dict] = []
        self.converted: list[tuple[Path, Path]] = []

    def synthesize(self, request: dict) -> bytes:
        self.requests.append(request)
        return self.wav

    def convert(self, wav: Path, m4a: Path) -> None:
        self.converted.append((wav, m4a))
        m4a.write_bytes(b"aac")


def run(argv: list[str], tmp_path: Path, recorder: Recorder | None = None, env: dict | None = None, capsys=None):
    recorder = recorder or Recorder()
    code = main(
        argv,
        env={"GEMINI_API_KEY": "k"} if env is None else env,
        dotenv=tmp_path / "missing.env",
        static_dir=tmp_path / "static",
        synthesize=recorder.synthesize,
        convert=recorder.convert,
    )
    return code, recorder


def test_main_writes_returned_wav_as_is(tmp_path: Path, capsys):
    out = tmp_path / "deep" / "no-1.wav"
    code, recorder = run(["いいえ", "--out", str(out)], tmp_path)
    assert code == 0
    assert out.read_bytes() == recorder.wav
    assert recorder.requests[0]["generation_config"] == {"speech_config": [{"voice": DEFAULT_VOICE}]}
    assert recorder.converted == []
    assert capsys.readouterr().out == f"{out} (0.50 秒)\n"


def test_main_passes_voice_and_style(tmp_path: Path):
    _, recorder = run(["はい", "--out", str(tmp_path / "y.wav"), "--voice", "Kore", "--style", "明るく"], tmp_path)
    assert recorder.requests == [build_request("はい", "Kore", "明るく")]


def test_main_makes_each_take_and_m4a(tmp_path: Path):
    out = tmp_path / "no-1.wav"
    code, recorder = run(["いいえ", "--out", str(out), "--takes", "2", "--m4a"], tmp_path)
    assert code == 0
    assert len(recorder.requests) == 2
    assert (tmp_path / "no-1-1.wav").exists() and (tmp_path / "no-1-2.wav").exists()
    assert recorder.converted == [
        (tmp_path / "no-1-1.wav", tmp_path / "static" / "no-1-1.m4a"),
        (tmp_path / "no-1-2.wav", tmp_path / "static" / "no-1-2.m4a"),
    ]


def test_main_without_key_explains_and_stops(tmp_path: Path, capsys):
    code, recorder = run(["はい", "--out", str(tmp_path / "y.wav")], tmp_path, env={})
    assert code == 1
    assert recorder.requests == []
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err and "AI Studio" in err and ".env" in err


def test_main_rejects_non_wav_out(tmp_path: Path, capsys):
    code, recorder = run(["はい", "--out", str(tmp_path / "y.mp3")], tmp_path)
    assert code == 2
    assert recorder.requests == []


def test_main_reports_api_failure(tmp_path: Path, capsys):
    def boom(request):
        raise RuntimeError("quota exceeded")

    recorder = Recorder()
    recorder.synthesize = boom
    code, _ = run(["はい", "--out", str(tmp_path / "y.wav")], tmp_path, recorder)
    assert code == 1
    assert "quota exceeded" in capsys.readouterr().err
