"""第 13 章：四条红线的规则检查。"""
from app.agent_context import ChatContext
from app.agent_guard import REPLACEMENTS, OutputGuard, scan


def _context(*, role="student", exam=False, visible=(), forbidden=()):
    return ChatContext(
        user_id=1,
        role=role,
        class_id=None,
        scene="chat",
        exam_in_progress=exam,
        session_factory=lambda: None,
        visible_names=tuple(visible),
        forbidden_names=tuple(forbidden),
    )


def test_exam_answer_hits_only_during_exam():
    text = "这道题选 A，第一步先配平。"
    hit = scan(text, _context(exam=True))

    assert hit is not None and hit.red_line == 1
    assert hit.replacement == REPLACEMENTS[1]
    assert scan(text, _context(exam=False)) is None


def test_other_student_score_hits():
    hit = scan("张三这次考了 95 分。", _context(visible=("学生一", "s1")))

    assert hit is not None and hit.red_line == 2


def test_forbidden_classmate_name_hits():
    hit = scan("学生二最近进步很大。", _context(forbidden=("学生二",)))

    assert hit is not None and hit.red_line == 2


def test_username_substring_in_chemistry_text_does_not_false_positive():
    assert scan("电子排布是 2s2 2p6。", _context(forbidden=("s2",))) is None


def test_score_pattern_ignores_time_and_exam_phrases():
    for text in (
        "上次考了 95 分。",
        "第一题考了 95 分。",
        "最近考了 95 分。",
        "考试考了 95 分。",
    ):
        assert scan(text, _context(visible=("学生一",))) is None


def test_same_name_in_visible_and_forbidden_is_not_blocked():
    hit = scan(
        "王小雨这次考了 95 分。",
        _context(visible=("王小雨",), forbidden=("王小雨",)),
    )

    assert hit is None


def test_exam_prose_solution_is_blocked():
    hit = scan("先看氧化剂，再配平，最后让得失电子守恒。", _context(exam=True))

    assert hit is not None and hit.red_line == 1


def test_exam_option_phrase_is_blocked():
    hit = scan("选项 B 更合适。", _context(exam=True))

    assert hit is not None and hit.red_line == 1


def test_exam_refusal_is_not_blocked():
    assert (
        scan(
            "这道题我不能替你做。考完把卷子拿来，我们一道一道看。",
            _context(exam=True),
        )
        is None
    )


def test_dangerous_replacement_matches_operation():
    taste = scan("你可以品尝一下这种试剂。", _context())
    assert taste is not None and taste.red_line == 3
    assert "扇闻" not in taste.replacement
    assert "尝" in taste.replacement

    heat = scan("用明火加热试管。", _context())
    assert heat is not None and heat.red_line == 3
    assert "扇闻" not in heat.replacement
    assert "加热" in heat.replacement

    smell = scan("你可以直接闻一下氯气。", _context())
    assert smell is not None and smell.red_line == 3
    assert "扇闻" in smell.replacement


def test_visible_name_score_passes():
    hit = scan(
        "学生一这次考了 95 分。",
        _context(visible=("学生一",), forbidden=("学生二",)),
    )

    assert hit is None


def test_dangerous_operation_hits():
    hit = scan("你可以直接闻一下氯气，观察气味。", _context())

    assert hit is not None and hit.red_line == 3


def test_knowledge_and_safe_advice_pass():
    assert scan("氯气为什么有毒？因为它会刺激呼吸道。", _context()) is None
    assert scan("正确做法是扇闻：用手轻轻扇动。", _context()) is None
    assert scan("不要直接闻氯气，要扇闻。", _context()) is None


def test_insult_hits():
    hit = scan("这么简单都不会，先看课本吧。", _context())

    assert hit is not None and hit.red_line == 4


def test_priority_exam_before_insult():
    hit = scan("答案是 A，这么简单都不会。", _context(exam=True))

    assert hit is not None and hit.red_line == 1


def test_safe_practice_answer_passes():
    assert scan("你最近连续答错了 3 次，我们先从基础题开始。", _context()) is None


def test_output_guard_streams_safe_sentences():
    guard = OutputGuard(_context())

    assert guard.feed("第一句安全。第二句也安全。") == [
        "第一句安全。",
        "第二句也安全。",
    ]


def test_output_guard_flushes_partial_sentence():
    guard = OutputGuard(_context())

    assert guard.feed("还没说完") == []
    assert guard.flush() == ["还没说完"]


def test_output_guard_stops_at_second_sentence():
    guard = OutputGuard(_context())

    assert guard.feed("第一句安全。这么简单都不会。后面也不发。") == [
        "第一句安全。",
        REPLACEMENTS[4],
    ]
    assert guard.tripped
    assert guard.feed("后面也不发。") == []
    assert guard.flush() == []


def test_output_guard_replacement_only_once():
    guard = OutputGuard(_context())

    assert guard.feed("这么简单都不会。") == [REPLACEMENTS[4]]
    assert guard.feed("下一句。") == []
    assert guard.flush() == []


def test_output_guard_flush_catches_partial_violation():
    guard = OutputGuard(_context())

    assert guard.feed("这么简单都不会") == []
    assert guard.flush() == [REPLACEMENTS[4]]


def test_output_guard_splits_long_text_without_punctuation():
    guard = OutputGuard(_context())

    chunks = guard.feed("安" * 200)

    assert len(chunks) == 1 and len(chunks[0]) == 160
    assert guard.flush() == ["安" * 40]
