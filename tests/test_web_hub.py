import asyncio
import json

import pytest

from insider_bot.game import GameManager
from insider_bot.judge import JudgeError, Verdict
from insider_bot.service import GameService
from insider_bot.web.hub import (
    ANSWER_SOUNDS,
    CORRECT_SOUND,
    GIVEUP_SOUND,
    INSIDER_STARTED,
    INSIDER_VOTING,
    START_SOUNDS,
    RoomHub,
    answer_sound,
    prepare_question,
)
from insider_bot.web.rooms import InvalidName, RoomNotFound, RoomRegistry
from insider_bot.web.server import STATIC_DIR
from tests.fakes import FakeClock, FakeJudge, FixedRandom

CORRECT = Verdict(1.0, True, "exact")
PENDING = "❓ 果物ですか？\n… 判定中"
ANSWER = "❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%"
STARTED = "🎮 お題が設定されました！\n質問どうぞ。"


class FakeConnection:
    """積まれたメッセージを記録する接続。"""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def enqueue(self, message: dict) -> None:
        self.messages.append(message)

    def of(self, kind: str) -> list[dict]:
        return [message for message in self.messages if message["type"] == kind]

    def entries(self) -> list[dict]:
        return [message["entry"] for message in self.of("entry")]

    def notices(self) -> list[str]:
        return [message["text"] for message in self.of("notice")]

    def last_room(self) -> dict:
        return self.of("room")[-1]


class World:
    def __init__(self, judge: FakeJudge | None = None, choose=None, topic: str | None = "すいか", rng=None) -> None:
        self.clock = FakeClock()
        self.judge = judge or FakeJudge()
        self.manager = GameManager(clock=self.clock)
        service = GameService(self.manager, self.judge, clock=self.clock)
        registry = RoomRegistry(clock=self.clock, on_remove=lambda room: self.manager.end(room.room_id))
        options = {} if choose is None else {"choose": choose}
        self.hub = RoomHub(
            registry,
            service,
            self.manager,
            clock=self.clock,
            pick_topic=lambda: topic,
            role_image=lambda role: f"/static/roles/{role}.png",
            rng=rng or FixedRandom(*([0] * 20)),
            **options,
        )
        self.room = self.hub.create_room()

    def join(self, name: str, token: str | None = None):
        conn = FakeConnection()
        _, player = self.hub.join(conn, self.room.code, name, token)
        return conn, player

    def game_id(self) -> int:
        return self.manager.get(self.room.room_id).game_id


async def playing(judge: FakeJudge | None = None):
    """出題者「たろう」がお題「りんご」（補足「赤い果物」）で始め、回答者「はなこ」がいる状態。"""
    world = World(judge)
    setter = world.join("たろう")
    asker = world.join("はなこ")
    await world.hub.start(world.room, setter[1], "りんご", "赤い果物")
    return world, setter, asker


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- 質問文の整形 ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("果物ですか", "果物ですか？"),
        (" 果物ですか。 ", "果物ですか？"),
        ("りんご?", "りんご？"),
        ("赤い？", "赤い？"),
        ("。", ""),
        ("？", ""),
        ("   ", ""),
    ],
)
def test_prepare_question(text, expected):
    assert prepare_question(text) == expected


# --- 入室・退室 ---


def test_join_enqueues_welcome_then_snapshot():
    world = World()
    conn, player = world.join("はなこ")
    assert conn.messages == [
        {"type": "welcome", "token": player.token},
        {
            "type": "snapshot",
            "room": {
                "players": [{"id": player.player_id, "name": "はなこ", "online": True}],
                "game": None,
                "you": {"id": player.player_id, "is_setter": False},
                "insider": None,
            },
            "log": [],
        },
    ]


def test_join_unknown_room_raises():
    world = World()
    with pytest.raises(RoomNotFound):
        world.hub.join(FakeConnection(), "ZZZZZZ", "はなこ", None)


def test_join_with_invalid_name_raises():
    with pytest.raises(InvalidName):
        World().join("")


def test_others_see_arrival_and_departure():
    world = World()
    first, taro = world.join("たろう")
    second, hanako = world.join("はなこ")
    assert first.last_room()["players"] == [
        {"id": taro.player_id, "name": "たろう", "online": True},
        {"id": hanako.player_id, "name": "はなこ", "online": True},
    ]
    assert second.of("room") == []
    world.hub.leave(world.room, second)
    assert first.last_room()["players"][1] == {"id": hanako.player_id, "name": "はなこ", "online": False}


