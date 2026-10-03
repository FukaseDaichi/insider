import logging
import random

from insider_bot.village.words import (
    ADVANCED_RANK,
    BEGINNER_RANK,
    EMPTY_DICTIONARY,
    EXPERT_RANK,
    UNSPECIFIED_RANK,
    Dictionary,
    load_dictionary,
    parse_dictionary,
)
from tests.fakes import FixedRandom

# 行番号定数で表現していた頃の難易度境界。CSV から導出した結果がこれと一致すること
SECOND_LINE = 954
THIRD_LINE = 5084
FOURTH_LINE = 7646
FIFTH_LINE = 8436


def csv_rows() -> list[list[str]]:
    from insider_bot.village import words

    path = words.DEFAULT_PATH
    return [line.rstrip("\n").split(",") for line in path.read_text(encoding="utf-8").splitlines()]


def csv_words(from_line: int, to_line: int) -> set[str]:
    return {row[0] for number, row in enumerate(csv_rows(), start=1) if from_line <= number <= to_line}


def every_draw_comes_from(dictionary: Dictionary, rank: int, from_line: int, to_line: int) -> None:
    allowed = csv_words(from_line, to_line)
    rng = random.Random(0)
    for _ in range(200):
        word = dictionary.pick(rank, rng)
        assert word is not None
        assert word in allowed, f"難易度 {rank} の範囲外のお題: {word}"


def test_the_bundled_csv_matches_the_former_boundaries():
    dictionary = load_dictionary()
    assert not dictionary.is_empty
    assert dictionary.last_line(2) == SECOND_LINE
    assert dictionary.last_line(3) == THIRD_LINE
    assert dictionary.last_line(4) == FOURTH_LINE
    assert dictionary.last_line(5) == FIFTH_LINE
    assert len(dictionary.words) == FIFTH_LINE


def test_the_csv_is_sorted_by_difficulty():
    previous = 0
    for number, row in enumerate(csv_rows(), start=1):
        assert len(row) == 2, f"2 列でない行: {number}"
        difficulty = int(row[1])
        assert 1 <= difficulty <= 5, f"難易度が 1〜5 でない行: {number}"
        assert difficulty >= previous, f"難易度が昇順でない行: {number}"
        previous = difficulty


def test_beginner_draws_from_difficulty_1_to_3():
    every_draw_comes_from(load_dictionary(), BEGINNER_RANK, 1, THIRD_LINE)


def test_advanced_draws_from_difficulty_3_to_4():
    every_draw_comes_from(load_dictionary(), ADVANCED_RANK, SECOND_LINE + 1, FOURTH_LINE)


def test_expert_draws_from_difficulty_5():
    every_draw_comes_from(load_dictionary(), EXPERT_RANK, FOURTH_LINE + 1, FIFTH_LINE)


def test_unspecified_draws_from_everything_but_expert():
    every_draw_comes_from(load_dictionary(), UNSPECIFIED_RANK, 1, FOURTH_LINE)
    every_draw_comes_from(load_dictionary(), 0, 1, FOURTH_LINE)


def test_pick_uses_the_draw_as_a_line_number():
    dictionary = parse_dictionary(["a,1", "b,2", "c,3", "d,4", "e,5"])
    # 初心者: 1〜last(3)=3 行目。randrange(3) → 0 なら 1 行目
    assert dictionary.pick(BEGINNER_RANK, FixedRandom(0)) == "a"
    assert dictionary.pick(BEGINNER_RANK, FixedRandom(2)) == "c"
    # 上級者: last(2)+1=3 〜 last(4)=4 行目
    assert dictionary.pick(ADVANCED_RANK, FixedRandom(0)) == "c"
    assert dictionary.pick(ADVANCED_RANK, FixedRandom(1)) == "d"
    # 変態: last(4)+1=5 〜 last(5)=5 行目
    assert dictionary.pick(EXPERT_RANK, FixedRandom(0)) == "e"
    # 指定なし: 1 〜 last(4)=4 行目
    assert dictionary.pick(UNSPECIFIED_RANK, FixedRandom(3)) == "d"


def test_empty_dictionary_picks_none():
    assert EMPTY_DICTIONARY.is_empty
    assert EMPTY_DICTIONARY.pick(BEGINNER_RANK, random.Random(0)) is None
    assert EMPTY_DICTIONARY.last_line(3) == 0


def test_broken_csv_is_discarded_entirely(caplog):
    broken = [
        ["a,1", "b,3", "c,2", "d,4", "e,5"],  # 昇順を破る
        ["a,1", "b,2", "c,4", "d,5"],  # 難易度 3 の語がない
        ["a,1", "b,x", "c,3", "d,4", "e,5"],  # 整数でない
        ["a", "b,2", "c,3", "d,4", "e,5"],  # 2 列目がない
        ["a,0", "b,2", "c,3", "d,4", "e,5"],  # 範囲外
        ["a,1", "b,2", "c,3", "d,4", "e,6"],  # 範囲外
        ["a,0_1", "b,2", "c,3", "d,4", "e,5"],  # Integer.parseInt は「_」を読めない
        ["a,　1　", "b,2", "c,3", "d,4", "e,5"],  # trim() は全角スペースを除かない
    ]
    for lines in broken:
        with caplog.at_level(logging.ERROR, logger="insider_bot.village.words"):
            caplog.clear()
            dictionary = parse_dictionary(lines)
        assert dictionary.is_empty, lines
        assert any(record.levelno == logging.ERROR for record in caplog.records), lines


def test_only_the_first_column_is_the_word_and_the_difficulty_is_trimmed():
    # Java の split(",") と同じく 1 列目だけを語として使い、3 列目以降は無視する。難易度は trim してから読む
    dictionary = parse_dictionary(["a,1,extra", "b, 2 ", "c,3", "d,４", "e,5"])
    assert dictionary.words[0] == "a"
    assert dictionary.last_line(2) == 2
    assert dictionary.last_line(4) == 4


def test_missing_file_gives_an_empty_dictionary(tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="insider_bot.village.words"):
        dictionary = load_dictionary(tmp_path / "nope.csv")
    assert dictionary.is_empty
    assert caplog.records


def test_invalid_utf8_is_replaced_with_replacement_character(tmp_path):
    # Java の InputStreamReader(..., UTF_8) は不正なバイトを U+FFFD に置換して読む
    csv_path = tmp_path / "w.csv"
    csv_path.write_bytes(b"a\xff,1\nb,2\nc,3\nd,4\ne,5\n")
    dictionary = load_dictionary(csv_path)
    assert not dictionary.is_empty
    assert dictionary.words[0] == "a�"
