import json

import pytest

from tests.line_golden import (
    FIXTURE,
    JAVA_SPECIAL_FORM_URL,
    NO_VILLAGE_TEXT,
    STEPS,
    Normalizer,
    Step,
    differences,
    first_number,
    replay,
)

BASE = "https://game.example.com"
FORM = f"{BASE}/village/special"


def test_village_numbers_become_placeholders_in_order_of_appearance():
    normalizer = Normalizer([])
    assert normalizer.messages([{"type": "text", "text": "1234村 と 56789"}]) == [{"type": "text", "text": "<N1>村 と <N2>"}]
    assert normalizer.messages([{"type": "text", "text": "56789"}]) == [{"type": "text", "text": "<N2>"}]


def test_nulls_images_forms_seats_and_candidate_words_are_hidden():
    java = {
        "type": "template",
        "altText": "お題は「すいか」です。確定しますか？",
        "quickReply": None,
        "template": {
            "type": "buttons",
            "thumbnailImageUrl": "https://lh3.example/abc",
            "imageAspectRatio": None,
            "imageSize": "contain",
            "text": "お題は「すいか」です。確定しますか？",
            "defaultAction": None,
            "actions": [
                {"type": "message", "label": "確定", "text": "すいか"},
                {"type": "postback", "label": "初心者", "data": "2", "displayText": None},
            ],
        },
    }
    texts = [{"type": "text", "text": JAVA_SPECIAL_FORM_URL}, {"type": "text", "text": "あなたは2番目の参加者です。"}]
    assert Normalizer([JAVA_SPECIAL_FORM_URL]).messages([java, *texts]) == [
        {
            "type": "template",
            "altText": "お題は「<WORD>」です。確定しますか？",
            "template": {
                "type": "buttons",
                "thumbnailImageUrl": "<IMAGE>",
                "imageSize": "contain",
                "text": "お題は「<WORD>」です。確定しますか？",
                "actions": [
                    {"type": "message", "label": "確定", "text": "<WORD>"},
                    {"type": "postback", "label": "初心者", "data": "2"},
                ],
            },
        },
        {"type": "text", "text": "<SPECIAL_FORM_URL>"},
        {"type": "text", "text": "あなたは<SEAT>番目の参加者です。"},
    ]


def test_first_number_reads_the_text_not_the_image_urls():
    messages = [{"type": "template", "altText": "1234村 を新しく作成しました。", "template": {"thumbnailImageUrl": "https://x/98765"}}]
    assert first_number(messages) == "1234"


def test_groups_are_compared_without_order_and_no_village_matches_none():
    steps = [Step("A", "x", group="g"), Step("B", "x", group="g"), Step("X", "500")]
    java = [
        {"user": "A", "text": "x", "messages": [{"type": "text", "text": "村人"}]},
        {"user": "B", "text": "x", "messages": [{"type": "text", "text": "インサイダー"}]},
        {"user": "X", "text": "500", "messages": [{"type": "text", "text": NO_VILLAGE_TEXT}]},
    ]
    python = [[{"type": "text", "text": "インサイダー"}], [{"type": "text", "text": "村人"}], None]
    assert differences(steps, java, python, FORM) == []
    python[2] = [{"type": "text", "text": "x"}]
    assert len(differences(steps, java, python, FORM)) == 1


def test_python_answers_line_exactly_like_the_java_linebot():
    # Java から採っていなくても、手順が Python の中核で最後まで通る（村ができる）ことは確かめる
    outputs = replay(BASE)
    if not FIXTURE.exists():
        pytest.skip(f"{FIXTURE.name} をまだ Java の LineBot から採っていない（採り方は tests/line_golden.py の docstring）")
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # 手順を変えたら、Java から採り直す（tests/line_golden.py の docstring）
    assert [step["user"] for step in golden["steps"]] == [step.user for step in STEPS]
    assert differences(STEPS, golden["steps"], outputs, FORM) == []
