import pytest

from insider_bot.village.parsing import java_split, java_trim, parse_java_int


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", 3),
        ("-5", -5),
        ("+5", 5),
        ("３", 3),  # 全角数字も Unicode の 10 進数字として読む
        ("１２", 12),
        ("٣", 3),
        ("2147483647", 2147483647),
        ("-2147483648", -2147483648),
        ("0" * 5000 + "3", 3),  # 桁数の多い 0 は読み飛ばす
        ("-" + "0" * 5000 + "3", -3),  # 負数の 0 読み飛ばし
        ("０" * 10 + "７", 7),  # 全角 0 も読み飛ばす
        ("-0", 0),
        ("+0", 0),
        ("0" * 5000, 0),  # 0 だけなら有効桁が空で 0
        ("0" * 5000 + "2147483647", 2147483647),  # 0 を除いて 10 桁なら範囲内
    ],
)
def test_reads_what_integer_parse_int_reads(text, expected):
    assert parse_java_int(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "+", "-", " 3", "3 ", "1_0", "3.0", "2147483648", "-2147483649", "99999999999", "三", "0x10", "+-3", "--3", "9" * 5000, "\U0001D7D1", "\U0001D7CF\U0001D7CE", "0" * 5000 + "2147483648"],
)
def test_rejects_what_integer_parse_int_rejects(text):
    assert parse_java_int(text) is None


def test_long_leading_zeros_are_read_in_linear_time():
    # Web からの入力は 1〜2 MB になりうる。0 の読み飛ばしが入力長の 2 乗だと数十秒止まる
    assert parse_java_int("0" * 1_000_000 + "3") == 3


def test_trim_removes_only_ascii_spaces_and_controls():
    assert java_trim(" \t\n3\r ") == "3"
    # 全角スペース（U+3000）は U+0020 より大きいので残る
    assert java_trim("　3　") == "　3　"


def test_split_drops_trailing_empty_parts():
    assert java_split("GM_1_a_", "_") == ["GM", "1", "a"]
    assert java_split("GM_1_", "_") == ["GM", "1"]
    assert java_split("_1_a", "_") == ["", "1", "a"]
    assert java_split("GM__a", "_") == ["GM", "", "a"]
    assert java_split("", "_") == [""]
    assert java_split("_", "_") == []
