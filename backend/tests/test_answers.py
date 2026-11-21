"""答案整理：全课唯一一份，判分、练习、复习都读它整理后的结果。"""
import pytest

from app.answers import AnswerError, judge_answer, normalize_answer, score_for


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


@pytest.mark.parametrize(
    "qtype, standard, submitted, option_count, expected",
    [
        ("single", "A", " A ", 3, True),
        ("single", "A", "a", 3, False),
        ("single", "A", "", 3, False),
        ("multiple", "AC", "CA", 3, True),
        ("multiple", "AC", "a c", 3, True),
        ("multiple", "AC", "A", 3, False),
        ("multiple", "AB", "ABC", 3, False),
        ("multiple", "AC", "D", 3, False),
        ("multiple", "AC", "", 3, False),
        ("blank", "NaCl", "Ｎａ Ｃｌ", 0, True),
        ("blank", "NaCl", "Na Cl", 0, True),
        ("blank", "CO", "Co", 0, False),
        ("blank", "NaCl", "", 0, False),
    ],
)
def test_judge_answer_follows_design_rules(qtype, standard, submitted, option_count, expected):
    assert judge_answer(qtype, standard, submitted, option_count) is expected


@pytest.mark.parametrize(
    "correct, total, expected",
    [
        (3, 3, 100.0),
        (2, 3, 66.7),
        (9, 12, 75.0),
        (0, 3, 0.0),
        (1, 16, 6.3),
        (0, 0, None),
    ],
)
def test_score_is_rounded_half_up_to_one_decimal(correct, total, expected):
    assert score_for(correct, total) == expected
