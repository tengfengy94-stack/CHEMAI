"""Agent 只读工具：搜题、知识点、学生画像、知识地图、讲错题。

工具只调用 service，不 import 路由层；身份从 ChatContext 读，参数里没有学生/班级编号。
"""
from typing import Annotated

from langchain.tools import ToolRuntime, tool
from sqlalchemy import func, select

from app import attempts, class_reporting, knowledge, practice, reporting, review
from app.agent_context import ChatContext
from app.auth import require_own_class
from app.models import (
    AnswerRecord,
    KnowledgePoint,
    Paper,
    Question,
    QuestionKnowledgePoint,
    User,
)
from app.question_search import build_question_query
from app.schemas import question_pool_to_dict


def _session(runtime: ToolRuntime[ChatContext]):
    return runtime.context.session_factory()


def _current_user(session, runtime: ToolRuntime[ChatContext]) -> User | None:
    return session.get(User, runtime.context.user_id)


def _refuse(message: str) -> dict:
    return {"found": False, "message": message}


def _clamp_limit(limit: int, default: int = 5) -> int:
    return max(1, min(int(limit or default), 20))


@tool
def search_questions(
    runtime: ToolRuntime[ChatContext],
    knowledge_point: Annotated[str | None, "知识点名称，可省略"] = None,
    difficulty: Annotated[int | None, "难度 1、2、3，可省略"] = None,
    limit: Annotated[int, "返回条数，默认 5，最多 20"] = 5,
) -> dict:
    """何时用：学生想搜题、想看题库里有没有某类题。
    会发生什么：只在已通过题里按知识点、难度、数量筛，返回题号、题干、题型、难度，不带答案解析。
    下一步：把题号告诉学生，让学生去练习页做。
    不适用：学生要你按弱项布置一组练习时用布置练习；问“这道题为什么错”用讲错题；老师组卷是题库页的事。
    """
    if difficulty is not None and difficulty not in (1, 2, 3):
        return _refuse("参数不合法：难度只能是 1、2、3")
    with _session(runtime) as session:
        user = _current_user(session, runtime)
        if user is None:
            return _refuse("没找到当前用户")

        point_id = None
        point_name = None
        if knowledge_point:
            found = knowledge.find_point(session, knowledge_point)
            if found is None:
                return _refuse("没找到这个知识点")
            point_id = found["id"]
            point_name = found["name"]

        stmt = build_question_query(user, difficulty=difficulty, status="approved")
        if point_id is not None:
            stmt = stmt.join(
                QuestionKnowledgePoint,
                QuestionKnowledgePoint.question_id == Question.id,
            ).where(QuestionKnowledgePoint.knowledge_point_id == point_id)

        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = session.scalars(
            stmt.order_by(Question.id).limit(_clamp_limit(limit))
        ).all()
        return {
            "found": True,
            "knowledge_point": point_name,
            "total": int(total),
            "remaining": max(0, int(total) - len(rows)),
            "questions": [question_pool_to_dict(question) for question in rows],
        }


@tool
def find_knowledge_point(
    runtime: ToolRuntime[ChatContext],
    query: Annotated[str, "学生说的知识点名称或别名"],
) -> dict:
    """何时用：学生问某个知识点是什么、在不在知识点库里，或说的名字和库里的写法对不上。
    会发生什么：按名称和别名匹配，返回最接近的一个知识点；匹配不到就说匹配不到。
    下一步：拿到正式名称后，再去搜题、看弱项或看知识地图。
    不适用：问两个知识点的关系，要用看知识地图；要一组练习题用布置练习。
    """
    with _session(runtime) as session:
        found = knowledge.find_point(session, query)
        if found is None:
            return _refuse("没找到这个知识点")
        return {"found": True, "point": found}


@tool
def student_profile(runtime: ToolRuntime[ChatContext]) -> dict:
    """何时用：学生问“我最近学得怎么样”“我哪块弱”“还有多少要复习”。
    会发生什么：现查当前学生的弱项前三、最近五次分数和待复习数。
    下一步：挑最弱的一个点，问学生要不要练几道或看错题。
    不适用：老师查班级要用看班级概况；查别人的画像一律不给。
    """
    if runtime.context.role != "student":
        return _refuse("只有学生可以查看自己的画像")
    with _session(runtime) as session:
        report = reporting.student_report(session, runtime.context.user_id)
        return {
            "found": True,
            "has_data": report["has_data"],
            "weak_items": report["items"],
            "recent_scores": report["recent_scores"],
            "review_due_count": report["review_due_count"],
        }