def test_closing_one_of_two_tabs_keeps_player_online():
    world = World()
    observer, _ = world.join("たろう")
    tab1, player = world.join("はなこ")
    world.join("はなこ", player.token)
    world.hub.leave(world.room, tab1)
    assert observer.last_room()["players"][1] == {"id": player.player_id, "name": "はなこ", "online": True}


# --- お題を出す ---


async def test_start_notifies_setter_and_announces_to_everyone():
    world, (setter_conn, _), (asker_conn, _) = await playing()
    assert setter_conn.notices() == ["お題『りんご』を登録しました"]
    assert asker_conn.notices() == []
    for conn in (setter_conn, asker_conn):
        assert conn.entries() == [{"id": 1, "author": None, "text": STARTED, "pending": False}]
        assert conn.messages[-1]["type"] == "room"


async def test_topic_reaches_only_the_setter():
    world, (setter_conn, setter), (asker_conn, _) = await playing()
    late_conn, _ = world.join("じろう")
    assert setter_conn.last_room()["you"] == {
        "id": setter.player_id,
        "is_setter": True,
        "topic": "りんご",
        "hint": "赤い果物",
    }
    for conn in (asker_conn, late_conn):
        dumped = json.dumps(conn.messages, ensure_ascii=False)
        assert "りんご" not in dumped
        assert "赤い果物" not in dumped
    again_conn, _ = world.join("たろう", setter.token)
    assert again_conn.of("snapshot")[0]["room"]["you"] == {
        "id": setter.player_id,
        "is_setter": True,
        "topic": "りんご",
        "hint": "赤い果物",
    }


async def test_header_shows_question_count_and_elapsed_but_not_setter():
    world, _, (asker_conn, asker) = await playing()
    world.clock.advance(30)
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert asker_conn.last_room()["game"] == {"id": 1, "questions": 1, "elapsed": 30.0}



async def test_start_plays_the_same_sound_for_everyone():
    world = World(choose=lambda sounds: sounds[1])
    setter_conn, setter = world.join("たろう")
    asker_conn, _ = world.join("はなこ")
    await world.hub.start(world.room, setter, "りんご", "")
    for conn in (setter_conn, asker_conn):
        assert conn.of("sound") == [{"type": "sound", "src": "/static/sounds/start-2.m4a"}]


async def test_start_sound_is_not_replayed_on_join():
    world, _, _ = await playing()
    late_conn, _ = world.join("じろう")
    assert late_conn.of("sound") == []


def test_start_sounds_are_served():
    assert len(START_SOUNDS) == 3
    for src in START_SOUNDS:
        assert (STATIC_DIR / src.removeprefix("/static/")).is_file()

# --- 返事の声 ---


@pytest.mark.parametrize(
    ("yes", "src"),
    [
        (100, "/static/sounds/yes-90.m4a"),
        (90, "/static/sounds/yes-90.m4a"),
        (89, "/static/sounds/yes-80.m4a"),
        (50, "/static/sounds/yes-50.m4a"),
        (49, "/static/sounds/no-40.m4a"),
        (10, "/static/sounds/no-10.m4a"),
        (9, "/static/sounds/no-0.m4a"),
        (0, "/static/sounds/no-0.m4a"),
    ],
)
def test_answer_sound_is_chosen_by_ten_percent_band(yes, src):
    assert answer_sound(yes) == src


def test_answer_sounds_are_served():
    assert len(ANSWER_SOUNDS) == 10
    for src in ANSWER_SOUNDS:
        assert (STATIC_DIR / src.removeprefix("/static/")).is_file()


async def test_answer_plays_the_band_sound_for_everyone():
    world, (setter_conn, _), (asker_conn, asker) = await playing()
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    for conn in (setter_conn, asker_conn):
        # 開始の音声の次に、返事の声が届く
        assert conn.of("sound")[1:] == [{"type": "sound", "src": "/static/sounds/yes-80.m4a"}]


async def test_correct_answer_plays_the_correct_sound_for_everyone():
    world, (setter_conn, _), (asker_conn, asker) = await playing(FakeJudge(answers={"りんご？": CORRECT}))
    await world.hub.ask(world.room, asker, "りんご", world.game_id())
    for conn in (setter_conn, asker_conn):
        # 返事の声は鳴らさず、正解の声だけ
        assert conn.of("sound")[1:] == [{"type": "sound", "src": "/static/sounds/correct.m4a"}]


