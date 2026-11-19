"""标准答案整理：全课唯一一份。

写法（设计/02-题库与考试.md §4.1）：
- 单选：一个字母，如 A
- 多选：字母连写、升序、不隔开，如 AC
- 填空：原文，如 NaCl

判分、练习、复习都读这里整理后的结果，不另写一套。
"""
import re

QUESTION_TYPES = ("single", "multiple", "blank")

# 老师可能用来隔开字母的符号：空格、英文/中文逗号、顿号、分号
_SEPARATORS = re.compile(r"[\s,，、;；]+")


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