@tool
def knowledge_map(
    runtime: ToolRuntime[ChatContext],
    point_name: Annotated[str | None, "知识点名称，可省略"] = None,
    point_id: Annotated[int | None, "知识点编号，可省略"] = None,
) -> dict:
    """何时用：学生问“学这个之前要先会什么”“这个点属于哪一块”。
    会发生什么：只返回目标知识点的上级和下级名称，不返回整棵树。
    下一步：如果上级范围正好是弱项，建议先补上一层的题。
    不适用：搜题、查弱项排名，都不是它的事。
    """
    if point_id is None and not point_name:
        return _refuse("参数不合法：需要知识点名称或编号")
    with _session(runtime) as session:
        point = session.get(KnowledgePoint, point_id) if point_id is not None else None
        if point is None and point_name:
            found = knowledge.find_point(session, point_name)
            if found is not None:
                point = session.get(KnowledgePoint, found["id"])
        if point is None:
            return _refuse("没找到这个知识点")

        parent = session.get(KnowledgePoint, point.parent_id) if point.parent_id else None
        children = session.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.parent_id == point.id)
            .order_by(KnowledgePoint.id)
        ).all()
        shown = children[:20]
        return {
            "found": True,
            "id": point.id,
            "name": point.name,
            "parent": parent.name if parent else None,
            "children": [child.name for child in shown],
            "remaining_children": max(0, len(children) - len(shown)),
        }


@tool
def explain_wrong_question(
    runtime: ToolRuntime[ChatContext],
    question_id: Annotated[int | None, "题目编号，可省略"] = None,
    question_stem: Annotated[str | None, "题干关键词，可省略"] = None,
) -> dict:
    """何时用：学生问“这道题为什么错”“我选 A 为什么不对”。
    会发生什么：读当前学生最近一次错误答案、题干、选项、标准答案和解析，并给一道同类题。
    下一步：问学生要不要做同类题，或把原题加入复习。
    不适用：学生只是要把题加入复习，用加复习；考试进行中的题不能讲；学生没答错过的题没有错可讲。
    """
    if runtime.context.role != "student":
        return _refuse("只有学生可以讲自己的错题")
    if runtime.context.exam_in_progress:
        return _refuse("这道题我不能替你做。考完把卷子拿来，我们一道一道看")
    with _session(runtime) as session:
        user = _current_user(session, runtime)
        if user is None:
            return _refuse("没找到当前用户")
        rows = session.execute(attempts.wrong_questions_query(user)).mappings().all()
        row = None
        for candidate in rows:
            if question_id is not None and candidate["question_id"] != question_id:
                continue
            if question_stem and question_stem not in (candidate["stem"] or ""):
                continue
            row = candidate
            break
        if row is None:
            return _refuse("没找到这道题的错题记录")

        similar = None
        point_id = session.scalar(
            select(QuestionKnowledgePoint.knowledge_point_id)
            .where(QuestionKnowledgePoint.question_id == row["question_id"])
            .order_by(QuestionKnowledgePoint.knowledge_point_id)
            .limit(1)
        )
        if point_id is not None:
            similar_question = session.scalar(
                select(Question)
                .join(
                    QuestionKnowledgePoint,
                    QuestionKnowledgePoint.question_id == Question.id,
                )
                .where(
                    QuestionKnowledgePoint.knowledge_point_id == point_id,
                    Question.status == "approved",
                    Question.id != row["question_id"],
                )
                .order_by(Question.id)
                .limit(1)
            )
            if similar_question is not None:
                similar = question_pool_to_dict(similar_question)

        return {
            "found": True,
            "question": {
                "id": row["question_id"],
                "stem": row["stem"],
                "type": row["type"],
                "options": row["options"],
                "student_answer": row["student_answer"],
                "answer": row["answer"],
                "explanation": row["explanation"],
                "paper_title": row["paper_title"],
            },
            "similar": similar,
        }