def test_end_sounds_are_served():
    for src in (CORRECT_SOUND, GIVEUP_SOUND):
        assert (STATIC_DIR / src.removeprefix("/static/")).is_file()


async def test_judge_error_plays_no_sound():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(error=JudgeError("timeout")))
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert setter_conn.of("sound")[1:] == []


@pytest.mark.parametrize(
    ("topic", "hint", "notice"),
    [
        ("　", "", "お題は1〜50文字で入力してください"),
        ("あ" * 51, "", "お題は1〜50文字で入力してください"),
        ("りんご", "あ" * 301, "補足は300文字までです"),
    ],
)
async def test_start_rejects_invalid_lengths(topic, hint, notice):
    world = World()
    conn, player = world.join("たろう")
    await world.hub.start(world.room, player, topic, hint)
    assert conn.notices() == [notice]
    assert world.manager.get(world.room.room_id) is None
    assert conn.of("sound") == []


async def test_near_simultaneous_starts_keep_the_first():
    world = World()
    _, first = world.join("たろう")
    second_conn, second = world.join("はなこ")
    await asyncio.gather(
        world.hub.start(world.room, first, "りんご", ""),
        world.hub.start(world.room, second, "みかん", ""),
    )
    assert world.manager.get(world.room.room_id).topic == "りんご"
    assert second_conn.notices() == ["このルームではゲームが進行中です"]
    assert len(second_conn.of("sound")) == 1


# --- 質問 ---


async def test_question_shows_pending_then_answer_in_order():
    gate = asyncio.Event()
    world, (setter_conn, _), (asker_conn, asker) = await playing(FakeJudge(gate=gate))
    task = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    assert setter_conn.entries()[-1] == {"id": 2, "author": "はなこ", "text": PENDING, "pending": True}
    gate.set()
    await task
    for conn in (setter_conn, asker_conn):
        assert conn.entries()[-2:] == [
            {"id": 2, "author": "はなこ", "text": PENDING, "pending": True},
            {"id": 2, "author": "はなこ", "text": ANSWER, "pending": False},
        ]
        assert conn.messages[-1]["type"] == "room"
    assert world.judge.calls == [("りんご", "赤い果物", "果物ですか？")]


@pytest.mark.parametrize(
    ("text", "notice"),
    [
        ("。", "質問を入力してください"),
        ("？", "質問を入力してください"),
        ("あ" * 201, "質問は200文字までです"),
    ],
)
async def test_question_rejected_before_judging(text, notice):
    world, _, (asker_conn, asker) = await playing()
    await world.hub.ask(world.room, asker, text, world.game_id())
    assert asker_conn.notices() == [notice]
    assert world.judge.calls == []


async def test_question_without_game_is_rejected():
    world = World()
    conn, player = world.join("はなこ")
    await world.hub.ask(world.room, player, "果物ですか", None)
    assert conn.notices() == ["進行中のゲームはありません"]
    assert conn.entries() == []


async def test_setter_can_ask_like_everyone():
    world, (_, setter), (asker_conn, _) = await playing()
    await world.hub.ask(world.room, setter, "果物ですか", world.game_id())
    assert asker_conn.entries()[-1] == {"id": 2, "author": "たろう", "text": ANSWER, "pending": False}
    assert asker_conn.last_room()["game"]["questions"] == 1


async def test_setter_can_answer_correctly():
    world, (_, setter), (asker_conn, _) = await playing(FakeJudge(answers={"りんご？": CORRECT}))
    await world.hub.ask(world.room, setter, "りんご", world.game_id())
    assert asker_conn.entries()[-1]["text"] == (
        "🎉 正解です！お題は「りんご」でした\n正解者: たろう　質問数: 1　経過時間: 0秒"
    )
    assert asker_conn.last_room()["game"] is None


async def test_question_for_previous_game_is_rejected():
    world, (_, setter), (asker_conn, asker) = await playing()
    previous = world.game_id()
    await world.hub.giveup(world.room, setter)
    await world.hub.start(world.room, setter, "みかん", "")
    await world.hub.ask(world.room, asker, "果物ですか", previous)
    assert asker_conn.notices() == ["ゲームが変わったため、その質問は送りませんでした"]
    assert world.judge.calls == []


