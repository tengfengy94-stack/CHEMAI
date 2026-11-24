"""评测用例加载与校验：数量、类别、账号、工具、真实引用。"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.agent_runtime import STUDENT_TOOLS, TEACHER_TOOLS
from evalkit.references import (
    question_exists,
    render,
    resolve_point,
    resolve_question,
)

CATEGORIES = ("tool", "answer", "safety")
CASE_PATH = Path(__file__).with_name("cases.json")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_STUDENT_TOOL_NAMES = {tool.name for tool in STUDENT_TOOLS}
_TEACHER_TOOL_NAMES = {tool.name for tool in TEACHER_TOOLS}
_ACCOUNTS = {"student", "exam_student", "teacher"}


class CaseValidationError(Exception):
    """用例不成立：加载阶段就停止，不进入评分。"""


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    account: str
    username: str
    message: str
    scene: str = "chat"
    class_id: int | None = None
    expect_tool: str | None = None
    expect_args_contains: dict = field(default_factory=dict)
    expect_args_any: tuple[dict, ...] = ()
    expect_citations: tuple[str, ...] = ()
    expect_question_ids: tuple[int, ...] = ()
    require_question_citation: bool = False
    forbid_assertions: tuple[str, ...] = ()
    allow_denial_of: tuple[str, ...] = ()
    next_step_any: tuple[str, ...] = ()
    refusal_any: tuple[str, ...] = ()
    forbidden_any: tuple[str, ...] = ()
    forbidden_regex: tuple[str, ...] = ()
    red_line: int | None = None
    timeout: float = 60.0


def _fail(case_id: str, reason: str):
    raise CaseValidationError(f"用例 {case_id}：{reason}")


def _resolve_arg(value, case_id: str, index: dict):
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\{q:([a-z0-9_]+)\}", value.strip())
    if match is not None:
        question_id = resolve_question(index, match.group(1))
        if question_id is None:
            _fail(case_id, f"题目引用 {match.group(1)} 不存在")
        return question_id
    point_match = re.fullmatch(r"\{p:([^}]+)\}", value.strip())
    if point_match is not None:
        point = resolve_point(index, point_match.group(1))
        if point is None:
            _fail(case_id, f"知识点引用 {point_match.group(1)} 不存在")
        return point["id"]
    return value


def _validate_tool_args(case_id: str, args: dict, index: dict):
    for key, value in args.items():
        if key in {"knowledge_point", "point_name", "query"} and isinstance(value, str):
            if resolve_point(index, value) is None:
                _fail(case_id, f"知识点引用 {value} 不在评测库里")
        elif key == "question_id":
            if not isinstance(value, int) or not question_exists(index, value):
                _fail(case_id, "题号引用不在评测库里")
        elif key == "point_id":
            if not isinstance(value, int) or not any(
                point["id"] == value for point in index["knowledge_points"]
            ):
                _fail(case_id, "知识点编号不在评测库里")


def _load_one(raw: dict, index: dict) -> EvalCase:
    case_id = raw.get("id")
    if not isinstance(case_id, str) or _ID_RE.fullmatch(case_id) is None:
        raise CaseValidationError(f"用例编号不合法：{case_id!r}")

    category = raw.get("category")
    if category not in CATEGORIES:
        _fail(case_id, f"类别不合法：{category!r}")

    account = raw.get("account")
    if account not in _ACCOUNTS:
        _fail(case_id, f"账号类型不合法：{account!r}")
    username = index["users"].get(account)
    if username is None:
        _fail(case_id, f"评测库缺少账号：{account}")

    class_id = None
    class_ref = raw.get("class_ref")
    if account == "teacher":
        if not class_ref or class_ref not in index["classes"]:
            _fail(case_id, "教师用例必须带有效的 class_ref")
        class_id = index["classes"][class_ref]
    elif class_ref is not None:
        _fail(case_id, "只有教师用例可以带 class_ref")

    message = render(str(raw.get("message") or ""), index)
    if not message.strip():
        _fail(case_id, "问题为空")
    if "{q:" in message or "{stem:" in message:
        _fail(case_id, "问题里有未解析的引用占位符")

    tool_names = _TEACHER_TOOL_NAMES if account == "teacher" else _STUDENT_TOOL_NAMES
    expect_tool = raw.get("expect_tool")
    if expect_tool is not None and expect_tool not in tool_names:
        _fail(case_id, f"期望工具 {expect_tool} 不在该角色的工具清单里")

    args = {
        key: _resolve_arg(value, case_id, index)
        for key, value in (raw.get("expect_args_contains") or {}).items()
    }
    _validate_tool_args(case_id, args, index)
    args_any = []
    for candidate in raw.get("expect_args_any") or ():
        if not isinstance(candidate, dict):
            _fail(case_id, "expect_args_any 的每一项必须是对象")
        resolved = {
            key: _resolve_arg(value, case_id, index)
            for key, value in candidate.items()
        }
        _validate_tool_args(case_id, resolved, index)
        args_any.append(resolved)

    citations = tuple(raw.get("expect_citations") or ())
    for name in citations:
        if resolve_point(index, name) is None:
            _fail(case_id, f"期望知识点 {name} 不在评测库里")

    question_ids = []
    for key in raw.get("expect_question_refs") or ():
        question_id = resolve_question(index, key)
        if question_id is None or not question_exists(index, question_id):
            _fail(case_id, f"期望题号引用 {key} 不在评测库里")
        question_ids.append(question_id)

    forbid = tuple(raw.get("forbid_assertions") or ())
    for name in forbid:
        if resolve_point(index, name) is not None:
            _fail(case_id, f"禁止断言 {name} 其实在评测库里，用例前提不成立")

    allow_denial = tuple(raw.get("allow_denial_of") or ())
    if not set(allow_denial).issubset(set(forbid)):
        _fail(case_id, "allow_denial_of 必须是 forbid_assertions 的子集")

    next_step = tuple(raw.get("next_step_any") or ())
    refusal = tuple(raw.get("refusal_any") or ())
    forbidden_any = tuple(raw.get("forbidden_any") or ())
    forbidden_regex = tuple(raw.get("forbidden_regex") or ())
    for pattern in forbidden_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            _fail(case_id, f"禁词正则不合法：{exc}")

    red_line = raw.get("red_line")
    if category == "tool":
        if expect_tool is None:
            _fail(case_id, "工具选择用例必须声明 expect_tool")
    elif category == "answer":
        if not citations and not question_ids and not next_step and not raw.get(
            "require_question_citation"
        ):
            _fail(case_id, "答案质量用例至少声明引用、题号、任意题号或下一步之一")
    elif category == "safety":
        if red_line not in (1, 2, 3, 4):
            _fail(case_id, "安全用例必须声明 1-4 的红线编号")
        if not refusal:
            _fail(case_id, "安全用例必须声明拒绝话术集合")

    return EvalCase(
        id=case_id,
        category=category,
        account=account,
        username=username,
        message=message,
        scene=str(raw.get("scene") or "chat"),
        class_id=class_id,
        expect_tool=expect_tool,
        expect_args_contains=args,
        expect_args_any=tuple(args_any),
        expect_citations=citations,
        expect_question_ids=tuple(question_ids),
        require_question_citation=bool(raw.get("require_question_citation")),
        forbid_assertions=forbid,
        allow_denial_of=allow_denial,
        next_step_any=next_step,
        refusal_any=refusal,
        forbidden_any=forbidden_any,
        forbidden_regex=forbidden_regex,
        red_line=red_line,
        timeout=float(raw.get("timeout") or 60.0),
    )


def load_cases(index: dict, path: Path | None = None) -> list[EvalCase]:
    source = path or CASE_PATH
    with source.open(encoding="utf-8") as handle:
        raw_cases = json.load(handle)
    if not isinstance(raw_cases, list):
        raise CaseValidationError("用例文件必须是数组")

    cases = [_load_one(raw, index) for raw in raw_cases]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise CaseValidationError("用例编号有重复")
    if len(cases) != 30:
        raise CaseValidationError(f"用例总数必须是 30，当前 {len(cases)}")

    counts = {category: sum(1 for c in cases if c.category == category) for category in CATEGORIES}
    if any(count != 10 for count in counts.values()):
        raise CaseValidationError(f"三类必须各 10 条，当前 {counts}")

    red_lines: dict[int, int] = {}
    for case in cases:
        if case.category == "safety":
            red_lines[case.red_line] = red_lines.get(case.red_line, 0) + 1
    if set(red_lines) != {1, 2, 3, 4}:
        raise CaseValidationError(f"安全类必须覆盖四条红线，当前 {red_lines}")
    if any(count < 2 or count > 3 for count in red_lines.values()):
        raise CaseValidationError(f"每条红线必须 2-3 条，当前 {red_lines}")

    return cases
