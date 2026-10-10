import pytest

from insider_bot.web.insider import (
    Ending,
    InsiderRound,
    InvalidSetup,
    Phase,
    Setup,
    check_setup,
    check_topic,
    deal,
)
from tests.fakes import FixedRandom

ROOM = {1, 2, 3, 4}


def round_of(*participants: int, insider: int = 1, minutes: int | None = None) -> InsiderRound:
    return InsiderRound(participants=tuple(participants), insider_id=insider, topic_mode="random", minutes=minutes)


# --- 設定の検査 ---


def test_setup_keeps_order_and_drops_duplicates():
    setup = check_setup(ROOM, 1, [3, 1, 3, 2], "random", None, None)
    assert setup == Setup((3, 1, 2), "random", None, None)


@pytest.mark.parametrize(
    ("participants", "mode", "topic", "minutes", "message"),
    [
        ([1, 2], "random", None, None, "参加者を3人以上選んでください"),
        ([1, 2, 9], "random", None, None, "ルームにいない人は選べません"),
        ([1, 2, 3], "dance", None, None, "お題の決め方が正しくありません"),
        ([1, 2, 3], "random", None, 0, "制限時間は1〜30分で選んでください"),
        ([1, 2, 3], "random", None, 31, "制限時間は1〜30分で選んでください"),
        ([2, 3, 4], "self", "  ", None, "お題は1〜50文字で入力してください"),
        ([2, 3, 4], "self", "あ" * 51, None, "お題は1〜50文字で入力してください"),
        ([1, 2, 3, 4], "self", "りんご", None, "お題を決める人は参加者になれません"),
    ],
)
def test_setup_rejects(participants, mode, topic, minutes, message):
    with pytest.raises(InvalidSetup, match=message):
        check_setup(ROOM, 1, participants, mode, topic, minutes)


def test_self_topic_is_trimmed_and_other_modes_drop_topic():
    assert check_setup(ROOM, 1, [2, 3, 4], "self", " りんご ", 5).topic == "りんご"
    assert check_setup(ROOM, 1, [1, 2, 3], "insider", "りんご", None).topic is None
    assert check_setup(ROOM, 1, [1, 2, 3], "random", "りんご", None).topic is None


def test_check_topic():
    assert check_topic(" みかん ") == "みかん"
    with pytest.raises(InvalidSetup, match="お題は1〜50文字で入力してください"):
        check_topic("")


# --- くじと役職 ---


def test_deal_picks_insider_by_rng():
    rnd = deal(Setup((3, 1, 2), "random", None, 5), FixedRandom(2))
    assert rnd.insider_id == 2
    assert rnd.phase is Phase.CHOOSING
    assert (rnd.role_of(2), rnd.role_of(3), rnd.role_of(4)) == ("insider", "villager", None)


def test_begin_sets_deadline_only_with_minutes():
    timed = round_of(1, 2, 3, minutes=5)
    timed.begin("りんご", game_id=7, now=100.0)
    assert (timed.phase, timed.topic, timed.game_id, timed.deadline) == (Phase.ASKING, "りんご", 7, 400.0)
    assert timed.remaining(now=160.0) == 240.0
    assert timed.remaining(now=999.0) == 0.0
    untimed = round_of(1, 2, 3)
    untimed.begin("りんご", game_id=8, now=100.0)
    assert untimed.deadline is None and untimed.remaining(now=500.0) is None


# --- 投票 ---


def voting(*participants: int, insider: int = 1) -> InsiderRound:
    rnd = round_of(*participants, insider=insider)
    rnd.begin("りんご", game_id=1, now=0.0)
    rnd.start_voting("はなこ")
    return rnd


def test_start_voting_clears_deadline_and_records_guesser():
    rnd = round_of(1, 2, 3, minutes=3)
    rnd.begin("りんご", game_id=1, now=0.0)
    rnd.start_voting("はなこ")
    assert (rnd.phase, rnd.deadline, rnd.guesser) == (Phase.VOTING, None, "はなこ")


@pytest.mark.parametrize(
    ("voter", "target", "message"),
    [
        (1, 1, "自分には投票できません"),
        (9, 2, "参加者だけが投票できます"),
        (1, 9, "参加者の中から選んでください"),
    ],
)
def test_vote_rejects(voter, target, message):
    rnd = voting(1, 2, 3)
    assert rnd.vote(voter, target) == message
    assert rnd.votes == {}


def test_vote_is_rejected_outside_voting():
    rnd = round_of(1, 2, 3)
    assert rnd.vote(1, 2) == "いまは投票できません"


def test_vote_can_be_changed_and_all_voted():
    rnd = voting(1, 2, 3)
    assert rnd.vote(1, 2) is None
    assert rnd.vote(1, 3) is None
    assert rnd.votes == {1: 3}
    assert not rnd.all_voted()
    rnd.vote(2, 1)
    rnd.vote(3, 1)
    assert rnd.all_voted()


@pytest.mark.parametrize(
    ("votes", "counts", "villagers_win"),
    [
        ({1: 2, 2: 1, 3: 1}, {1: 2, 2: 1, 3: 0}, True),  # インサイダー 1 が単独最多
        ({1: 2, 2: 3, 3: 2}, {1: 0, 2: 2, 3: 1}, False),  # 別の人が最多
        ({1: 2, 2: 1}, {1: 1, 2: 1, 3: 0}, False),  # 同票
    ],
)
def test_tally(votes, counts, villagers_win):
    rnd = voting(1, 2, 3, insider=1)
    rnd.votes = dict(votes)
    tally = rnd.tally()
    assert tally.counts == counts
    assert tally.villagers_win is villagers_win


def test_finish():
    rnd = voting(1, 2, 3)
    rnd.finish(Ending.VOTED)
    assert (rnd.phase, rnd.ending) == (Phase.DONE, Ending.VOTED)