async def test_correct_answer_ends_game():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(answers={"りんご？": CORRECT}))
    await world.hub.ask(world.room, asker, "りんご", world.game_id())
    assert setter_conn.entries()[-1]["text"] == (
        "🎉 正解です！お題は「りんご」でした\n正解者: はなこ　質問数: 1　経過時間: 0秒"
    )
    assert setter_conn.last_room()["game"] is None
    assert world.manager.get(world.room.room_id) is None


async def test_queued_question_is_cancelled_when_earlier_one_is_correct():
    gate = asyncio.Event()
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(default=CORRECT, gate=gate))
    first = world.hub.ask(world.room, asker, "りんご", world.game_id())
    await wait_until(lambda: world.judge.calls)
    second = world.hub.ask(world.room, asker, "みかん", world.game_id())
    await wait_until(lambda: sum(entry["pending"] for entry in setter_conn.entries()) == 2)
    gate.set()
    await asyncio.gather(first, second)
    finished = [entry["text"] for entry in setter_conn.entries() if not entry["pending"]]
    assert finished[-2].startswith("🎉 正解です！")
    assert finished[-1] == "❓ みかん？\n— ゲームが終わったため取り消しました"


async def test_giveup_during_judging_comes_after_the_answer():
    gate = asyncio.Event()
    world, (setter_conn, setter), (_, asker) = await playing(FakeJudge(gate=gate))
    question = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    giveup = asyncio.create_task(world.hub.giveup(world.room, setter))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(question, giveup)
    finished = [entry["text"] for entry in setter_conn.entries() if not entry["pending"]]
    assert finished[-2:] == [ANSWER, "🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）"]


async def test_judge_failure_replaces_pending_with_error():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(error=JudgeError("timeout")))
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert setter_conn.entries()[-1] == {
        "id": 2,
        "author": "はなこ",
        "text": "⚠️ 判定できませんでした。もう一度どうぞ",
        "pending": False,
    }


async def test_unexpected_error_does_not_leave_pending_entry():
    world, (setter_conn, _), (_, asker) = await playing(FakeJudge(error=RuntimeError("想定外")))
    await world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    assert setter_conn.entries()[-1]["text"] == "⚠️ 判定できませんでした。もう一度どうぞ"
    assert setter_conn.entries()[-1]["pending"] is False


async def test_result_is_kept_when_asker_leaves_during_judging():
    gate = asyncio.Event()
    world, (setter_conn, _), (asker_conn, asker) = await playing(FakeJudge(gate=gate))
    task = world.hub.ask(world.room, asker, "果物ですか", world.game_id())
    await wait_until(lambda: world.judge.calls)
    world.hub.leave(world.room, asker_conn)
    sent_before = len(asker_conn.messages)
    gate.set()
    await task
    assert setter_conn.entries()[-1]["text"] == ANSWER
    assert world.room.log[-1].text == ANSWER
    assert len(asker_conn.messages) == sent_before


# --- ギブアップ・通知 ---


async def test_answerer_can_give_up():
    world, (setter_conn, _), (_, asker) = await playing()
    await world.hub.giveup(world.room, asker)
    assert setter_conn.entries()[-1] == {
        "id": 2,
        "author": "はなこ",
        "text": "🏳️ ギブアップ！お題は『りんご』でした（質問数: 0）",
        "pending": False,
    }
    assert setter_conn.last_room()["game"] is None


async def test_giveup_plays_the_giveup_sound_for_everyone():
    world, (setter_conn, _), (asker_conn, asker) = await playing()
    await world.hub.giveup(world.room, asker)
    for conn in (setter_conn, asker_conn):
        assert conn.of("sound")[1:] == [{"type": "sound", "src": "/static/sounds/giveup.m4a"}]


async def test_giveup_without_game_notifies_only_that_player():
    world = World()
    conn, player = world.join("はなこ")
    other, _ = world.join("じろう")
    await world.hub.giveup(world.room, player)
    assert conn.notices() == ["進行中のゲームはありません"]
    assert other.notices() == []
    assert conn.entries() == []
    assert conn.of("sound") == []


async def test_notice_reaches_every_tab_of_that_player_only():
    world = World()
    tab1, setter = world.join("たろう")
    tab2, _ = world.join("たろう", setter.token)
    other, _ = world.join("はなこ")
    await world.hub.start(world.room, setter, "りんご", "")
    assert tab1.notices() == tab2.notices() == ["お題『りんご』を登録しました"]
    assert other.notices() == []


# --- インサイダーゲーム: 配って始める ---


