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
WEB_STARTED = "🎮 ゲーム開始！\nお題が出されました！\n「🎙 押して話す」で質問をどうぞ！"
# ゲーム開始の音声。同じ部屋や通話で遊んでも声が重ならないよう、サーバーが選んで全員に同じものを送る
START_SOUNDS = tuple(f"/static/sounds/start-{n}.m4a" for n in (1, 2, 3))


class RoomHub:
    def __init__(
        self,
        registry: RoomRegistry,
        service: GameService,
        manager: GameManager,
        clock: Clock = time.monotonic,
        choose: Callable[[Sequence[str]], str] = random.choice,
    ) -> None:
        self._registry = registry
        self._service = service
        self._manager = manager
        self._clock = clock
        self._choose = choose
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
        if self._manager.get(room.room_id) is not None:
            self._notify(room, player, "このルームではゲームが進行中です")
            return
        outcome = await self._service.start(room.room_id, player.player_id, player.name, topic, hint)
        if outcome.public is not None:
            outcome = Outcome(private=outcome.private, public=WEB_STARTED)
            # 状態ではなくその場かぎりの合図。再接続や途中参加の snapshot では鳴らさない
            self._broadcast(room, {"type": "sound", "src": self._choose(START_SOUNDS)})
        self._apply(room, player, outcome, author=None)

    async def giveup(self, room: Room, player: Player) -> None:
        outcome = await self._service.giveup(room.room_id)
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
        you: dict[str, Any] = {"is_setter": False}
        if game is not None:
            header = {
                "id": game.game_id,
                "questions": game.question_count,
                "elapsed": round(self._clock() - game.started_at, 1),
            }
            if game.setter_id == player.player_id:
                # お題と補足は出題者の接続にだけ入れる。誰が出題者かはほかの接続に送らない
                you = {"is_setter": True, "topic": game.topic, "hint": game.hint}
        players = [{"name": p.name, "online": room.is_online(p)} for p in room.players.values()]
        return {"players": players, "game": header, "you": you}

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
