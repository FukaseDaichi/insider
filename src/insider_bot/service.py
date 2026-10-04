"""ゲーム進行の中核。Discord に依存しないので、テキストでも音声でも同じ入口を使う。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from insider_bot import format as fmt
from insider_bot.game import Clock, GameAlreadyRunning, GameManager
from insider_bot.judge import Judge, JudgeError

log = logging.getLogger(__name__)

# 末尾がこれで終わる発言だけを質問として扱い、それ以外は雑談として無視する
_QUESTION_MARKS = ("？", "?")


def is_question(text: str) -> bool:
    return text.rstrip().endswith(_QUESTION_MARKS)


@dataclass(frozen=True)
class Outcome:
    """private は操作した本人だけに見せる本文、public はチャンネルに投稿する本文。

    yes_percent は「はい／いいえ」の返事のときだけ入る、はい の確からしさ（0〜100）。
    Web 版が返事の声を選ぶのに使う。正解・ギブアップ・エラーでは None。
    """

    private: str | None = None
    public: str | None = None
    yes_percent: int | None = None


IGNORED = Outcome()


class GameService:
    def __init__(self, manager: GameManager, judge: Judge, clock: Clock = time.monotonic) -> None:
        self._manager = manager
        self._judge = judge
        self._clock = clock
        # チャンネルごとのロック。参加チャンネル数ぶんしか増えないので削除しない
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, channel_id: int) -> asyncio.Lock:
        return self._locks.setdefault(channel_id, asyncio.Lock())

    async def start(self, channel_id: int, setter_id: int, setter_name: str, topic: str, hint: str) -> Outcome:
        topic, hint = topic.strip(), hint.strip()
        if not topic:
            return Outcome(private=fmt.format_invalid_topic())
        async with self._lock(channel_id):
            try:
                self._manager.start(channel_id, topic, hint, setter_id, setter_name)
            except GameAlreadyRunning:
                return Outcome(private=fmt.format_already_running())
        return Outcome(private=fmt.format_registered(topic), public=fmt.format_started(setter_name))

    async def status(self, channel_id: int) -> Outcome:
        async with self._lock(channel_id):
            game = self._manager.get(channel_id)
            if game is None:
                return Outcome(private=fmt.format_no_game())
            return Outcome(private=fmt.format_status(game, self._clock() - game.started_at))

    async def giveup(self, channel_id: int) -> Outcome:
        async with self._lock(channel_id):
            game = self._manager.end(channel_id)
            if game is None:
                return Outcome(private=fmt.format_no_game())
            return Outcome(public=fmt.format_giveup(game))

    async def handle_question(
        self, channel_id: int, author_id: int, author_name: str, text: str, setter_can_ask: bool = False
    ) -> Outcome:
        """channel_id はゲームを登録したテキストチャンネルの ID。

        setter_can_ask が真なら出題者の質問も判定する（Web 版は出題者を伏せて質問者に紛れ込ませる）。
        """
        received = self._manager.get(channel_id)
        if received is None:
            return IGNORED
        async with self._lock(channel_id):
            game = self._manager.get(channel_id)
            if game is None or game.game_id != received.game_id:
                return IGNORED
            if (author_id == game.setter_id and not setter_can_ask) or not is_question(text):
                return IGNORED
            try:
                verdict = await self._judge.judge(game.topic, game.hint, text)
            except JudgeError as error:
                log.warning("判定に失敗しました（channel=%s）: %s", channel_id, error)
                return Outcome(public=fmt.format_error())
            game.question_count += 1
            if verdict.is_correct:
                self._manager.end(channel_id)
                return Outcome(public=fmt.format_correct(game, author_name, self._clock() - game.started_at))
            return Outcome(public=fmt.format_answer(text, verdict), yes_percent=fmt.yes_percent(verdict.yes_prob))
