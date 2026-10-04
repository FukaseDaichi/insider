import asyncio

from insider_bot.game import GameManager
from insider_bot.judge import JudgeError, Verdict
from insider_bot.service import GameService, Outcome
from tests.fakes import FakeClock, FakeJudge

CH = 1
SETTER = 10
PLAYER = 20
CORRECT = Verdict(1.0, True, "exact")


def make(judge=None):
    clock = FakeClock()
    judge = judge or FakeJudge()
    manager = GameManager(clock=clock)
    return GameService(manager, judge, clock=clock), manager, judge, clock


async def started(judge=None, topic="りんご", hint=""):
    service, manager, judge, clock = make(judge)
    await service.start(CH, SETTER, "出題者", topic, hint)
    return service, manager, judge, clock


async def wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


# --- start / status / giveup ---


async def test_start_returns_private_confirmation_and_public_announcement():
    service, manager, _, _ = make()
    outcome = await service.start(CH, SETTER, "出題者", "りんご", "赤い果物")
    assert outcome == Outcome(
        private="お題『りんご』を登録しました",
        public="🎮 ゲーム開始！出題者さんがお題を出しました。質問をどうぞ\n質問は最後に「？」をつけてね（例: 果物ですか？）",
    )
    assert manager.get(CH).hint == "赤い果物"


async def test_start_strips_whitespace_around_topic_and_hint():
    service, manager, _, _ = make()
    await service.start(CH, SETTER, "出題者", "　りんご ", " 赤い ")
    game = manager.get(CH)
    assert (game.topic, game.hint) == ("りんご", "赤い")


async def test_start_rejects_blank_topic():
    service, manager, _, _ = make()
    outcome = await service.start(CH, SETTER, "出題者", "　 ", "")
    assert outcome == Outcome(private="お題を入力してください")
    assert manager.get(CH) is None


async def test_start_while_running_is_private_error():
    service, manager, _, _ = await started()
    outcome = await service.start(CH, 99, "別の人", "みかん", "")
    assert outcome == Outcome(private="このチャンネルではゲームが進行中です")
    assert manager.get(CH).topic == "りんご"


async def test_status_without_game():
    service, _, _, _ = make()
    assert await service.status(CH) == Outcome(private="進行中のゲームはありません")


async def test_status_with_game_is_private():
    service, _, _, clock = await started()
    await service.handle_question(CH, PLAYER, "p", "果物？")
    clock.advance(65)
    assert await service.status(CH) == Outcome(
        private="進行中のゲーム　出題者: 出題者　質問数: 1　経過時間: 1分5秒"
    )


async def test_giveup_reveals_topic_publicly_and_ends():
    service, manager, _, _ = await started()
    await service.handle_question(CH, PLAYER, "p", "果物？")
    assert await service.giveup(CH) == Outcome(public="🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）")
    assert manager.get(CH) is None


async def test_giveup_without_game_is_private():
    service, _, _, _ = make()
    assert await service.giveup(CH) == Outcome(private="進行中のゲームはありません")


# --- handle_question ---


async def test_question_without_game_is_ignored():
    service, _, judge, _ = make()
    assert await service.handle_question(CH, PLAYER, "p", "果物？") == Outcome()
    assert judge.calls == []


async def test_question_gets_public_answer_and_counts():
    service, manager, judge, _ = await started(hint="赤い果物")
    outcome = await service.handle_question(CH, PLAYER, "p", "果物ですか？")
    assert outcome == Outcome(public="❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%", yes_percent=82)
    assert judge.calls == [("りんご", "赤い果物", "果物ですか？")]
    assert manager.get(CH).question_count == 1


async def test_setter_and_blank_messages_are_ignored():
    service, manager, judge, _ = await started()
    assert await service.handle_question(CH, SETTER, "出題者", "果物？") == Outcome()
    assert await service.handle_question(CH, PLAYER, "p", " \n　") == Outcome()
    assert judge.calls == []
    assert manager.get(CH).question_count == 0


async def test_setter_question_is_judged_when_setter_can_ask():
    service, manager, judge, _ = await started()
    outcome = await service.handle_question(CH, SETTER, "出題者", "果物ですか？", setter_can_ask=True)
    assert outcome == Outcome(public="❓ 果物ですか？\n✅ はい　　はい 82% ██████████░░ いいえ 18%", yes_percent=82)
    assert manager.get(CH).question_count == 1


