import pytest

from insider_bot.web.rooms import (
    CODE_ALPHABET,
    CODE_LENGTH,
    InvalidName,
    RoomFull,
    RoomLimitReached,
    RoomRegistry,
)
from tests.fakes import FakeClock


def make(**limits):
    clock = FakeClock()
    removed = []
    registry = RoomRegistry(clock=clock, on_remove=removed.append, **limits)
    return registry, clock, removed


# --- 作成 ---


def test_create_gives_unique_codes_and_ids():
    registry, _, _ = make()
    rooms = [registry.create() for _ in range(20)]
    assert len({room.code for room in rooms}) == 20
    assert len({room.room_id for room in rooms}) == 20
    for room in rooms:
        assert len(room.code) == CODE_LENGTH
        assert set(room.code) <= set(CODE_ALPHABET)
        assert registry.get(room.code) is room


def test_code_alphabet_has_no_confusing_characters():
    assert not set("0O1IL") & set(CODE_ALPHABET)


def test_get_unknown_code_is_none():
    registry, _, _ = make()
    assert registry.get("ZZZZZZ") is None


# --- 入室 ---


def test_join_creates_player_with_token():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, " はなこ ")
    assert player.name == "はなこ"
    assert len(player.token) >= 16
    assert room.players[player.token] is player


def test_rejoin_with_token_keeps_player_and_name():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    assert registry.join(room, player.token, "別の名前") is player
    assert player.name == "はなこ"


def test_unknown_token_creates_new_player():
    registry, _, _ = make()
    room = registry.create()
    first = registry.join(room, None, "はなこ")
    second = registry.join(room, "見知らぬ合言葉", "じろう")
    assert second is not first
    assert second.player_id != first.player_id


@pytest.mark.parametrize("name", ["", "   ", "あ" * 21])
def test_join_rejects_invalid_name(name):
    registry, _, _ = make()
    room = registry.create()
    with pytest.raises(InvalidName):
        registry.join(room, None, name)
    assert room.players == {}


def test_player_limit_applies_only_to_new_players():
    registry, _, _ = make(max_players=2)
    room = registry.create()
    first = registry.join(room, None, "たろう")
    registry.join(room, None, "はなこ")
    with pytest.raises(RoomFull):
        registry.join(room, None, "じろう")
    assert registry.join(room, first.token, "たろう") is first


# --- 接続 ---


def test_attach_and_detach_track_online_per_connection():
    registry, _, _ = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    assert not room.is_online(player)
    registry.attach(room, "tab-1", player)
    registry.attach(room, "tab-2", player)
    registry.detach(room, "tab-1")
    assert room.is_online(player)
    registry.detach(room, "tab-2")
    assert not room.is_online(player)


# --- ルーム数の上限 ---


def test_room_limit_evicts_oldest_room_without_connections():
    registry, clock, removed = make(max_rooms=2)
    oldest = registry.create()
    clock.advance(1)
    registry.create()
    clock.advance(1)
    newest = registry.create()
    assert removed == [oldest]
    assert registry.get(oldest.code) is None
    assert registry.get(newest.code) is newest


def test_room_limit_never_evicts_rooms_with_connections():
    registry, clock, removed = make(max_rooms=2)
    playing = registry.create()
    registry.attach(playing, "tab", registry.join(playing, None, "たろう"))
    clock.advance(1)
    empty = registry.create()
    registry.create()
    assert removed == [empty]
    assert registry.get(playing.code) is playing


def test_room_limit_raises_when_every_room_has_connections():
    registry, _, removed = make(max_rooms=2)
    for name in ("たろう", "はなこ"):
        room = registry.create()
        registry.attach(room, name, registry.join(room, None, name))
    with pytest.raises(RoomLimitReached):
        registry.create()
    assert removed == []


# --- 片付け ---


def test_cleanup_removes_room_nobody_joined_after_10_minutes():
    registry, clock, removed = make()
    room = registry.create()
    clock.advance(599)
    registry.cleanup()
    assert registry.get(room.code) is room
    clock.advance(1)
    registry.cleanup()
    assert registry.get(room.code) is None
    assert removed == [room]


def test_cleanup_removes_joined_room_after_6_hours_without_connections():
    registry, clock, removed = make()
    room = registry.create()
    player = registry.join(room, None, "はなこ")
    registry.attach(room, "tab", player)
    clock.advance(7 * 3600)
    registry.cleanup()
    assert registry.get(room.code) is room
    registry.detach(room, "tab")
    clock.advance(6 * 3600 - 1)
    registry.cleanup()
    assert registry.get(room.code) is room
    clock.advance(1)
    registry.cleanup()
    assert removed == [room]


# --- 履歴 ---


def test_add_entry_numbers_entries_and_keeps_latest_300():
    registry, _, _ = make()
    room = registry.create()
    entries = [room.add_entry(None, str(i)) for i in range(305)]
    assert [entry.entry_id for entry in entries[:2]] == [1, 2]
    assert len(room.log) == 300
    assert room.log[0].text == "5"


def test_entry_to_message():
    registry, _, _ = make()
    room = registry.create()
    entry = room.add_entry("はなこ", "❓ 果物ですか？\n… 判定中", pending=True)
    assert entry.to_message() == {"id": 1, "author": "はなこ", "text": "❓ 果物ですか？\n… 判定中", "pending": True}


def test_entry_kind_and_data_are_sent_only_when_set():
    room = RoomRegistry().create()
    plain = room.add_entry(None, "本文")
    card = room.add_entry(None, "結果", kind="insider_result", data={"winner": "insider"})
    assert plain.to_message() == {"id": plain.entry_id, "author": None, "text": "本文", "pending": False}
    assert card.to_message() == {
        "id": card.entry_id,
        "author": None,
        "text": "結果",
        "pending": False,
        "kind": "insider_result",
        "data": {"winner": "insider"},
    }


def test_room_starts_without_insider_round():
    assert RoomRegistry().create().insider is None
