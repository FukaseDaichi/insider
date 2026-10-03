"""村の状態と不変条件。ネットワークに依存しない。

Java では synchronized で守っていた操作（人数確定と配役抽選、お題設定、逆村化、参加）は、
asyncio 単一スレッドでは「1 つの同期メソッドで完結し、途中で await しない」ことで同じ保証になる。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from insider_bot.village import texts


class Rng(Protocol):
    def randrange(self, n: int, /) -> int: ...

    def shuffle(self, seq: list, /) -> None: ...


class Role(Enum):
    INSIDER = "INSIDER"
    VILLAGER = "VILLAGER"
    GAME_MASTER = "GAME_MASTER"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def illust_key(self) -> str:
        """役職画像のカタログで使う名前。"""
        return _ILLUST_KEYS[self]


_LABELS = {Role.INSIDER: texts.INSIDER_ROLE, Role.VILLAGER: texts.VILLAGER_ROLE, Role.GAME_MASTER: texts.GAME_MASTER_ROLE}
_ILLUST_KEYS = {Role.INSIDER: "INSIDER", Role.VILLAGER: "VILLAGERS", Role.GAME_MASTER: "GM"}

# 席番号としてあり得ない値を「GM を立てる村だが、人数が未確定で席が未抽選」の印に使う
GOD_MODE_PENDING = 999


@dataclass(frozen=True)
class Seat:
    user_id: str
    role: Role


@dataclass(eq=False)
class Village:
    owner_id: str
    number: int = 0
    topic: str | None = None
    size: int = 0
    insider_seat: int = 0
    gm_seat: int = 0
    reverse: bool = False
    random_mode: bool = False
    seats: list[Seat] = field(default_factory=list)

    def set_topic(self, topic: str) -> bool:
        """一度だけ設定できる。設定済みなら False。"""
        if self.topic is not None:
            return False
        self.topic = topic
        return True

    def mark_god_mode(self) -> None:
        self.gm_seat = GOD_MODE_PENDING

    def is_god_mode_awaiting_size(self) -> bool:
        return self.gm_seat == GOD_MODE_PENDING

    def has_game_master(self) -> bool:
        return self.gm_seat != 0

    def has_members(self) -> bool:
        return bool(self.seats)

    def member_count(self) -> int:
        return len(self.seats)

    def configure(self, size: int, rng: Rng) -> bool:
        """人数を確定し、インサイダーと（神モードなら）GM の席を抽選する。設定済みなら False。

        配役を決めてから size を書くので、「人数は決まったが配役は未確定」の状態は観測されない。
        ランダム村ではオーナーも参加者なので、同じ操作の中で先頭に着席させる。
        """
        if self.size != 0:
            return False
        self.insider_seat = rng.randrange(size) + 1
        if self.gm_seat == GOD_MODE_PENDING:
            candidate = rng.randrange(size) + 1
            while candidate == self.insider_seat:
                candidate = rng.randrange(size) + 1
            self.gm_seat = candidate
        self.size = size
        if self.random_mode:
            self.join(self.owner_id)
        return True

    def join(self, user_id: str) -> Seat | None:
        """参加させて配役する。参加済みなら同じ席を返す。満員（人数未設定を含む）なら None。"""
        for seat in self.seats:
            if seat.user_id == user_id:
                return seat
        if len(self.seats) >= self.size:
            return None
        seat = Seat(user_id, self._role_for(len(self.seats) + 1))
        self.seats.append(seat)
        return seat

    def role_of(self, user_id: str) -> Role | None:
        for seat in self.seats:
            if seat.user_id == user_id:
                return seat.role
        return None

    def seat_number_of(self, user_id: str) -> int:
        """参加順の番号（1 始まり）。未参加なら 0。"""
        for index, seat in enumerate(self.seats, start=1):
            if seat.user_id == user_id:
                return index
        return 0

    def apply_reverse(self) -> bool:
        """誰も参加していないときだけ逆村にする。参加者がいれば False。"""
        if self.seats:
            return False
        self.reverse = True
        return True

    def _role_for(self, seat_number: int) -> Role:
        """逆村はインサイダーと村人を入れ替える。GM の席は変わらない。"""
        if seat_number == self.insider_seat:
            return Role.VILLAGER if self.reverse else Role.INSIDER
        if seat_number == self.gm_seat:
            return Role.GAME_MASTER
        return Role.INSIDER if self.reverse else Role.VILLAGER


class SpecialVillage:
    """任意のメッセージ集合を参加順に 1 通ずつ配る村。

    不変条件は「i 番目の参加者に i 番目のメッセージが対応する」ことと「参加者数はメッセージ数を超えない」こと。
    配布順は作成時に確定し（並べ替えは作る側の責務）、以降は参加者が増えるだけ。
    """

    def __init__(self, messages: Sequence[str | None]) -> None:
        self.messages: tuple[str | None, ...] = tuple(messages)
        self.number: int = 0
        self.members: list[str] = []

    def capacity(self) -> int:
        return len(self.messages)

    def member_count(self) -> int:
        return len(self.members)

    def has_member(self, user_id: str) -> bool:
        return user_id in self.members

    def join(self, user_id: str) -> bool:
        """参加済みなら True のまま。満員なら False。"""
        if user_id in self.members:
            return True
        if len(self.members) >= len(self.messages):
            return False
        self.members.append(user_id)
        return True

    def seat_number_of(self, user_id: str) -> int:
        try:
            return self.members.index(user_id) + 1
        except ValueError:
            return 0

    def message_for(self, user_id: str) -> str | None:
        """未参加なら None。空や None のメッセージは「メッセージは特にありません。」。"""
        seat = self.seat_number_of(user_id)
        if seat == 0:
            return None
        message = self.messages[seat - 1]
        return message if message else texts.NO_SPECIAL_MESSAGE
