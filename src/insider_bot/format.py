"""返信文を組み立てる純粋関数。"""

from __future__ import annotations

import math

from insider_bot.game import Game
from insider_bot.judge import Verdict

BAR_CELLS = 12
QUESTION_DISPLAY_LIMIT = 200


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def yes_percent(yes_prob: float) -> int:
    return _round_half_up(min(max(yes_prob, 0.0), 1.0) * 100)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}時間{minutes}分{secs}秒"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def _shorten(question: str) -> str:
    if len(question) <= QUESTION_DISPLAY_LIMIT:
        return question
    return question[:QUESTION_DISPLAY_LIMIT] + "…"


def format_answer(question: str, verdict: Verdict) -> str:
    yes = yes_percent(verdict.yes_prob)
    label = "✅ はい" if yes >= 50 else "❌ いいえ"
    filled = _round_half_up(yes / 100 * BAR_CELLS)
    bar = "█" * filled + "░" * (BAR_CELLS - filled)
    return f"❓ {_shorten(question)}\n{label}　　はい {yes}% {bar} いいえ {100 - yes}%"


def format_correct(game: Game, answerer_name: str, elapsed: float) -> str:
    return (
        f"🎉 正解です！お題は「{game.topic}」でした\n"
        f"正解者: {answerer_name}　質問数: {game.question_count}　経過時間: {format_duration(elapsed)}"
    )


def format_giveup(game: Game) -> str:
    return f"🏳️ ギブアップ！お題は『{game.topic}』でした（質問数: {game.question_count}）"


def format_status(game: Game, elapsed: float) -> str:
    return (
        f"進行中のゲーム　出題者: {game.setter_name}　"
        f"質問数: {game.question_count}　経過時間: {format_duration(elapsed)}"
    )


def format_started(setter_name: str) -> str:
    return f"🎮 ゲーム開始！{setter_name}さんがお題を出しました。質問をどうぞ\n質問は最後に「？」をつけてね（例: 果物ですか？）"


def format_registered(topic: str) -> str:
    return f"お題『{topic}』を登録しました"


def format_already_running() -> str:
    return "このチャンネルではゲームが進行中です"


def format_no_game() -> str:
    return "進行中のゲームはありません"


def format_error() -> str:
    return "⚠️ 判定できませんでした。もう一度どうぞ"


def format_invalid_topic() -> str:
    return "お題を入力してください"