def trio(world: World):
    """たろう・はなこ・じろう の 3 人と、見るだけの さぶろう。"""
    return [world.join(name) for name in ("たろう", "はなこ", "じろう", "さぶろう")]


async def test_insider_random_start_deals_roles_and_starts_game():
    world = World(rng=FixedRandom(1))  # 2 番目（はなこ）がインサイダー
    (t, tp), (h, hp), (j, jp), (s, sp) = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    game = world.manager.get(world.room.room_id)
    assert game.topic == "すいか"
    assert world.judge.calls == []
    insider = h.last_room()["insider"]
    assert insider["phase"] == "asking"
    assert insider["participants"] == [tp.player_id, hp.player_id, jp.player_id]
    assert insider["you"] == {"role": "insider", "topic": "すいか", "image": "/static/roles/INSIDER.png", "vote": None}
    assert t.last_room()["insider"]["you"] == {
        "role": "villager",
        "topic": None,
        "image": "/static/roles/VILLAGERS.png",
        "vote": None,
    }
    assert s.last_room()["insider"]["you"] == {"role": None, "topic": None, "image": None, "vote": None}
    texts = [entry["text"] for entry in t.entries()]
    assert texts[-1] == INSIDER_STARTED
    assert "たろう・はなこ・じろう" in texts[-2]
    assert "すいか" not in "".join(texts)
    assert t.of("sound")


async def test_insider_role_is_kept_only_in_own_snapshot():
    world = World(rng=FixedRandom(0))
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    again, _ = world.join("たろう", tp.token)
    snapshot = again.of("snapshot")[0]["room"]
    assert snapshot["insider"]["you"]["role"] == "insider"
    assert snapshot["insider"]["you"]["topic"] == "すいか"
    # ほかの人の接続には、誰がインサイダーかもお題も入らない
    for conn in (h, j):
        dumped = json.dumps(conn.messages, ensure_ascii=False)
        assert "すいか" not in dumped
        assert "INSIDER.png" not in dumped


async def test_insider_self_topic_excludes_starter():
    world = World()
    (t, tp), (h, hp), (j, jp), (s, sp) = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "self", "ぶどう", None)
    assert t.notices()[-1] == "お題を決める人は参加者になれません"
    assert world.room.insider is None
    await world.hub.insider_start(world.room, tp, [hp.player_id, jp.player_id, sp.player_id], "self", "ぶどう", 3)
    assert world.manager.get(world.room.room_id).topic == "ぶどう"
    assert t.last_room()["insider"]["you"]["role"] is None
    assert t.last_room()["insider"]["remaining"] == 180.0


async def test_insider_start_rejects_invalid_setup_and_busy_room():
    world = World()
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id], "random", None, None)
    assert t.notices()[-1] == "参加者を3人以上選んでください"
    await world.hub.start(world.room, tp, "りんご", "")
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    assert t.notices()[-1] == "このルームではゲームが進行中です"


async def test_insider_random_start_needs_dictionary():
    world = World(topic=None)
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "random", None, None)
    assert t.notices()[-1] == "お題の辞書が使えないため、ランダムでは始められません"
    assert world.room.insider is None


async def test_players_with_the_same_name_are_told_apart_by_id():
    world = World(rng=FixedRandom(2))
    (t, tp), (h, hp) = world.join("たろう"), world.join("はなこ")
    (t2, t2p) = world.join("たろう")
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, t2p.player_id], "random", None, None)
    assert t2.last_room()["insider"]["you"]["role"] == "insider"
    assert t.last_room()["insider"]["you"]["role"] == "villager"


async def test_insider_chooses_topic_then_game_starts():
    world = World(rng=FixedRandom(2))  # じろう がインサイダー
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, tp, [tp.player_id, hp.player_id, jp.player_id], "insider", None, 5)
    assert world.manager.get(world.room.room_id) is None
    assert t.last_room()["insider"]["phase"] == "choosing"
    assert t.entries()[-1]["text"] == "🕵️ インサイダーがお題を考えています…"
    assert j.last_room()["insider"]["you"]["topic"] is None
    await world.hub.insider_topic(world.room, tp, "もも")
    assert t.notices()[-1] == "いまはお題を決められません"
    await world.hub.insider_topic(world.room, jp, "  ")
    assert j.notices()[-1] == "お題は1〜50文字で入力してください"
    world.clock.advance(30)
    await world.hub.insider_topic(world.room, jp, "もも")
    assert world.manager.get(world.room.room_id).topic == "もも"
    assert j.last_room()["insider"]["you"]["topic"] == "もも"
    # 制限時間はお題が決まった時点から数える
    assert j.last_room()["insider"]["remaining"] == 300.0


