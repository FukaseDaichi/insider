import pytest

from insider_bot.format import (
    format_already_running,
    format_answer,
    format_correct,
    format_duration,
    format_error,
    format_giveup,
    format_invalid_topic,
    format_no_game,
    format_registered,
    format_started,
    format_status,
    yes_percent,
)
from insider_bot.game import Game
from insider_bot.judge import Verdict


def make_game(**overrides) -> Game:
    fields = dict(
        game_id=1, channel_id=1, topic="りんご", hint="", setter_id=10,
        setter_name="出題者", started_at=0.0, question_count=14,
    )
    fields.update(overrides)
    return Game(**fields)


@pytest.mark.parametrize(
    ("prob", "pct"),
    [(0.0, 0), (1.0, 100), (0.82, 82), (0.825, 83), (0.004, 0), (0.995, 100), (-0.1, 0), (1.2, 100)],
)
def test_yes_percent_rounds_half_up_and_clamps(prob, pct):
    assert yes_percent(prob) == pct


def test_format_answer_yes():
    text = format_answer("果物ですか？", Verdict(0.82, False, "jev"))
    assert text == "❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%"


def test_format_answer_no():
    text = format_answer("動物ですか？", Verdict(0.1, False, "jev"))
    assert text == "❓ 動物ですか？\n❌ いいえ　　はい 10% █░░░░░░░░░░░ いいえ 90%"


def test_label_follows_rounded_percent_at_boundary():
    # 0.496 は 50% と表示されるので、ラベルも「はい」にそろえる
    assert "✅ はい　　はい 50%" in format_answer("q", Verdict(0.496, False, "jev"))
    assert "❌ いいえ　　はい 49%" in format_answer("q", Verdict(0.494, False, "jev"))


def test_long_question_is_truncated_for_display():
    text = format_answer("あ" * 250, Verdict(0.5, False, "jev"))
    first_line = text.split("\n")[0]
    assert first_line == "❓ " + "あ" * 200 + "…"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0秒"), (45.9, "45秒"), (392, "6分32秒"), (3723, "1時間2分3秒"), (3600, "1時間0分0秒")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_correct():
    text = format_correct(make_game(), "回答者", 392)
    assert text == "🎉 正解です！お題は「りんご」でした\n正解者: 回答者　質問数: 14　経過時間: 6分32秒"


def test_format_giveup():
    assert format_giveup(make_game(question_count=3)) == "🏳️ ギブアップ！お題は『りんご』でした（質問数: 3）"


def test_format_status_does_not_reveal_topic():
    text = format_status(make_game(question_count=5), 65)
    assert text == "進行中のゲーム　出題者: 出題者　質問数: 5　経過時間: 1分5秒"
    assert "りんご" not in text


def test_fixed_messages():
    assert format_started("出題者") == "🎮 ゲーム開始！出題者さんがお題を出しました。質問をどうぞ"
    assert format_registered("りんご") == "お題『りんご』を登録しました"
    assert format_already_running() == "このチャンネルではゲームが進行中です"
    assert format_no_game() == "進行中のゲームはありません"
    assert format_error() == "⚠️ 判定できませんでした。もう一度どうぞ"
    assert format_invalid_topic() == "お題を入力してください"
