"""お題辞書。CSV（1 列目がお題、2 列目が難易度 1〜5）を起動時に 1 度だけ読み、難易度の区間から引く。

難易度の区間は 2 列目から導出するので、行を増減しても境界を手で直す必要はない。ただし CSV は難易度の
昇順でなければならない。難易度が読めない行、昇順を破る行、語のない難易度があれば辞書全体を破棄する。
中途半端な辞書から引くと、違う難易度のお題を黙って配ることになるため。破棄したときの抽選は None を返す。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from insider_bot.village.model import Rng
from insider_bot.village.parsing import java_split, java_trim, parse_java_int

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).parent / "word.csv"

# 利用者に見せる難易度（UI の番号）。CSV の難易度とは体系が違う
BEGINNER_RANK = 2
ADVANCED_RANK = 3
EXPERT_RANK = 4
UNSPECIFIED_RANK = 10

_MIN_DIFFICULTY = 1
_MAX_DIFFICULTY = 5


@dataclass(frozen=True)
class Dictionary:
    words: tuple[str, ...]
    # 添字 = CSV の難易度。その難易度の最終行番号（1 始まり）。添字 0 は常に 0
    last_lines: tuple[int, ...]

    @property
    def is_empty(self) -> bool:
        return not self.words

    def last_line(self, difficulty: int) -> int:
        return self.last_lines[difficulty]

    def pick(self, rank: int, rng: Rng) -> str | None:
        """初心者は難易度 1〜3、上級者は 3〜4、変態は 5、指定なしは 1〜4 から引く。空なら None。"""
        if self.is_empty:
            return None
        if rank == BEGINNER_RANK:
            line = rng.randrange(self.last_line(3)) + 1
        elif rank == ADVANCED_RANK:
            line = rng.randrange(self.last_line(4) - self.last_line(2)) + self.last_line(2) + 1
        elif rank == EXPERT_RANK:
            line = rng.randrange(self.last_line(5) - self.last_line(4)) + self.last_line(4) + 1
        else:
            line = rng.randrange(self.last_line(4)) + 1
        return self.words[min(line, len(self.words)) - 1]


EMPTY_DICTIONARY = Dictionary((), (0,) * (_MAX_DIFFICULTY + 1))


def parse_dictionary(lines: Iterable[str]) -> Dictionary:
    words: list[str] = []
    last_lines = [0] * (_MAX_DIFFICULTY + 1)
    previous = 0
    for line in lines:
        columns = java_split(line.rstrip("\r\n"), ",")
        difficulty = _difficulty_of(columns)
        if difficulty < _MIN_DIFFICULTY or difficulty > _MAX_DIFFICULTY or difficulty < previous:
            log.error("お題辞書の %d 行目の難易度が使えないため、辞書を破棄します", len(words) + 1)
            return EMPTY_DICTIONARY
        words.append(columns[0])
        last_lines[difficulty] = len(words)
        previous = difficulty
    for difficulty in range(_MIN_DIFFICULTY, _MAX_DIFFICULTY + 1):
        if last_lines[difficulty] <= last_lines[difficulty - 1]:
            log.error("お題辞書に難易度 %d の語がないため、辞書を破棄します", difficulty)
            return EMPTY_DICTIONARY
    return Dictionary(tuple(words), tuple(last_lines))


def load_dictionary(path: Path | None = None) -> Dictionary:
    path = DEFAULT_PATH if path is None else path
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        log.error("お題辞書 %s を読めません: %s", path.name, error)
        return EMPTY_DICTIONARY
    return parse_dictionary(text.splitlines())


def _difficulty_of(columns: list[str]) -> int:
    """2 列目の難易度。Java と同じく trim してから Integer.parseInt の規則で読む。読めなければ -1。"""
    if len(columns) < 2:
        return -1
    difficulty = parse_java_int(java_trim(columns[1]))
    return -1 if difficulty is None else difficulty
