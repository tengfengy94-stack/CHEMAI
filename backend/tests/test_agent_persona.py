"""第 13 章：人设上下文与提示。"""
from sqlalchemy import select

from app import clock
from app.agent_context import ChatContext, build_system_prompt
from app.agent_routes import _build_context
from app.models import PracticeRecord, Question, User


def _user(client, username):
    with client.app.state.session_factory() as session:
        return session.scalar(select(User).where(User.username == username))


def _context(role="student", scene="practice", wrong=0):
    return ChatContext(
        user_id=1,
        role=role,
        class_id=None,
        scene=scene,
        exam_in_progress=False,
        session_factory=lambda: None,
        consecutive_wrong=wrong,
    )


def _add_practice(client, username, *results):
    """给指定学生追加练习记录，按传入顺序写入。"""
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.username == username))
        question = Question(
            stem="测试题",
            type="single",
            options=["A", "B"],
            answer="A",
            explanation=None,
            difficulty=2,
            status="approved",
            created_by="t1",
        )
        session.add(question)
        session.flush()
        for is_correct in results:
            session.add(
                PracticeRecord(
                    student_id=user.id,
                    question_id=question.id,
                    difficulty=2,
                    is_correct=is_correct,
                    created_at=clock.utcnow(),
                )
            )
        session.commit()


def test_build_context_reads_consecutive_wrong(client, make_user):
    make_user("s1", role="student", name="学生一")
    _add_practice(client, "s1", False, False, False)

    context = _build_context(client.app, _user(client, "s1"), "practice", None)

    assert context.consecutive_wrong == 3


def test_build_context_teacher_and_admin_have_zero(client, make_user):
    make_user("s1", role="student", name="学生一")
    make_user("t1", role="teacher")
    make_user("admin", role="admin")
    _add_practice(client, "s1", False, False, False)

    for username in ("t1", "admin"):
        context = _build_context(client.app, _user(client, username), "chat", None)
        assert context.consecutive_wrong == 0


def test_build_context_name_scope(client, make_user, make_class):
    make_user("t1", role="teacher")
    make_user("t2", role="teacher")
    first = make_class("一班", "t1")
    second = make_class("二班", "t2")
    make_user("s1", role="student", name="学生一", class_id=first)
    make_user("s2", role="student", name="学生二", class_id=first)
    make_user("s3", role="student", name="学生三", class_id=second)
    make_user("admin", role="admin")

    student = _build_context(client.app, _user(client, "s1"), "chat", None)
    assert {"学生一", "s1"} <= set(student.visible_names)
    assert "学生二" in student.forbidden_names
    assert "学生三" not in student.forbidden_names

    teacher = _build_context(client.app, _user(client, "t1"), "chat", first)
    assert {"学生一", "学生二"} <= set(teacher.visible_names)
    assert "学生三" in teacher.forbidden_names

    admin = _build_context(client.app, _user(client, "admin"), "chat", None)
    assert admin.visible_names == ()
    assert admin.forbidden_names == ()


def test_encouragement_not_added_below_threshold():
    prompt = build_system_prompt(_context(wrong=2))

    assert "连续答错" not in prompt


def test_encouragement_added_at_threshold_and_keeps_scene_rule():
    prompt = build_system_prompt(_context(scene="practice", wrong=3))

    assert "连续答错了 3 次" in prompt
    assert "不要直接说出选项或最终答案" in prompt
    assert (
        prompt.index("现在是练习场景")
        < prompt.index("连续答错了 3 次")
        < prompt.index("四条红线")
    )


def test_chat_prompt_routes_why_wrong_to_explain_tool():
    prompt = build_system_prompt(_context(scene="chat"))

    assert "为什么错" in prompt
    assert "讲错题" in prompt
    assert "错因" in prompt
    assert "同类题" in prompt


def test_prompt_covers_student_insults():
    prompt = build_system_prompt(_context())

    assert "不跟着对骂" in prompt
    assert "继续当前" in prompt


def test_teacher_and_admin_never_get_encouragement():
    teacher = build_system_prompt(_context(role="teacher", wrong=3))
    admin = build_system_prompt(_context(role="admin", wrong=3))

    assert "连续答错" not in teacher
    assert "不出现鼓励" in teacher
    assert "连续答错" not in admin
