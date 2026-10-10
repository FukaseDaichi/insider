"""Web 版の進行役。接続から届いた操作を検査して GameService に渡し、結果を接続の送信待ちの列に積む。

送信は列に積むだけで待たず、状態を変えてから積むまでの間に await を挟まない。
asyncio は 1 スレッドなので、こうすると状態を変えた順と画面に届く順が一致する。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from insider_bot import format as fmt
from insider_bot.game import Clock, GameManager
from insider_bot.service import GameService, Outcome
from insider_bot.village.illust import Illustrations
from insider_bot.web.insider import (
    ACTIVE_PHASES,
    InsiderRound,
    InvalidSetup,
    Phase,
    Rng,
    check_setup,
    check_topic,
    deal,
)
from insider_bot.web.rooms import Entry, Player, Room, RoomNotFound, RoomRegistry

log = logging.getLogger(__name__)

TOPIC_MAX = 50
HINT_MAX = 300
QUESTION_MAX = 200
# 音声認識が付けがちな句点や、手で打った「？」をいったん外してから「？」を付け直す
_TRAILING_MARKS = "。．.、？?"


class Connection(Protocol):
    def enqueue(self, message: dict[str, Any]) -> None: ...


def prepare_question(text: str) -> str:
    """押して話す・質問用の入力欄から来た文字を「？」で終わる質問にそろえる。中身がなければ空文字。"""
    text = text.strip().rstrip(_TRAILING_MARKS).rstrip()
    return f"{text}？" if text else ""


# Discord 用の「最後に「？」をつけてね」は、「？」を自動で付ける Web では声で「はてな」と言わせかねない。
# 出題者は質問者に紛れて遊ぶので、名前を出さない
WEB_STARTED = "🎮 お題が設定されました！\n質問どうぞ。"
# ゲーム開始の音声。同じ部屋や通話で遊んでも声が重ならないよう、サーバーが選んで全員に同じものを送る
START_SOUNDS = tuple(f"/static/sounds/start-{n}.m4a" for n in (1, 2, 3))
# 返事の声。はい % を 10 刻みの帯に分け、名前は帯の下限（yes-50 は 50〜59）。50 以上が「はい」で画面の ✅/❌ と揃える
ANSWER_SOUNDS = tuple(
    f"/static/sounds/{'yes' if band >= 50 else 'no'}-{band}.m4a" for band in range(0, 100, 10)
)
# ゲームの終わりの声。正解は言い当てた質問の返事の代わりに、ギブアップはお題の公開と一緒に鳴らす
CORRECT_SOUND = "/static/sounds/correct.m4a"
GIVEUP_SOUND = "/static/sounds/giveup.m4a"


# インサイダーゲームでは、お題当ての出題者は人ではなく AI の GM。参加者の ID（1 から）と重ならない番兵
GM_SETTER_ID = 0
GM_NAME = "GM"
# 先頭の 🎮 で画面が開始の案内（GM の吹き出し）と見分け、質問番号を数え直す
INSIDER_STARTED = "🎮 インサイダーゲーム開始！\n役職を確かめて、質問どうぞ。"
INSIDER_CHOOSING = "🕵️ インサイダーがお題を考えています…"
MODE_LABELS = {
    "random": "お題はランダム",
    "self": "お題は出した人が決めました",
    "insider": "お題はインサイダーが決めます",
}


def _default_role_image(role: str) -> str:
    return Illustrations("").default_url(role)


def answer_sound(yes_percent: int) -> str:
    band = min(max(yes_percent, 0), 99) // 10
    return ANSWER_SOUNDS[band]


class RoomHub:
    def __init__(
        self,
        registry: RoomRegistry,
        service: GameService,
        manager: GameManager,
        clock: Clock = time.monotonic,
        choose: Callable[[Sequence[str]], str] = random.choice,
        pick_topic: Callable[[], str | None] = lambda: None,
        role_image: Callable[[str], str] = _default_role_image,
        rng: Rng | None = None,
    ) -> None:
        self._registry = registry
        self._service = service
        self._manager = manager
        self._clock = clock
        self._choose = choose
        # ランダムのお題（配役ツールと同じ辞書）と役職画像。__main__ が配役ツールの中核から渡す
        self._pick_topic = pick_topic
        self._role_image = role_image
        self._rng: Rng = rng if rng is not None else random.Random()
        # 判定中のタスクが途中で回収されないよう、終わるまで参照を持つ
        self._tasks: set[asyncio.Task[None]] = set()

    def create_room(self) -> Room:
        return self._registry.create()

    def cleanup(self) -> None:
        self._registry.cleanup()

    def join(self, conn: Connection, code: str, name: str, token: str | None) -> tuple[Room, Player]:
        """接続の登録と snapshot の積み込みを待たずに行い、前後の更新を取りこぼさない。"""
        room = self._registry.get(code)
        if room is None:
            raise RoomNotFound(code)
        player = self._registry.join(room, token, name)
        self._registry.attach(room, conn, player)
        conn.enqueue({"type": "welcome", "token": player.token})
        conn.enqueue(
            {
                "type": "snapshot",
                "room": self._room_state(room, player),
                "log": [entry.to_message() for entry in room.log],
            }
        )
        self._broadcast_room(room, skip=conn)
        return room, player

    def leave(self, room: Room, conn: Connection) -> None:
        self._registry.detach(room, conn)
        self._broadcast_room(room)

    async def start(self, room: Room, player: Player, topic: str, hint: str) -> None:
        topic, hint = topic.strip(), hint.strip()
        if not 1 <= len(topic) <= TOPIC_MAX:
            self._notify(room, player, f"お題は1〜{TOPIC_MAX}文字で入力してください")
            return
        if len(hint) > HINT_MAX:
            self._notify(room, player, f"補足は{HINT_MAX}文字までです")
            return
        if self._busy(room):
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        outcome = await self._service.start(room.room_id, player.player_id, player.name, topic, hint)
        if outcome.public is not None:
            # 前のインサイダーゲームの役職のカードは、次のゲームが始まるまでしか出さない
            room.insider = None
            outcome = Outcome(private=outcome.private, public=WEB_STARTED)
            # 状態ではなくその場かぎりの合図。再接続や途中参加の snapshot では鳴らさない
            self._broadcast(room, {"type": "sound", "src": self._choose(START_SOUNDS)})
        self._apply(room, player, outcome, author=None)

    def _busy(self, room: Room) -> bool:
        """お題当てのゲームが進行中か、インサイダーゲームがお題待ち・質問・投票のどれか。"""
        if self._manager.get(room.room_id) is not None:
            return True
        return room.insider is not None and room.insider.phase in ACTIVE_PHASES

    def _name_of(self, room: Room, player_id: int) -> str:
        for candidate in room.players.values():
            if candidate.player_id == player_id:
                return candidate.name
        return "?"

    async def insider_start(
        self,
        room: Room,
        player: Player,
        participants: list[int],
        topic_mode: str,
        topic: str | None,
        minutes: int | None,
    ) -> None:
        if self._busy(room):
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        try:
            setup = check_setup(
                [p.player_id for p in room.players.values()], player.player_id, participants, topic_mode, topic, minutes
            )
        except InvalidSetup as error:
            self._notify(room, player, str(error))
            return
        chosen = setup.topic
        if setup.topic_mode == "random":
            chosen = self._pick_topic()
            if chosen is None:
                self._notify(room, player, "お題の辞書が使えないため、ランダムでは始められません")
                return
        insider = deal(setup, self._rng)
        insider.images = {
            player_id: self._role_image("INSIDER" if player_id == insider.insider_id else "VILLAGERS")
            for player_id in insider.participants
        }
        # 次の await より前に置く。始まるまでの間に届いた別の開始は _busy で断られる
        room.insider = insider
        names = "・".join(self._name_of(room, player_id) for player_id in insider.participants)
        self._broadcast_entry(
            room, room.add_entry(None, f"🕵️ インサイダーゲーム　参加者: {names}（{MODE_LABELS[setup.topic_mode]}）")
        )
        if chosen is None:
            self._broadcast_entry(room, room.add_entry(None, INSIDER_CHOOSING))
            self._broadcast_room(room)
            return
        await self._begin_insider(room, insider, chosen)

    async def insider_topic(self, room: Room, player: Player, topic: str) -> None:
        insider = room.insider
        # お題を先に置いてから await する。連打や再送で 2 回届いても、ゲームは 1 回だけ始まる
        if (
            insider is None
            or insider.phase is not Phase.CHOOSING
            or insider.insider_id != player.player_id
            or insider.topic is not None
        ):
            self._notify(room, player, "いまはお題を決められません")
            return
        try:
            insider.topic = check_topic(topic)
        except InvalidSetup as error:
            self._notify(room, player, str(error))
            return
        await self._begin_insider(room, insider, insider.topic)

    async def _begin_insider(self, room: Room, insider: InsiderRound, topic: str) -> None:
        """お題当てのゲームを AI の GM で始める。参加者は全員（インサイダーも）質問する。"""
        outcome = await self._service.start(room.room_id, GM_SETTER_ID, GM_NAME, topic, "")
        game = self._manager.get(room.room_id)
        if outcome.public is None or game is None or room.insider is not insider:
            # _busy で防いでいるので起きないはず。起きたらこの回を捨て、画面を戻す
            log.warning("インサイダーゲームを始められませんでした（room=%s）", room.code)
            if room.insider is insider:
                room.insider = None
            self._broadcast_room(room)
            return
        insider.begin(topic, game.game_id, self._clock())
        self._broadcast(room, {"type": "sound", "src": self._choose(START_SOUNDS)})
        self._broadcast_entry(room, room.add_entry(None, INSIDER_STARTED))
        self._broadcast_room(room)

    async def giveup(self, room: Room, player: Player) -> None:
        outcome = await self._service.giveup(room.room_id)
        if outcome.public is not None:
            self._broadcast(room, {"type": "sound", "src": GIVEUP_SOUND})
        self._apply(room, player, outcome, author=player.name)

    def ask(self, room: Room, player: Player, text: str, game_id: object) -> asyncio.Task[None]:
        """判定は接続の受信ループから切り離して動かす。質問者のタブが閉じても結果は履歴に残る。"""
        task = asyncio.create_task(self._ask(room, player, text, game_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _ask(self, room: Room, player: Player, text: str, game_id: object) -> None:
        # handle_question が対象のゲームを控えるまで await を挟まない。確かめたゲームと判定するゲームを一致させるため
        if len(text.strip()) > QUESTION_MAX:
            self._notify(room, player, f"質問は{QUESTION_MAX}文字までです")
            return
        question = prepare_question(text)
        if not question:
            self._notify(room, player, "質問を入力してください")
            return
        game = self._manager.get(room.room_id)
        if game is None:
            self._notify(room, player, fmt.format_no_game())
            return
        if game_id != game.game_id:
            # 押している間に次のゲームが始まっていた。前のゲームへの質問を新しいお題で判定しない
            self._notify(room, player, "ゲームが変わったため、その質問は送りませんでした")
            return
        entry = room.add_entry(player.name, f"❓ {question}\n… 判定中", pending=True)
        self._broadcast_entry(room, entry)
        try:
            outcome = await self._service.handle_question(
                room.room_id, player.player_id, player.name, question, setter_can_ask=True
            )
        except Exception:
            log.exception("質問の処理に失敗しました（room=%s）", room.code)
            outcome = Outcome(public=fmt.format_error())
        entry.pending = False
        # 開始の音声と同じく、その場かぎりの合図。全員が同じ声を聞く
        if outcome.yes_percent is not None:
            self._broadcast(room, {"type": "sound", "src": answer_sound(outcome.yes_percent)})
        elif outcome.is_correct:
            self._broadcast(room, {"type": "sound", "src": CORRECT_SOUND})
        if outcome.public is not None:
            entry.text = outcome.public
        else:
            # 判定の順番待ちの間に、先の質問の正解やギブアップでゲームが終わった
            entry.text = f"❓ {question}\n— ゲームが終わったため取り消しました"
        self._broadcast_entry(room, entry)
        self._broadcast_room(room)

    def _apply(self, room: Room, player: Player, outcome: Outcome, author: str | None) -> None:
        if outcome.private is not None:
            self._notify(room, player, outcome.private)
        if outcome.public is not None:
            self._broadcast_entry(room, room.add_entry(author, outcome.public))
        self._broadcast_room(room)

    def _room_state(self, room: Room, player: Player) -> dict[str, Any]:
        game = self._manager.get(room.room_id)
        header = None
        you: dict[str, Any] = {"id": player.player_id, "is_setter": False}
        if game is not None:
            header = {
                "id": game.game_id,
                "questions": game.question_count,
                "elapsed": round(self._clock() - game.started_at, 1),
            }
            if game.setter_id == player.player_id:
                # お題と補足は出題者の接続にだけ入れる。誰が出題者かはほかの接続に送らない
                you = {"id": player.player_id, "is_setter": True, "topic": game.topic, "hint": game.hint}
        # 名前は重なりうるので、画面は参加者を ID で選ぶ（連番で、秘密ではない）
        players = [
            {"id": p.player_id, "name": p.name, "online": room.is_online(p)} for p in room.players.values()
        ]
        return {"players": players, "game": header, "you": you, "insider": self._insider_state(room, player)}

    def _insider_state(self, room: Room, player: Player) -> dict[str, Any] | None:
        insider = room.insider
        if insider is None:
            return None
        role = insider.role_of(player.player_id)
        # 役職・お題・自分の票は、その人の接続にだけ入れる。ほかの接続には誰がインサイダーかを送らない
        you = {
            "role": role,
            "topic": insider.topic if role == "insider" else None,
            "image": insider.images.get(player.player_id),
            "vote": insider.votes.get(player.player_id),
        }
        return {
            "phase": insider.phase.value,
            "participants": list(insider.participants),
            "topic_mode": insider.topic_mode,
            "remaining": insider.remaining(self._clock()),
            "voted": [player_id for player_id in insider.participants if player_id in insider.votes],
            "you": you,
            "result": insider.result,
        }

    def _broadcast_room(self, room: Room, skip: Connection | None = None) -> None:
        for conn, player in list(room.connections.items()):
            if conn is not skip:
                conn.enqueue({"type": "room", **self._room_state(room, player)})

    def _broadcast_entry(self, room: Room, entry: Entry) -> None:
        self._broadcast(room, {"type": "entry", "entry": entry.to_message()})

    def _broadcast(self, room: Room, message: dict[str, Any]) -> None:
        for conn in list(room.connections):
            conn.enqueue(message)

    def _notify(self, room: Room, player: Player, text: str) -> None:
        for conn, owner in list(room.connections.items()):
            if owner is player:
                conn.enqueue({"type": "notice", "text": text})
