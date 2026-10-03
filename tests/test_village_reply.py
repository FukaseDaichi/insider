from insider_bot.village.reply import Buttons, Confirm, Image, MessageAction, PostbackAction, Text, UriAction


def test_replies_compare_by_value():
    assert Text("a") == Text("a")
    assert Image("https://x/a.png") == Image("https://x/a.png")
    assert MessageAction("確認", "1234") == MessageAction("確認", "1234")
    assert PostbackAction("入室状況確認", "1234") != PostbackAction("入室状況確認", "1235")
    assert UriAction("ご意見", "https://x") == UriAction("ご意見", "https://x")


def test_buttons_defaults():
    buttons = Buttons("本文", (MessageAction("確認", "1"),))
    assert buttons.image is None
    assert buttons.title is None
    assert buttons.alt_text is None
    assert buttons.overflow == ()


def test_buttons_overflow_can_nest():
    inner = Buttons("本文", (PostbackAction("入室状況確認", "1"),), overflow=(Text("本文"),))
    outer = Buttons("本文", (PostbackAction("入室状況確認", "1"),), image="https://x/a.png", overflow=(inner,))
    assert outer.overflow[0].overflow[0] == Text("本文")


def test_confirm_has_two_actions():
    confirm = Confirm("村の作成をしますか？", (MessageAction("GM", "お題"), MessageAction("神", "神")), alt_text="案内")
    assert len(confirm.actions) == 2
    assert confirm.alt_text == "案内"