async def test_insider_topic_twice_starts_only_one_game():
    world = World(rng=FixedRandom(0))
    (t, tp), (h, hp), (j, jp), _ = trio(world)
    await world.hub.insider_start(world.room, hp, [tp.player_id, hp.player_id, jp.player_id], "insider", None, None)
    await asyncio.gather(
        world.hub.insider_topic(world.room, tp, "もも"),
        world.hub.insider_topic(world.room, tp, "なし"),
    )
    assert world.manager.get(world.room.room_id).topic == "もも"
    assert t.notices()[-1] == "いまはお題を決められません"
    assert [e["text"] for e in t.entries()].count(INSIDER_STARTED) == 1


CORRECT_SUIKA = FakeJudge(answers={"すいかですか？": CORRECT})


async def insider_playing(rng_index: int = 0):
    """たろう・はなこ・じろう が参加者（rng_index 番目がインサイダー）、さぶろう は見るだけ。お題は すいか。"""
    world = World(judge=FakeJudge(answers={"すいかですか？": CORRECT}), rng=FixedRandom(rng_index))
    people = trio(world)
    ids = [p.player_id for _, p in people[:3]]
    await world.hub.insider_start(world.room, people[0][1], ids, "random", None, 5)
    return world, people


async def test_spectator_cannot_ask():
    world, people = await insider_playing()
    s, sp = people[3]
    await world.hub.ask(world.room, sp, "果物ですか", world.game_id())
    assert s.notices()[-1] == "インサイダーゲームの参加者だけが質問できます"
    assert world.judge.calls == []


async def test_correct_guess_opens_voting_then_all_votes_close_it():
    world, people = await insider_playing(rng_index=0)  # たろう がインサイダー
    (t, tp), (h, hp), (j, jp), (s, sp) = people
    await world.hub.ask(world.room, hp, "すいかですか", world.game_id())
    insider = t.last_room()["insider"]
    assert insider["phase"] == "voting"
    assert insider["remaining"] is None
    assert t.entries()[-1]["text"] == INSIDER_VOTING
    world.hub.vote(world.room, sp, tp.player_id)
    assert s.notices()[-1] == "参加者だけが投票できます"
    world.hub.vote(world.room, hp, tp.player_id)
    world.hub.vote(world.room, jp, hp.player_id)
    world.hub.vote(world.room, jp, tp.player_id)  # 入れ直し
    assert t.last_room()["insider"]["voted"] == [hp.player_id, jp.player_id]
    # 誰が誰に入れたかは、本人の接続以外に送らない
    assert t.last_room()["insider"]["you"]["vote"] is None
    assert j.last_room()["insider"]["you"]["vote"] == tp.player_id
    world.hub.vote(world.room, tp, hp.player_id)
    result = t.entries()[-1]
    assert result["kind"] == "insider_result"
    assert result["data"] == {
        "ending": "voted",
        "topic": "すいか",
        "insider": "たろう",
        "insider_id": tp.player_id,
        "guesser": "はなこ",
        "winner": "villagers",
        "votes": [
            {"id": tp.player_id, "name": "たろう", "count": 2},
            {"id": hp.player_id, "name": "はなこ", "count": 1},
            {"id": jp.player_id, "name": "じろう", "count": 0},
        ],
    }
    assert "村人の勝ち" in result["text"]
    assert t.last_room()["insider"]["phase"] == "done"
    assert s.last_room()["insider"]["result"] == result["data"]


async def test_close_vote_by_participant_with_tie_lets_insider_win():
    world, people = await insider_playing(rng_index=0)
    (t, tp), (h, hp), (j, jp), (s, sp) = people
    await world.hub.ask(world.room, hp, "すいかですか", world.game_id())
    world.hub.close_vote(world.room, hp)
    assert h.notices()[-1] == "まだ誰も投票していません"
    world.hub.vote(world.room, hp, tp.player_id)
    world.hub.vote(world.room, tp, jp.player_id)
    world.hub.close_vote(world.room, sp)
    assert s.notices()[-1] == "参加者だけが開票できます"
    world.hub.close_vote(world.room, jp)
    data = t.entries()[-1]["data"]
    assert data["winner"] == "insider"
    assert "インサイダーの勝ち" in t.entries()[-1]["text"]
