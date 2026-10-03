"""村の構造化操作。LINE と Web で共通のゲーム規則で、経路を知らない。

対象の村が見つからない場合はどのメソッドも None を返す。村が消えている、まだ作っていない、条件を満たさない、
はいずれも利用者の操作として起こりうることで、例外ではない。呼び出し側が経路に応じた既定応答へ変換する。

どのメソッドも同期で、途中に await を挟まない。asyncio 単一スレッドでは、これが Java の synchronized と
同じ「途中経過が他から観測されない」保証になる。
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from insider_bot.village import messages
from insider_bot.village.illust import Illustrations
from insider_bot.village.model import Rng, SpecialVillage, Village
from insider_bot.village.registry import SpecialVillageRegistry, VillageRegistry
from insider_bot.village.reply import Reply
from insider_bot.village.werewords import MIN_WEREWORDS_SIZE, werewords_messages
from insider_bot.village.words import BEGINNER_RANK, Dictionary


@dataclass(frozen=True)
class OwnedVillage:
    """オーナーから見た、自分の最新の村の進み具合。画面が次に聞くこと（お題・人数）を決めるのに使う。

    お題そのものは持たない（配布状況の返事で本人には見える）。
    """

    number: int
    mode: str
    has_topic: bool
    size: int
    member_count: int
    reverse: bool


class VillageService:
    def __init__(
        self,
        villages: VillageRegistry,
        specials: SpecialVillageRegistry,
        dictionary: Dictionary,
        illust: Illustrations,
        rng: Rng | None = None,
    ) -> None:
        self._villages = villages
        self._specials = specials
        self._dictionary = dictionary
        self._illust = illust
        self._rng: Rng = rng if rng is not None else random.Random()

    @property
    def illust(self) -> Illustrations:
        return self._illust

    # --- 作成 ---

    def create_village(self, user_id: str, god_mode: bool) -> list[Reply]:
        village = Village(user_id)
        if god_mode:
            village.mark_god_mode()
        number = self._villages.add(village)
        return messages.created_reply(number)

    def create_random_village(self, user_id: str) -> list[Reply]:
        """お題は初心者から自動で引き、GM も抽選する。オーナーに聞くのは人数だけ。"""
        village = Village(user_id)
        village.mark_god_mode()
        village.random_mode = True
        topic = self.pick_topic(BEGINNER_RANK)
        if topic is not None:
            # 辞書が壊れていると引けない。Java と同じくお題は未設定のまま残り、次の自由文入力がお題になる
            village.set_topic(topic)
        number = self._villages.add(village)
        return messages.random_created_reply(number)

    # --- 設定 ---

    def set_size(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.find_latest_owned(user_id, lambda v: v.size == 0)
        if village is None:
            return None
        if number <= 1:
            return messages.size_error_reply()
        # 神モードかどうかは人数確定で上書きされるので先に控える
        god_mode = village.is_god_mode_awaiting_size()
        random_mode = village.random_mode
        if not village.configure(number, self._rng):
            return None
        if random_mode:
            return messages.random_size_set_reply(village, number, self._illust)
        return messages.size_set_reply(village, god_mode, self._illust)

    def set_topic(self, user_id: str, topic: str) -> list[Reply] | None:
        village = self._villages.find_latest_owned(user_id, lambda v: v.topic is None)
        if village is None or not village.set_topic(topic):
            return None
        return messages.topic_set_reply(village)

    def set_reverse(self, user_id: str) -> list[Reply] | None:
        # ランダム村は GM とインサイダーを 1 人ずつ配るので逆村にしない
        village = self._villages.find_latest_owned(user_id, lambda v: not v.has_members() and not v.random_mode)
        if village is None or not village.apply_reverse():
            return None
        return messages.reverse_set_reply(village)

    def create_werewords(self, user_id: str) -> tuple[list[Reply], int] | None:
        """元の村は残し、配布メッセージだけを持つ特殊村を新しく作る。返事と、作った特殊村の番号を返す。

        人数とお題が揃っていなければ None。
        """
        village = self._villages.find_latest_owned(user_id, lambda v: not v.has_members())
        if village is None or village.size < MIN_WEREWORDS_SIZE or village.topic is None:
            return None
        god_mode = village.has_game_master()
        number = self.create_special_village(werewords_messages(god_mode, village.size, village.topic, self._rng))
        return messages.werewords_created_reply(village.topic, number, god_mode), number

    def convert_to_werewords(self, user_id: str) -> list[Reply] | None:
        """create_werewords の返事だけを返す。特殊村の番号は返事の本文にある。"""
        created = self.create_werewords(user_id)
        return None if created is None else created[0]

    # --- 参加と状況 ---

    def join_village(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.get(number)
        if village is None:
            return None
        if user_id == village.owner_id:
            if not village.random_mode:
                return messages.owner_reply(village)
            if village.role_of(user_id) is None:
                # 人数未設定で、まだ配役されていない
                return messages.random_numset_reply()
        elif village.role_of(user_id) is None and village.join(user_id) is None:
            return messages.full_reply()
        return messages.role_reply(village, user_id, self._illust)

    def village_status(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._villages.get(number)
        return None if village is None else messages.status_reply(village, user_id)

    def join_special_village(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._specials.get(number)
        if village is None:
            return None
        if not village.join(user_id):
            return messages.full_reply()
        return messages.special_role_reply(village, user_id)

    def special_village_status(self, user_id: str, number: int) -> list[Reply] | None:
        village = self._specials.get(number)
        return None if village is None else messages.status_reply(village, user_id)

    # --- 特殊村と辞書 ---

    def create_special_village(self, texts: Sequence[str | None]) -> int:
        """複製して並べ替え、登録して番号を返す。呼び出し元の列は変えない。"""
        shuffled = list(texts)
        self._rng.shuffle(shuffled)
        return self._specials.add(SpecialVillage(shuffled))

    def pick_topic(self, rank: int) -> str | None:
        return self._dictionary.pick(rank, self._rng)

    # --- オーナーから見た村 ---

    def latest_owned(self, user_id: str) -> OwnedVillage | None:
        """利用者がオーナーの、最も新しい村の要約。作成の直後に呼べば、いま作った村を指す。"""
        village = self._villages.find_latest_owned(user_id, lambda v: True)
        if village is None:
            return None
        if village.random_mode:
            mode = "random"
        elif village.has_game_master():
            mode = "god"
        else:
            mode = "normal"
        return OwnedVillage(
            number=village.number,
            mode=mode,
            has_topic=village.topic is not None,
            size=village.size,
            member_count=village.member_count(),
            reverse=village.reverse,
        )
