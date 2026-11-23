"""把第 07 章的临时知识点迁进第 08 章的正式词表。

用法（在 backend/ 下）：
    ../.venv/Scripts/python.exe -m app.knowledge_migrate --dry-run
    ../.venv/Scripts/python.exe -m app.knowledge_migrate --apply

迁移只做数据整理，不建表、不改接口。计划阶段只读；执行阶段放在一个事务里，
任一步失败整体回滚。重复执行时正式节点已存在、临时节点已消失，计划为空。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, knowledge
from app.db import make_engine, make_session_factory
from app.knowledge_seed import FORMAL_CHILDREN, FORMAL_NAMES, FORMAL_ROOTS, TEMP_LABEL_MAP
from app.models import KnowledgePoint, KnowledgePointAlias, QuestionKnowledgePoint


class KnowledgeMigrationError(Exception):
    """迁移无法安全执行；命令层打印中文原因并返回非零。"""


@dataclass
class MigrationPlan:
    create: list[dict[str, str | None]] = field(default_factory=list)
    merges: list[dict[str, str]] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    moved_questions: int = 0
    moved_aliases: list[str] = field(default_factory=list)

    def report(self, *, dry_run: bool, applied: bool) -> dict:
        return {
            "dry_run": dry_run,
            "applied": applied,
            "created": [dict(item) for item in self.create],
            "merged": [dict(item) for item in self.merges],
            "kept": list(self.keep),
            "moved_questions": self.moved_questions,
            "moved_aliases": list(self.moved_aliases),
            "conflicts": list(self.conflicts),
        }


def _load(session: Session):
    points = list(session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id)))
    aliases: dict[int, list[str]] = defaultdict(list)
    for row in session.scalars(
        select(KnowledgePointAlias).order_by(KnowledgePointAlias.id)
    ):
        aliases[row.knowledge_point_id].append(row.alias)

    owner: dict[str, int] = {}
    for point in points:
        owner[point.name] = point.id
    for point_id, words in aliases.items():
        for word in words:
            owner[word] = point_id
    return points, aliases, owner


def _question_ids(session: Session) -> dict[int, set[int]]:
    result: dict[int, set[int]] = defaultdict(set)
    for point_id, question_id in session.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            QuestionKnowledgePoint.question_id,
        )
    ):
        result[point_id].add(question_id)
    return result


def build_plan(session: Session) -> MigrationPlan:
    """只读地算出迁移计划；不写库。"""
    points, aliases, owner = _load(session)
    by_name = {point.name: point for point in points}
    by_id = {point.id: point for point in points}
    question_ids = _question_ids(session)
    plan = MigrationPlan()

    formal_ids: dict[str, int | None] = {}
    target_questions: dict[str, set[int]] = {}
    target_aliases: dict[str, list[str]] = {}

    # 1. 正式根节点：已有同名节点就用，没有就计划新建；位置不对或词被占就是冲突。
    for name in FORMAL_ROOTS:
        existing = by_name.get(name)
        if existing is not None:
            if existing.parent_id is not None:
                plan.conflicts.append(f"正式根节点「{name}」已存在，但挂在其他节点下")
                continue
            formal_ids[name] = existing.id
            target_questions[name] = set(question_ids.get(existing.id, set()))
            target_aliases[name] = list(aliases.get(existing.id, []))
        else:
            if name in owner:
                plan.conflicts.append(f"正式根节点「{name}」与已有节点的名称或别名冲突")
                continue
            formal_ids[name] = None
            target_questions[name] = set()
            target_aliases[name] = []
            plan.create.append({"name": name, "parent": None})

    # 2. 正式子节点：只能是正式根节点的直接下级。
    for root_name, child_names in FORMAL_CHILDREN.items():
        if root_name not in formal_ids:
            continue
        for child_name in child_names:
            existing = by_name.get(child_name)
            if existing is not None:
                parent = by_id.get(existing.parent_id) if existing.parent_id is not None else None
                if parent is None or parent.name != root_name:
                    plan.conflicts.append(
                        f"正式子节点「{child_name}」已存在，但不在「{root_name}」下"
                    )
                continue
            if child_name in owner:
                plan.conflicts.append(f"正式子节点「{child_name}」与已有节点的名称或别名冲突")
                continue
            plan.create.append({"name": child_name, "parent": root_name})

    # 3. 临时节点：按名称或别名命中正式根节点；命中就合并，未命中就保留。
    for point in points:
        if point.name in FORMAL_NAMES:
            continue
        words = [point.name, *aliases.get(point.id, [])]
        targets = sorted({TEMP_LABEL_MAP[word] for word in words if word in TEMP_LABEL_MAP})
        if len(targets) > 1:
            plan.conflicts.append(
                f"临时节点「{point.name}」同时命中多个正式节点：{'、'.join(targets)}"
            )
            continue
        if not targets:
            plan.keep.append(point.name)
            continue

        target_name = targets[0]
        if target_name not in formal_ids:
            plan.conflicts.append(
                f"临时节点「{point.name}」的目标「{target_name}」不是可用的正式根节点"
            )
            continue
        target_id = formal_ids[target_name]
        if target_id == point.id:
            plan.conflicts.append(f"临时节点「{point.name}」不能合并到自己")
            continue

        merged_aliases = knowledge._clean_aliases(
            [*target_aliases[target_name], point.name, *aliases.get(point.id, [])],
            exclude=target_name,
        )
        taken = [
            word
            for word in merged_aliases
            if owner.get(word) is not None
            and owner[word] not in (point.id, target_id)
        ]
        if taken:
            plan.conflicts.append(
                f"临时节点「{point.name}」并入「{target_name}」时词冲突："
                + "、".join(sorted(taken))
            )
            continue

        source_questions = set(question_ids.get(point.id, set()))
        plan.moved_questions += len(source_questions - target_questions[target_name])
        plan.moved_aliases.extend(
            word
            for word in merged_aliases
            if word not in target_aliases[target_name]
        )
        target_questions[target_name] |= source_questions
        target_aliases[target_name] = merged_aliases
        plan.merges.append({"source": point.name, "target": target_name})

    return plan


def _apply_plan(session: Session, plan: MigrationPlan) -> None:
    created: dict[str, KnowledgePoint] = {}
    for name in FORMAL_ROOTS:
        point = session.scalar(select(KnowledgePoint).where(KnowledgePoint.name == name))
        if point is None:
            point = knowledge._create_point(
                session,
                name=name,
                parent_id=None,
                aliases=[],
                created_by="system",
            )
        created[name] = point

    for root_name, child_names in FORMAL_CHILDREN.items():
        root = created[root_name]
        for child_name in child_names:
            point = session.scalar(
                select(KnowledgePoint).where(KnowledgePoint.name == child_name)
            )
            if point is None:
                point = knowledge._create_point(
                    session,
                    name=child_name,
                    parent_id=root.id,
                    aliases=[],
                    created_by="system",
                )
            created[child_name] = point

    for merge in plan.merges:
        source = session.scalar(
            select(KnowledgePoint).where(KnowledgePoint.name == merge["source"])
        )
        if source is None:  # 第三次执行时临时节点已经不在，跳过
            continue
        knowledge._merge_points(session, source, created[merge["target"]])

    session.commit()


def run_migration(session: Session, *, dry_run: bool = False) -> dict:
    plan = build_plan(session)
    report = plan.report(dry_run=dry_run, applied=False)
    if plan.conflicts or dry_run:
        return report
    try:
        _apply_plan(session, plan)
    except Exception:
        session.rollback()
        raise
    report["applied"] = True
    return report


def format_report(report: dict) -> str:
    if report["conflicts"]:
        result = "发现冲突，未写入"
    elif report["dry_run"]:
        result = "dry-run，未写入"
    elif report["applied"]:
        result = "已写入"
    else:
        result = "未写入"

    lines = [f"== 知识点迁移（{result}）=="]
    if report["created"]:
        lines.append(f"新建正式节点 {len(report['created'])} 个：")
        for item in report["created"]:
            parent = f"（{item['parent']} 下）" if item["parent"] else "（根）"
            lines.append(f"  - {item['name']}{parent}")
    else:
        lines.append("新建正式节点：无")

    if report["merged"]:
        lines.append(f"合并临时节点 {len(report['merged'])} 个：")
        for item in report["merged"]:
            lines.append(f"  - {item['source']} -> {item['target']}")
    else:
        lines.append("合并临时节点：无")

    lines.append(
        "保留未命中节点："
        + ("、".join(report["kept"]) if report["kept"] else "无")
    )
    lines.append(
        f"移动题目关联 {report['moved_questions']} 条，"
        f"别名 {len(report['moved_aliases'])} 个"
        + (f"（{'、'.join(report['moved_aliases'])}）" if report["moved_aliases"] else "")
    )
    if report["conflicts"]:
        lines.append(f"冲突 {len(report['conflicts'])} 项，未写入：")
        lines.extend(f"  - {item}" for item in report["conflicts"])
    else:
        lines.append("冲突：无")
    lines.append(f"结果：{result}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把第 07 章的临时知识点迁进正式词表"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run", action="store_true", help="只输出迁移计划，不写库（默认）"
    )
    group.add_argument("--apply", action="store_true", help="执行迁移")
    args = parser.parse_args(argv)

    dry_run = not args.apply
    engine = make_engine(config.database_url())
    factory = make_session_factory(engine)
    try:
        with factory() as session:
            try:
                report = run_migration(session, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001 - 命令层统一打印中文原因
                print(f"迁移失败，已回滚：{exc}")
                return 1
    finally:
        engine.dispose()

    print(format_report(report))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
