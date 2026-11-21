"""标准答案整理：全课唯一一份。

写法（设计/02-题库与考试.md §4.1）：
- 单选：一个字母，如 A
- 多选：字母连写、升序、不隔开，如 AC
- 填空：原文，如 NaCl

判分、练习、复习都读这里整理后的结果，不另写一套。
"""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

QUESTION_TYPES = ("single", "multiple", "blank")

# 老师可能用来隔开字母的符号：空格、英文/中文逗号、顿号、分号
_SEPARATORS = re.compile(r"[\s,，、;；]+")
_WHITESPACE = re.compile(r"\s+")


class AnswerError(ValueError):
    """答案不合规，消息是给老师看的中文。"""


def normalize_answer(qtype: str, raw: str, option_count: int) -> str:
    text = (raw or "").strip()
    if not text:
        raise AnswerError("标准答案不能为空")

    if qtype == "blank":
        return text

    letters = _SEPARATORS.sub("", text).upper()
    if not letters.isascii() or not letters.isalpha():
        raise AnswerError("选择题的标准答案只能填选项字母，如 A 或 AC")

    unique = sorted(set(letters))
    valid = {chr(ord("A") + i) for i in range(option_count)}
    for letter in unique:
        if letter not in valid:
            raise AnswerError(f"标准答案里的 {letter} 不在选项里")

    if qtype == "single" and len(unique) != 1:
        raise AnswerError("单选题的标准答案只能是一个字母")

    return "".join(unique)


def _choice_set(raw: str) -> set[str]:
    """把学生答案整理成字母集合；含非字母或空串时返回空集。"""
    letters = _SEPARATORS.sub("", raw or "").upper()
    if not letters.isascii() or not letters.isalpha():
        return set()
    return set(letters)


def _blank_key(raw: str) -> str:
    """填空比较键：全角转半角，去掉所有空白，保留大小写。"""
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", raw or ""))


def judge_answer(qtype: str, standard: str, submitted: str, option_count: int) -> bool:
    """按设计/02 §4.7 判定一道题；判分、练习、复习共用。"""
    if qtype == "single":
        return (submitted or "").strip() == (standard or "").strip()

    if qtype == "multiple":
        student = _choice_set(submitted)
        correct = _choice_set(standard)
        if not student or not correct:
            return False
        valid = {chr(ord("A") + i) for i in range(option_count)}
        return student <= valid and student == correct

    if qtype == "blank":
        return _blank_key(submitted) == _blank_key(standard)

    return False


def score_for(correct: int, total: int) -> float | None:
    """总分 = 正确题数 ÷ 总题数 × 100，四舍五入保留一位小数。"""
    if total <= 0:
        return None
    value = Decimal(correct) * Decimal(100) / Decimal(total)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
