"""ルームのインサイダーゲーム 1 回分の状態と決まり。ネットワーク・asyncio・GameService に依存しない。

段階は お題待ち（choosing）→ 質問（asking）→ 投票（voting）→ 終わり（done）。
お題がランダムか始める人が決める場合は、配ってすぐ質問に進む（choosing を通らない）。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

MIN_PARTICIPANTS = 3
MIN_MINUTES = 1
MAX_MINUTES = 30
TOPIC_MAX = 50
TOPIC_MODES = ("random", "self", "insider")


class Rng(Protocol):
    def randrange(self, n: int) -> int: ...


class Phase(StrEnum):
    CHOOSING = "choosing"
    ASKING = "asking"
    VOTING = "voting"
    DONE = "done"


# この段階の間は、ルームでほかのゲームを始められない
ACTIVE_PHASES = (Phase.CHOOSING, Phase.ASKING, Phase.VOTING)


class Ending(StrEnum):
    VOTED = "voted"
    TIME_UP = "time_up"
    GIVEUP = "giveup"


class InvalidSetup(Exception):
    """設定やお題が正しくない。文はそのまま押した人に見せる。"""


@dataclass(frozen=True)
class Setup:
    participants: tuple[int, ...]
    topic_mode: str
    topic: str | None
    minutes: int | None


def check_topic(topic: str) -> str:
    topic = topic.strip()
    if not 1 <= len(topic) <= TOPIC_MAX:
        raise InvalidSetup(f"お題は1〜{TOPIC_MAX}文字で入力してください")
    return topic


def check_setup(
    room_player_ids: Collection[int],
    starter_id: int,
    participants: Sequence[int],
    topic_mode: str,
    topic: str | None,
    minutes: int | None,
) -> Setup:
    """画面から届いた設定を確かめて整える。正しくなければ InvalidSetup。"""
    if topic_mode not in TOPIC_MODES:
        raise InvalidSetup("お題の決め方が正しくありません")
    # 同じ人を 2 回送られても 1 人に数える。並びは選んだ順のまま
    chosen = tuple(dict.fromkeys(participants))
    if any(player_id not in room_player_ids for player_id in chosen):
        raise InvalidSetup("ルームにいない人は選べません")
    if topic_mode == "self" and starter_id in chosen:
        # お題を知る人が質問に紛れると、ゲームが成り立たない
        raise InvalidSetup("お題を決める人は参加者になれません")
    if len(chosen) < MIN_PARTICIPANTS:
        raise InvalidSetup(f"参加者を{MIN_PARTICIPANTS}人以上選んでください")
    if minutes is not None and not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise InvalidSetup(f"制限時間は{MIN_MINUTES}〜{MAX_MINUTES}分で選んでください")
    checked = check_topic(topic or "") if topic_mode == "self" else None
    return Setup(chosen, topic_mode, checked, minutes)


@dataclass(frozen=True)
class Tally:
    """counts は参加者 → 得票（0 票の人も、参加者の並びで入れる）。"""

    counts: dict[int, int]
    villagers_win: bool


@dataclass(eq=False)
class InsiderRound:
    participants: tuple[int, ...]
    insider_id: int
    topic_mode: str
    minutes: int | None
    # 参加者 → 役職画像の URL。表示のたびに変わらないよう、配るときに 1 度だけ選ぶ
    images: dict[int, str] = field(default_factory=dict)
    topic: str | None = None
    phase: Phase = Phase.CHOOSING
    game_id: int | None = None
    deadline: float | None = None
    guesser: str | None = None
    votes: dict[int, int] = field(default_factory=dict)
    ending: Ending | None = None
    # 終わったときに全員へ見せる結果。hub が名前を入れて組み立てる
    result: dict[str, Any] | None = None

    def is_participant(self, player_id: int) -> bool:
        return player_id in self.participants

    def role_of(self, player_id: int) -> str | None:
        if not self.is_participant(player_id):
            return None
        return "insider" if player_id == self.insider_id else "villager"

    def begin(self, topic: str, game_id: int, now: float) -> None:
        """お題当てのゲームが始まった。制限時間はここから数える。"""
        self.topic = topic
        self.game_id = game_id
        self.phase = Phase.ASKING
        self.deadline = None if self.minutes is None else now + self.minutes * 60

    def remaining(self, now: float) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - now)

    def start_voting(self, guesser: str) -> None:
        self.phase = Phase.VOTING
        self.deadline = None
        self.guesser = guesser

    def vote(self, voter: int, target: int) -> str | None:
        """投票する。断るときは押した人に見せる文を返す。開票までは入れ直せる。"""
        if self.phase is not Phase.VOTING:
            return "いまは投票できません"
        if not self.is_participant(voter):
            return "参加者だけが投票できます"
        if voter == target:
            return "自分には投票できません"
        if not self.is_participant(target):
            return "参加者の中から選んでください"
        self.votes[voter] = target
        return None

    def all_voted(self) -> bool:
        return all(player_id in self.votes for player_id in self.participants)

    def tally(self) -> Tally:
        counts = {player_id: 0 for player_id in self.participants}
        for target in self.votes.values():
            counts[target] += 1
        top = max(counts.values())
        leaders = [player_id for player_id, count in counts.items() if count == top]
        # 最多票がインサイダー 1 人だけのときだけ村人の勝ち。同票はインサイダーが逃げ切る
        return Tally(counts, leaders == [self.insider_id] and top > 0)

    def finish(self, ending: Ending) -> None:
        self.phase = Phase.DONE
        self.ending = ending
        self.deadline = None


def deal(setup: Setup, rng: Rng) -> InsiderRound:
    """参加者の中からインサイダーを 1 人くじで選ぶ。"""
    insider = setup.participants[rng.randrange(len(setup.participants))]
    return InsiderRound(
        participants=setup.participants, insider_id=insider, topic_mode=setup.topic_mode, minutes=setup.minutes
    )
