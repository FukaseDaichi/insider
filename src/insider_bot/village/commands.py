"""テキスト入力の解釈。LINE のトークと Web のチャット入力で共通の 1 組だけを持つ。

経路ごとに違ってよいのは、入力の取り出し方と結果の返し方、対象の村がないときの応答だけ。
入力の解釈（数値の境界、コマンド表、空白の扱い）をここに集めるのは、片方だけを直して配布結果が
分岐しても、突き合わせる利用者がいないため誰も気付けないから。

対象の村がないときは None を返し、呼び出し側が経路に応じた既定応答へ変換する。
"""

from __future__ import annotations

from insider_bot.village import messages, texts
from insider_bot.village.parsing import java_trim, parse_java_int
from insider_bot.village.registry import MAX_VILLAGE_NUMBER, MIN_SPECIAL_NUMBER
from insider_bot.village.reply import Reply, Text
from insider_bot.village.service import VillageService
from insider_bot.village.words import UNSPECIFIED_RANK

# 設定できる参加人数の上限。これを超える数値は通常村の番号として扱う
MAX_SIZE_INPUT = 100
# ポストバックの値がこれ未満なら、村番号ではなくお題候補の難易度
TOPIC_RANK_LIMIT = 10

_CREATE = ("お題", "題", "神")
_RANDOM = ("ランダム",)
_INVITATION = ("@配布", "＠配布")
_SPECIAL = ("@特殊", "＠特殊")
_LOOKUP = ("@取得", "＠取得")
_REVERSE = ("@逆村", "＠逆村")
_WEREWORDS = ("@わーわーず", "＠わーわーず")


class CommandHandler:
    def __init__(self, service: VillageService, special_form_url: str) -> None:
        self._service = service
        self._special_form_url = special_form_url

    def handle(self, user_id: str, text: str) -> list[Reply] | None:
        # Java の String.trim() と Integer.parseInt() と同じ規則。全角数字は数値、全角スペースは除かない
        command = java_trim(text)
        number = parse_java_int(command)
        if number is not None:
            if number > MAX_VILLAGE_NUMBER:
                return self._service.join_special_village(user_id, number)
            if number > MAX_SIZE_INPUT:
                return self._service.join_village(user_id, number)
            return self._service.set_size(user_id, number)
        if command in _CREATE:
            return self._service.create_village(user_id, god_mode=command == "神")
        if command in _RANDOM:
            return self._service.create_random_village(user_id)
        if command in _INVITATION:
            return messages.invitation_reply(self._service.illust)
        if command in _SPECIAL:
            return messages.special_form_reply(self._special_form_url)
        if command in _LOOKUP:
            return self.topic_candidate(UNSPECIFIED_RANK)
        if command in _REVERSE:
            return self._service.set_reverse(user_id)
        if command in _WEREWORDS:
            return self._service.convert_to_werewords(user_id)
        # 残りはお題。前後の空白は利用者が入力したお題の一部として保つ
        return self._service.set_topic(user_id, text)

    def topic_candidate(self, rank: int) -> list[Reply]:
        """お題候補と引き直しのボタン。村を持っていなくても引けるので利用者の識別は要らない。"""
        return messages.candidate_reply(self._service.pick_topic(rank))

    # --- ポストバック ---

    def postback(self, user_id: str | None, data: str) -> list[Reply] | None:
        """ボタンのポストバック。LINE と Web で共通の 1 組だけを持つ。

        0〜9 はお題候補で、利用者の識別は要らない。それ以外は入室状況で、識別できない利用者には状態を変えずに
        1 対 1 のトークを促す。値は Integer.parseInt と同じ規則で読み、前後の空白は除かない。読めなければ None。
        """
        number = parse_java_int(data)
        if number is None:
            return None
        if 0 <= number < TOPIC_RANK_LIMIT:
            return self.topic_candidate(number)
        if user_id is None:
            return [Text(texts.ERR_UNIDENTIFIED_USER)]
        if number < MIN_SPECIAL_NUMBER:
            return self._service.village_status(user_id, number)
        return self._service.special_village_status(user_id, number)
