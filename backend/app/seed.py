"""首次启动、题库为空时插入三条种子题（第 02 章 ① 的表）。"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import PLACEHOLDER_CREATOR
from app.models import Question, utcnow

SEED_QUESTIONS = [
    {
        "stem": "下列物质中属于电解质的是",
        "type": "single",
        "options": ["NaCl", "蔗糖", "CO2"],
        "answer": "A",
        "difficulty": 2,
        "status": "approved",
    },
    {
        "stem": "配平：Fe + O2 → Fe3O4",
        "type": "blank",
        "options": None,
        "answer": "3Fe + 2O2 → Fe3O4",
        "difficulty": 2,
        "status": "draft",
    },
    {
        "stem": "关于氧化还原反应，下列说法正确的是",
        "type": "multiple",
        "options": ["氧化剂得电子", "还原剂失电子", "化合价不变"],
        "answer": "AB",
        "difficulty": 3,
        "status": "pending",
    },
]


def seed_if_empty(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(Question)):
        return
    # 三条用同一个时间，列表按 id 排出 ① 表格里的顺序 1、2、3
    now = utcnow()
    for item in SEED_QUESTIONS:
        session.add(Question(**item, explanation=None, created_by=PLACEHOLDER_CREATOR, created_at=now))
    session.commit()