@tool
def due_reviews(
    runtime: ToolRuntime[ChatContext],
    limit: Annotated[int, "返回条数，默认 5，最多 20"] = 5,
) -> dict:
    """何时用：学生问“今天要复习什么”“还有多少没复习”。
    会发生什么：按到期时间取前几条，逾期排在最前，并返回剩余条数。
    下一步：引导学生去复习页，或问要不要从第一道开始。
    不适用：手动加任务要用加复习；查历史复习记录不给。
    """
    if runtime.context.role != "student":
        return _refuse("只有学生可以查看自己的复习任务")
    with _session(runtime) as session:
        total = review.due_task_count(session, runtime.context.user_id)
        rows = review.list_tasks(
            session, scope="due", student_id=runtime.context.user_id
        )
        shown = rows[: _clamp_limit(limit)]
        return {
            "found": True,
            "total": int(total),
            "remaining": max(0, len(rows) - len(shown)),
            "tasks": [
                review.task_to_dict(task, question) for task, question, _ in shown
            ],
        }


@tool
def assign_practice(
    runtime: ToolRuntime[ChatContext],
    count: Annotated[int, "题目数量，默认 5，最多 20"] = 5,
) -> dict:
    """何时用：学生说“给我布置几道题练”“给我出一组练习”，要按弱项选好的一组题。
    会发生什么：按弱项和当前难度选一组题，返回题号、题干、难度；不写练习记录。
    下一步：告诉学生从哪一道开始，点“去练”进练习页。
    不适用：只是搜题、看题库里有什么题，用搜题；老师给全班布置作业这一版不做。
    """
    if runtime.context.role != "student":
        return _refuse("只有学生可以布置自己的练习")
    with _session(runtime) as session:
        questions = practice.pick_questions(
            session, runtime.context.user_id, _clamp_limit(count)
        )
        if not questions:
            return _refuse("题库里还没有可练习的题")
        return {"found": True, "count": len(questions), "questions": questions}


@tool
def add_review(
    runtime: ToolRuntime[ChatContext],
    question_id: Annotated[int, "要加入复习的题目编号"],
) -> dict:
    """何时用：学生说“把第 X 题加入复习”“加入复习计划”“这道题帮我记一下，过几天再做”。
    会发生什么：直接按题号建一条第 0 级、明天到期的复习任务；已有任务只提前到期日。不要求这道题在错题记录里。
    下一步：告诉学生哪天会再出现。
    不适用：讲一道题为什么错用讲错题；改已有任务的级别不给；给别的学生加不给。
    """
    if runtime.context.role != "student":
        return _refuse("只有学生可以给自己加复习")
    with _session(runtime) as session:
        try:
            task = review.add_manual_task(
                session, runtime.context.user_id, question_id
            )
        except review.ReviewQuestionNotFound:
            return _refuse("没找到这道题")
        except review.ReviewQuestionNotApproved:
            return _refuse("这道题还没通过审核，不能加入复习")
        return {
            "found": True,
            "task": {
                "question_id": task.question_id,
                "level": task.level,
                "due_on": task.due_on.isoformat() if task.due_on else None,
            },
        }


def _trim_attempt(detail: dict) -> dict:
    questions = detail.get("questions") or []
    items = [
        {
            "position": item["position"],
            "question_id": item["id"],
            "is_correct": bool(item.get("is_correct")),
        }
        for item in questions
    ]
    wrong = [item for item in items if not item["is_correct"]]
    visible = wrong[:20] if len(items) > 20 else items
    return {
        "paper_title": detail.get("paper_title"),
        "score": detail.get("score"),
        "graded_at": detail.get("graded_at"),
        "total_questions": len(items),
        "correct_count": len(items) - len(wrong),
        "wrong_count": len(wrong),
        "questions": visible,
        "truncated": len(visible) < len(items),
        "remaining": max(0, len(items) - len(visible)),
    }


def _latest_student_attempt(session, student_id: int, class_id: int | None = None, paper_title: str | None = None):
    stmt = (
        select(AnswerRecord)
        .where(
            AnswerRecord.student_id == student_id,
            AnswerRecord.status == "graded",
        )
        .order_by(AnswerRecord.graded_at.desc(), AnswerRecord.id.desc())
        .limit(1)
    )
    if class_id is not None:
        stmt = stmt.where(AnswerRecord.class_id == class_id)
    if paper_title:
        stmt = stmt.join(Paper, Paper.id == AnswerRecord.paper_id).where(
            Paper.title.contains(paper_title)
        )
    return session.scalar(stmt)


