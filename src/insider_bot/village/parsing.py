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
    # Java の Integer.parseInt は UTF-16 の 1 文字ずつ読むので、BMP 外の数字はサロゲートペアになり読めない
    if any(ord(c) > 0xFFFF for c in text):
        return None

    if not _JAVA_INT.fullmatch(text):
        return None

    sign = text[0] if text[0] in "+-" else ""
    digits = text[len(sign) :]

    # 先頭の 0（全角の「０」など他の 10 進数字の 0 を含む）は桁数に数えない。
    # 1 文字ずつ切り詰めると入力長の 2 乗かかるので、添字を進めて 1 回で読み飛ばす
    start = 0
    while start < len(digits) and unicodedata.digit(digits[start]) == 0:
        start += 1
    significant = digits[start:]

    # int32 は 10 桁まで。桁数で先に弾き、巨大な数字列を int() に渡さない
    if len(significant) > 10:
        return None

    value = int(sign + significant) if significant else 0
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


def java_length(text: str) -> int:
    """Java の String.length() と同じく UTF-16 の符号単位で数える（絵文字は 2）。LINE の文字数の上限はこの数え方。"""
    return len(text.encode("utf-16-le")) // 2
