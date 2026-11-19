"""答案整理：全课唯一一份，判分、练习、复习都读它整理后的结果。"""
import pytest

from app.answers import AnswerError, normalize_answer


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("A", "A"),
        ("a", "A"),
        (" b ", "B"),
        ("C,A", "AC"),
        ("ac", "AC"),
        ("A A", "A"),
        ("c，a、b", "ABC"),
        ("BA", "AB"),
    ],
)
def test_choice_answers_are_uppercased_deduplicated_and_sorted(raw, expected):
    qtype = "single" if len(expected) == 1 else "multiple"
    assert normalize_answer(qtype, raw, option_count=4) == expected


def test_blank_answer_keeps_original_text_without_outer_spaces():
    assert normalize_answer("blank", "  3Fe + 2O2 → Fe3O4 ", option_count=0) == "3Fe + 2O2 → Fe3O4"


def test_blank_answer_keeps_case():
    assert normalize_answer("blank", "NaCl", option_count=0) == "NaCl"


@pytest.mark.parametrize(
    "qtype, raw, option_count, message",
    [
        ("single", "", 4, "标准答案不能为空"),
        ("blank", "   ", 0, "标准答案不能为空"),
        ("single", "AB", 4, "单选题的标准答案只能是一个字母"),
        ("single", "D", 3, "标准答案里的 D 不在选项里"),
        ("multiple", "AE", 4, "标准答案里的 E 不在选项里"),
        ("multiple", "A1", 4, "选择题的标准答案只能填选项字母"),
    ],
)
def test_invalid_answers_are_rejected_with_reason(qtype, raw, option_count, message):
    with pytest.raises(AnswerError, match=message):
        normalize_answer(qtype, raw, option_count=option_count)
