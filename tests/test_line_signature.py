import pytest

from insider_bot.line.signature import sign, verify

SECRET = "channel-secret"
BODY = b'{"events":[]}'


def test_sign_is_base64_of_hmac_sha256_over_the_raw_body():
    # LineBot の deploy/verify と同じ既知のベクトル: HMAC-SHA256("secret", "body") の Base64
    assert sign("secret", b"body") == "3EaYNVf+oSe0OvchRn65s/3iM4/j4U9RlSqoR4wT01U="


def test_verify_accepts_the_signature_of_the_body():
    assert verify(SECRET, BODY, sign(SECRET, BODY))


@pytest.mark.parametrize(
    ("body", "signature"),
    [
        (BODY + b" ", sign(SECRET, BODY)),
        (BODY, sign("other-secret", BODY)),
        (BODY, None),
        (BODY, ""),
        (BODY, "署名"),
        (BODY, "\udc80"),
    ],
    ids=["tampered-body", "other-secret", "missing", "empty", "non-ascii", "lone-surrogate"],
)
def test_verify_rejects_anything_else(body, signature):
    assert not verify(SECRET, body, signature)
