"""题目检索的共享查询：角色条件 + 筛选条件。

路由和 Agent 工具都从这里取，避免工具 import 路由层。
"""
from sqlalchemy import select

from app.auth import AccessDeniedError
from app.models import Question, User


def build_question_query(
    user: User,
    difficulty: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
):
    """角色条件先加，用户筛选只收窄；筛选永远不能放大范围。"""
    if user.role == "teacher":
        conditions = [Question.created_by == user.username]
    elif user.role == "student":
        # 学生只看已通过（设计/02 §4.2）；这条与筛选无关，永远在
        conditions = [Question.status == "approved"]
    elif user.role == "admin":
        conditions = []
    else:
        # 未知角色不能落到"管理员全量"，直接拒绝
        raise AccessDeniedError("角色不认识，不能查看题目")

    if difficulty is not None:
        conditions.append(Question.difficulty == difficulty)
    if status is not None:
        conditions.append(Question.status == status)
    if keyword:
        conditions.append(Question.stem.contains(keyword))

    stmt = select(Question)
    if conditions:
        stmt = stmt.where(*conditions)
    return stmt
