"""村の文言。LineBot（Java）の MessageConst と各クラスの文字列を一字一句保つ。"""

DEFAULT_MESSAGE = "お題を配りたい方は「お題」または「神」を、\nお題及び役職を確認したい場合は村番号（数字4桁）を入力してください。"
DEFAULT_CONFIRM_TEXT = "村の作成をしますか？"

OWNER_ODAI_MESSAGE = "お題を入力してください。"
OWNER_NUMSET_MESSAGE = "お題を配りたい人数を入力してください。\n　例：「5」の場合は、「インサイダー１人、村4人」です。"
GOD_NUMSET_MESSAGE = "お題を配りたい人数を入力してください。\n　例：「6」の場合は、「GM１人、インサイダー１人、村4人」です。"
RANDOM_NUMSET_MESSAGE = "人数を設定してください。役職もお題もランダムに配ります。"
ERR_NUMSET_MESSAGE = "村の人数は2人以上に設定してください。\nもう一度村の人数を設定してください。"
ERR_UNIDENTIFIED_USER = "ユーザーを識別できないため操作できません。\nbotとの1対1のトークから操作してください。"

VILLAGE_FULL = "村がいっぱいです。"
NO_SPECIAL_MESSAGE = "メッセージは特にありません。"

INSIDER_ROLE = "インサイダー"
VILLAGER_ROLE = "村人"
GAME_MASTER_ROLE = "ＧＭ"

# Werewords。添字は役職番号（1 占師、2 インサイダー、3 村人、4 GM）
WEREWORDS_MESSAGES = (
    "",
    "あなたの役職は占師です。お題は「{0}」です。",
    "あなたの役職はインサイダーです。お題は「{0}」です。",
    "あなたの役職は村人です",
    "あなたの役職はGMです。お題は「{0}」です。\n役職は「{1}」が欠けています。",
)
WEREWORDS_ROLES = ("", "占師", "インサイダー", "村人")

OFFICIAL_ACCOUNT_URL = "https://line.me/R/ti/p/%40966mpnqz"
OFFICIAL_ACCOUNT_ID_MESSAGE = "お友達ID\n@966mpnqz"
