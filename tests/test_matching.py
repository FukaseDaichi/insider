import pytest

from insider_bot.judge import extract_guess, is_exact_guess, normalize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("リンゴ", "りんご"),
        ("ﾘﾝｺﾞ", "りんご"),
        ("ＡＰＰＬＥ", "apple"),
        ("り ん\tご\n", "りんご"),
        ("　りんご　", "りんご"),
        ("ビール", "びーる"),
        ("C++", "c++"),
    ],
)
def test_normalize(text, expected):
    assert normalize(text) == expected


def test_normalize_keeps_long_vowel_mark_so_beer_and_building_differ():
    assert normalize("ビール") != normalize("ビル")


@pytest.mark.parametrize(
    "question",
    ["リンゴ？", "ﾘﾝｺﾞ", "りんご", "りんごですか", "りんごですか？", "りんごでしょうか？！", "りんごかな？", "りんご!!"],
)
def test_exact_guess_matches(question):
    assert is_exact_guess("りんご", question)


@pytest.mark.parametrize(
    "question",
    ["りんごか？", "りんごではない？", "りんごより大きい？", "青りんごですか", "林檎", "りんごかみかん？"],
)
def test_exact_guess_does_not_match(question):
    assert not is_exact_guess("りんご", question)


def test_single_char_ending_is_not_stripped():
    assert not is_exact_guess("すい", "すいか？")


def test_topic_ending_with_question_like_suffix_still_matches():
    assert is_exact_guess("さかな", "さかな？")


def test_beer_does_not_match_building():
    assert not is_exact_guess("ビール", "ビル？")


def test_extract_guess_candidates():
    assert extract_guess("りんごですか？") == {"りんごですか", "りんご"}


@pytest.mark.parametrize("question", ["？？", "", "　", "!?"])
def test_punctuation_only_question_has_no_candidates(question):
    assert extract_guess(question) == set()
    assert not is_exact_guess("りんご", question)


def test_blank_topic_never_matches():
    assert not is_exact_guess("　", "")
