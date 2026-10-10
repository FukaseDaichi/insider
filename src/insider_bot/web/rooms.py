"""Web 版のルームと参加者。ネットワークにも GameService にも依存しない。"""

from __future__ import annotations

import itertools
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from insider_bot.game import Clock
from insider_bot.web.insider import InsiderRound

# 紛らわしい 0・O・1・I・L を除く
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
MAX_ROOMS = 50
MAX_PLAYERS = 20
NAME_MAX = 20
LOG_LIMIT = 300
UNJOINED_TTL_SECONDS = 10 * 60
IDLE_TTL_SECONDS = 6 * 60 * 60


class RoomNotFound(Exception):
    """ルームがない（番号違い・片付け済み・サーバーの再起動）。"""


class RoomFull(Exception):
    """参加者が上限に達していて、新しい参加者を作れない。"""


class RoomLimitReached(Exception):
    """ルーム数が上限で、空けられるルームもない。"""


class InvalidName(Exception):
    """名前が空か長すぎる。"""


@dataclass(eq=False)
class Player:
    player_id: int
    name: str
    token: str


@dataclass(eq=False)
class Entry:
    entry_id: int
    author: str | None
    text: str
    pending: bool = False
    # 文字の読み解きではなく構造で描く記録（インサイダーゲームの結果）。ほかの記録は None のまま
    kind: str | None = None
    data: dict[str, Any] | None = None

    def to_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "id": self.entry_id,
            "author": self.author,
            "text": self.text,
            "pending": self.pending,
        }
        if self.kind is not None:
            message["kind"] = self.kind
            message["data"] = self.data
        return message


@dataclass(eq=False)
class Room:
    room_id: int
    code: str
    last_active: float
    joined: bool = False
    players: dict[str, Player] = field(default_factory=dict)
    connections: dict[object, Player] = field(default_factory=dict)
    log: list[Entry] = field(default_factory=list)
    # いまのインサイダーゲーム。終わった回も、次のゲームが始まるまで役職のカードを開き直せるよう残す
    insider: InsiderRound | None = None
    _entry_ids: itertools.count = field(default_factory=lambda: itertools.count(1), init=False, repr=False)

    def is_online(self, player: Player) -> bool:
        return any(owner is player for owner in self.connections.values())

    def add_entry(
        self,
        author: str | None,
        text: str,
        pending: bool = False,
        kind: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Entry:
        entry = Entry(next(self._entry_ids), author, text, pending, kind, data)
        self.log.append(entry)
        del self.log[:-LOG_LIMIT]
        return entry


class RoomRegistry:
    def __init__(
        self,
        clock: Clock = time.monotonic,
        on_remove: Callable[[Room], None] = lambda room: None,
        max_rooms: int = MAX_ROOMS,
        max_players: int = MAX_PLAYERS,
    ) -> None:
        self._clock = clock
        self._on_remove = on_remove
        self._max_rooms = max_rooms
        self._max_players = max_players
        self._rooms: dict[str, Room] = {}
        self._room_ids = itertools.count(1)
        self._player_ids = itertools.count(1)

    def get(self, code: str) -> Room | None:
        return self._rooms.get(code)

    def create(self) -> Room:
        if len(self._rooms) >= self._max_rooms:
            # 作成に認証がないので、空のルームを大量に作られても遊んでいる人のルームは消さない
            idle = [room for room in self._rooms.values() if not room.connections]
            if not idle:
                raise RoomLimitReached()
            self._remove(min(idle, key=lambda room: room.last_active))
        code = self._new_code()
        room = Room(room_id=next(self._room_ids), code=code, last_active=self._clock())
        self._rooms[code] = room
        return room

    def join(self, room: Room, token: str | None, name: str) -> Player:
        """合言葉が一致すれば既存の参加者を返す（名前は変えない）。それ以外は新しい参加者を作る。"""
        if token is not None and token in room.players:
            return room.players[token]
        name = name.strip()
        if not 1 <= len(name) <= NAME_MAX:
            raise InvalidName(name)
        if len(room.players) >= self._max_players:
            raise RoomFull(room.code)
        player = Player(next(self._player_ids), name, secrets.token_urlsafe(16))
        room.players[player.token] = player
        room.joined = True
        return player

    def attach(self, room: Room, conn: object, player: Player) -> None:
        room.connections[conn] = player
        room.last_active = self._clock()

    def detach(self, room: Room, conn: object) -> None:
        room.connections.pop(conn, None)
        room.last_active = self._clock()

    def cleanup(self) -> None:
        now = self._clock()
        for room in list(self._rooms.values()):
            if room.connections:
                continue
            ttl = IDLE_TTL_SECONDS if room.joined else UNJOINED_TTL_SECONDS
            if now - room.last_active >= ttl:
                self._remove(room)

    def _remove(self, room: Room) -> None:
        del self._rooms[room.code]
        self._on_remove(room)

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code
