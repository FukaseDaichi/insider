"""ゲームの状態（1 チャンネル 1 ゲーム）。Discord や Jev には依存しない。"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Callable

Clock = Callable[[], float]


@dataclass
class Game:
    game_id: int
    channel_id: int
    topic: str
    hint: str
    setter_id: int
    setter_name: str
    started_at: float
    question_count: int = 0


class GameAlreadyRunning(Exception):
    """そのチャンネルでは既にゲームが進行中。"""


class GameManager:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._games: dict[int, Game] = {}
        self._ids = itertools.count(1)

    def start(self, channel_id: int, topic: str, hint: str, setter_id: int, setter_name: str) -> Game:
        if channel_id in self._games:
            raise GameAlreadyRunning(channel_id)
        game = Game(
            game_id=next(self._ids),
            channel_id=channel_id,
            topic=topic,
            hint=hint,
            setter_id=setter_id,
            setter_name=setter_name,
            started_at=self._clock(),
        )
        self._games[channel_id] = game
        return game

    def get(self, channel_id: int) -> Game | None:
        return self._games.get(channel_id)

    def end(self, channel_id: int) -> Game | None:
        return self._games.pop(channel_id, None)
