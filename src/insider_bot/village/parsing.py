"""Java（LineBot）と同じ規則で文字列を読む。

入力の解釈が Java とずれると、同じ入力への応答が LINE 版と食い違う。Python の str.strip() と int() は
Java の String.trim() と Integer.parseInt() より受け付ける範囲が広い（全角スペースを除く、「1_0」や
int の範囲外を読む）ので、利用者の入力や外部データの解釈には使わない。
"""

from __future__ import annotations

import re
import unicodedata

# String.trim() が除くのは U+0020 以下の文字だけ
_JAVA_TRIM_CHARS = "".join(chr(code) for code in range(0x21))
# Integer.parseInt は符号 1 つと Unicode の 10 進数字（全角数字を含む）だけを受け付ける
_JAVA_INT = re.compile(r"[+-]?\d+")
_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1


def java_trim(text: str) -> str:
    return text.strip(_JAVA_TRIM_CHARS)


def parse_java_int(text: str) -> int | None:
    """Integer.parseInt と同じ規則で読む。読めなければ None。前後の空白は読めない（先に java_trim する）。"""
    if not _JAVA_INT.fullmatch(text):
        return None

    # Extract sign and digit part
    sign = ""
    digits = text
    if text and text[0] in "+-":
        sign = text[0]
        digits = text[1:]

    # Skip leading zeros (including Unicode decimal zeros like full-width ０)
    while digits and unicodedata.digit(digits[0], None) == 0:
        digits = digits[1:]

    # If more than 10 significant digits remain, outside int32 range
    if len(digits) > 10:
        return None

    # Convert remaining digits to int
    try:
        value = int(sign + digits) if digits else 0
    except ValueError:
        return None

    if not _INT_MIN <= value <= _INT_MAX:
        return None
    return value


def java_split(text: str, separator: str) -> list[str]:
    """String.split と同じく末尾の空要素を落とす。区切りが現れなければ元の文字列 1 つ。"""
    if separator not in text:
        return [text]
    parts = text.split(separator)
    while parts and parts[-1] == "":
        parts.pop()
    return parts
