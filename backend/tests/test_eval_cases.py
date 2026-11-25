"""用例加载：三十条、三类覆盖、教师账号、真实引用、非法用例拒绝。"""
import json

import pytest

from evalkit.cases import CASE_PATH, CaseValidationError, load_cases
from evalkit.db import build_eval_database
from evalkit.judge import FAILURE_CASE_INVALID, FAILURE_TYPES
from evalkit.references import build_reference_index, resolve_point


@pytest.fixture(scope="module")
def eval_index(tmp_path_factory):
    path = tmp_path_factory.mktemp("eval-cases") / "eval.db"
    fixture = build_eval_database(path)
    return build_reference_index(fixture)


def _raw_cases():
    return json.loads(CASE_PATH.read_text(encoding="utf-8"))


def _write_cases(tmp_path, cases):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return path


def test_loads_thirty_cases(eval_index):
    cases = load_cases(eval_index)
    assert len(cases) == 30
    assert sum(1 for c in cases if c.category == "tool") == 10
    assert sum(1 for c in cases if c.category == "answer") == 10
    assert sum(1 for c in cases if c.category == "safety") == 10


def test_tool_cases_cover_student_tools_and_teacher(eval_index):
    cases = load_cases(eval_index)
    tool_cases = [c for c in cases if c.category == "tool"]
    student_tools = {c.expect_tool for c in tool_cases if c.account != "teacher"}
    assert student_tools == {
        "search_questions",
        "find_knowledge_point",
        "student_profile",
        "knowledge_map",
        "explain_wrong_question",
        "due_reviews",
        "assign_practice",
        "add_review",
        "exam_result",
    }
    teacher_case = next(c for c in tool_cases if c.account == "teacher")
    assert teacher_case.expect_tool == "class_overview"
    assert teacher_case.class_id is not None


def test_question_placeholders_are_resolved(eval_index):
    cases = load_cases(eval_index)
    explain = next(c for c in cases if c.id == "tool_explain_wrong_question")
    assert explain.expect_args_contains["question_id"] == eval_index["question_refs"]["redox_wrong"]
    assert "{" not in explain.message


def test_knowledge_map_accepts_name_or_id(eval_index):
    case = next(c for c in load_cases(eval_index) if c.id == "tool_knowledge_map")
    assert case.expect_args_any[0] == {"point_name": "氧化剂"}
    assert case.expect_args_any[1] == {
        "point_id": resolve_point(eval_index, "氧化剂")["id"]
    }


def test_all_citations_exist(eval_index):
    for case in load_cases(eval_index):
        for name in case.expect_citations:
            assert resolve_point(eval_index, name) is not None


def test_rejects_wrong_total(eval_index, tmp_path):
    raw = _raw_cases()[:-1]
    with pytest.raises(CaseValidationError, match="30"):
        load_cases(eval_index, _write_cases(tmp_path, raw))


def test_rejects_wrong_category(eval_index, tmp_path):
    raw = _raw_cases()
    raw[0]["category"] = "quality"
    with pytest.raises(CaseValidationError, match="类别不合法"):
        load_cases(eval_index, _write_cases(tmp_path, raw))


def test_rejects_fabricated_citation(eval_index, tmp_path):
    raw = _raw_cases()
    answer = next(c for c in raw if c["category"] == "answer")
    answer["expect_citations"] = ["库外编造点"]
    with pytest.raises(CaseValidationError, match="不在评测库里"):
        load_cases(eval_index, _write_cases(tmp_path, raw))


def test_rejects_teacher_without_class(eval_index, tmp_path):
    raw = _raw_cases()
    teacher = next(c for c in raw if c.get("account") == "teacher")
    teacher.pop("class_ref")
    with pytest.raises(CaseValidationError, match="class_ref"):
        load_cases(eval_index, _write_cases(tmp_path, raw))


def test_failure_taxonomy_has_four_classes():
    assert len(FAILURE_TYPES) == 4
    assert FAILURE_CASE_INVALID in FAILURE_TYPES
