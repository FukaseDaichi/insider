import pytest

from insider_bot.game import GameAlreadyRunning, GameManager
from tests.fakes import FakeClock


def test_start_creates_game_with_fields():
    manager = GameManager(clock=FakeClock(500.0))
    game = manager.start(1, "りんご", "赤い果物", 10, "出題者")
    assert (game.channel_id, game.topic, game.hint, game.setter_id, game.setter_name) == (
        1, "りんご", "赤い果物", 10, "出題者",
    )
    assert game.started_at == 500.0
    assert game.question_count == 0
    assert manager.get(1) is game


def test_one_game_per_channel():
    manager = GameManager()
    manager.start(1, "りんご", "", 10, "a")
    with pytest.raises(GameAlreadyRunning):
        manager.start(1, "みかん", "", 11, "b")


def test_channels_are_independent():
    manager = GameManager()
    a = manager.start(1, "りんご", "", 10, "a")
    b = manager.start(2, "みかん", "", 11, "b")
    assert manager.get(1) is a and manager.get(2) is b


def test_end_removes_and_returns_game():
    manager = GameManager()
    game = manager.start(1, "りんご", "", 10, "a")
    assert manager.end(1) is game
    assert manager.get(1) is None
    assert manager.end(1) is None


def test_game_ids_are_unique_even_in_same_channel():
    manager = GameManager()
    first = manager.start(1, "りんご", "", 10, "a")
    manager.end(1)
    second = manager.start(1, "りんご", "", 10, "a")
    assert first.game_id != second.game_id
