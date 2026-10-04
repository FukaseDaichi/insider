"""スタンプへの応答。ゲームの操作ではないので、製作者への連絡先とホームページを案内するだけ。

文言とボタンは LineBot（Java）の StickerReplyEvent と一字一句同じ。「ホームぺージ」の「ぺ」はひらがな（原文のまま）。
ホームページは Web 版の公開 URL、ご意見フォームは Java と同じ Google フォーム。
"""

from __future__ import annotations

from insider_bot.village.illust import Illustrations
from insider_bot.village.reply import Buttons, Reply, UriAction

FEEDBACK_FORM_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLSf5pH-nC86Lb9L18dx9fBJv1ZUu-qdftS_PBkBRA5imjjFVgA/viewform"
)
STICKER_MESSAGE = "ご利用ありがとうございます。要望・報告は以下にご連絡ください。"


def sticker_reply(illust: Illustrations, homepage_url: str) -> list[Reply]:
    return [
        Buttons(
            STICKER_MESSAGE,
            (UriAction("ご意見", FEEDBACK_FORM_URL), UriAction("ホームぺージ", homepage_url)),
            image=illust.url_for("INSIDER"),
            alt_text=f"製作者の「白いフランです。」\n{STICKER_MESSAGE}\n Hp:  {homepage_url}",
        )
    ]