@tool
def exam_result(
    runtime: ToolRuntime[ChatContext],
    attempt_id: Annotated[int | None, "作答记录编号，学生可省略"] = None,
    paper_title: Annotated[str | None, "卷子标题关键词，可省略"] = None,
    student_name: Annotated[str | None, "老师查学生时必填：学生姓名"] = None,
    student_username: Annotated[str | None, "同名时补充：学生用户名"] = None,
) -> dict:
    """何时用：学生问“我上次考试哪几道错了”“那次考了多少分”；老师查本班某个学生。
    会发生什么：返回总分和每题对错；老师只能查当前班级学生，学生只能查自己的。
    下一步：挑一道错题，问学生要不要看为什么错。
    不适用：看别人的成绩不给；看还没判分的卷子没有结果可给。
    """
    with _session(runtime) as session:
        user = _current_user(session, runtime)
        if user is None:
            return _refuse("没找到当前用户")

        if runtime.context.role == "student":
            if attempt_id is not None:
                try:
                    record = attempts.get_attempt_record(attempt_id, session)
                    attempts.require_attempt_reader(session, record, user)
                except attempts.AttemptNotFound:
                    return _refuse("没找到这条作答记录")
                except Exception:  # noqa: BLE001 - 权限拒绝统一成中文结果
                    return _refuse("只能看自己的作答记录")
                if record.status != "graded":
                    return _refuse("这次考试还没判分，暂时没有结果")
            else:
                record = _latest_student_attempt(
                    session, user.id, paper_title=paper_title
                )
                if record is None:
                    return _refuse("没找到已判分的考试记录")
            return {"found": True, **_trim_attempt(attempts.attempt_detail(session, record))}

        if runtime.context.role != "teacher":
            return _refuse("当前身份不能查看考试结果")
        class_id = runtime.context.class_id
        if class_id is None:
            return _refuse("请先选择班级")
        try:
            require_own_class(class_id, user, session)
        except Exception:  # noqa: BLE001
            return _refuse("只能查自己带的班")
        if not student_name and not student_username:
            return _refuse("请说出本班学生姓名")

        conditions = [User.role == "student", User.class_id == class_id]
        if student_username:
            conditions.append(User.username == student_username)
        else:
            conditions.append(User.name == student_name)
        matches = session.scalars(select(User).where(*conditions)).all()
        if not matches:
            return _refuse("本班没有这个学生")
        if len(matches) > 1:
            return _refuse("本班有多个同名学生，请补充用户名")
        target = matches[0]

        record = _latest_student_attempt(
            session, target.id, class_id=class_id, paper_title=paper_title
        )
        if record is None:
            return _refuse("没找到这个学生已判分的考试记录")
        return {"found": True, **_trim_attempt(attempts.attempt_detail(session, record))}


@tool
def class_overview(runtime: ToolRuntime[ChatContext]) -> dict:
    """何时用：老师问“我们班哪块最弱”“这次考得怎么样”。
    会发生什么：只返回当前班级的知识点错误率分布和学生人数，不返回学生名单或排名。
    下一步：建议老师从最弱的那一个点挑几道题讲评。
    不适用：学生用一律拒绝；查某一个学生的成绩要用看考试结果。
    """
    if runtime.context.role != "teacher":
        return _refuse("只有老师可以查看班级概况")
    class_id = runtime.context.class_id
    if class_id is None:
        return _refuse("请先选择班级")
    with _session(runtime) as session:
        user = _current_user(session, runtime)
        if user is None:
            return _refuse("没找到当前用户")
        try:
            require_own_class(class_id, user, session)
        except Exception:  # noqa: BLE001
            return _refuse("只能查自己带的班")
        overview = class_reporting.class_overview(session, class_id, user)
        points = overview.get("knowledge_points") or []
        shown = points[:5]
        return {
            "found": True,
            "class": overview.get("class"),
            "student_count": len(overview.get("students") or []),
            "exam_count": overview.get("exam_count", 0),
            "knowledge_points": shown,
            "total_knowledge_points": len(points),
            "remaining": max(0, len(points) - len(shown)),
        }