async def test_only_messages_ending_with_question_mark_are_judged():
    service, manager, judge, _ = await started()
    for chat in ("果物ですか", "りんご！", "わからない?!", "？ヒント欲しい"):
        assert await service.handle_question(CH, PLAYER, "p", chat) == Outcome()
    assert judge.calls == []
    assert manager.get(CH).question_count == 0


async def test_fullwidth_and_halfwidth_question_marks_with_trailing_space_are_judged():
    service, manager, judge, _ = await started()
    for question in ("果物ですか？", "赤い?", "丸い？ \n"):
        assert (await service.handle_question(CH, PLAYER, "p", question)).public is not None
    assert [call[2] for call in judge.calls] == ["果物ですか？", "赤い?", "丸い？ \n"]
    assert manager.get(CH).question_count == 3


async def test_correct_answer_ends_game_and_counts_winning_question():
    judge = FakeJudge(answers={"りんご？": CORRECT})
    service, manager, _, clock = await started(judge)
    clock.advance(392)
    outcome = await service.handle_question(CH, PLAYER, "回答者", "りんご？")
    assert outcome == Outcome(
        public="🎉 正解です！お題は「りんご」でした\n正解者: 回答者　質問数: 1　経過時間: 6分32秒",
        is_correct=True,
    )
    assert manager.get(CH) is None
    assert outcome.yes_percent is None


async def test_judge_error_replies_and_does_not_count():
    service, manager, _, _ = await started(FakeJudge(error=JudgeError("down")))
    outcome = await service.handle_question(CH, PLAYER, "p", "果物？")
    assert outcome == Outcome(public="⚠️ 判定できませんでした。もう一度どうぞ")
    assert manager.get(CH).question_count == 0


# --- 排他制御 ---


async def test_two_simultaneous_correct_guesses_announce_once():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=CORRECT, gate=gate))
    first = asyncio.create_task(service.handle_question(CH, PLAYER, "a", "りんご？"))
    await wait_until(lambda: judge.calls)
    second = asyncio.create_task(service.handle_question(CH, 21, "b", "林檎？"))
    await asyncio.sleep(0)
    gate.set()
    outcomes = [await first, await second]
    assert sum("正解です" in (o.public or "") for o in outcomes) == 1
    assert outcomes[1] == Outcome()
    assert len(judge.calls) == 1


async def test_giveup_waits_for_in_flight_question():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=Verdict(0.3, False, "jev"), gate=gate))
    question = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "動物？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    assert not giveup.done()
    gate.set()
    assert (await question).public.startswith("❓ 動物？")
    assert await giveup == Outcome(public="🏳️ ギブアップ！お題は『りんご』でした（質問数: 1）")


async def test_giveup_after_in_flight_correct_answer_finds_no_game():
    gate = asyncio.Event()
    service, _, judge, _ = await started(FakeJudge(default=CORRECT, gate=gate))
    question = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "りんご？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    gate.set()
    assert "正解です" in (await question).public
    assert await giveup == Outcome(private="進行中のゲームはありません")


async def test_stale_question_is_not_judged_in_next_game():
    gate = asyncio.Event()
    service, manager, judge, _ = await started(FakeJudge(gate=gate))
    in_flight = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "果物？"))
    await wait_until(lambda: judge.calls)
    giveup = asyncio.create_task(service.giveup(CH))
    await asyncio.sleep(0)
    restart = asyncio.create_task(service.start(CH, 30, "次の出題者", "みかん", ""))
    await asyncio.sleep(0)
    # 旧ゲームがまだ残っている間に届いた質問（旧ゲームの game_id を記録してロック待ちになる）
    stale = asyncio.create_task(service.handle_question(CH, PLAYER, "p", "丸いですか？"))
    await asyncio.sleep(0)
    gate.set()
    await in_flight
    await giveup
    await restart
    assert await stale == Outcome()
    assert len(judge.calls) == 1
    game = manager.get(CH)
    assert (game.topic, game.question_count) == ("みかん", 0)


async def test_judge_error_is_logged_as_one_line_warning(caplog):
    service, _, _, _ = await started(FakeJudge(error=JudgeError("TypeSafeAPITimeoutError: Request timed out")))
    with caplog.at_level("WARNING", logger="insider_bot.service"):
        await service.handle_question(CH, PLAYER, "p", "果物？")
    [record] = caplog.records
    assert record.levelname == "WARNING"
    assert record.exc_info is None
    assert "TypeSafeAPITimeoutError: Request timed out" in record.getMessage()
