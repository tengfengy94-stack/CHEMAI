# Proposal

## Why

第 09 章结束时，学生报告只有一张弱项表；设计 §4.5 要求的掌握度、最近五次分数、待复习数都还没有出口，老师侧则完全没有班级报告页。讲评课要回答的「谁没交、哪道题错得多」目前只能靠翻作答记录，报告这条链没有闭合。

## What Changes

- 学生报告一次返回四块：弱项前三（已有口径）、掌握度、最近五次分数、待复习数。
- 掌握度按「达到样本门槛的知识点等权平均正确率 × 100」计算，只算作答数不少于 2 的知识点；不可计算时返回 0 并带无数据标记，页面不得显示「掌握度 0」。
- 区分三种「没有」：完全没有作答事实、有作答但没有知识点达到样本门槛、数据够但全对；弱项只收错误率大于 0 的知识点，修正当前 0% 知识点可能进入弱项的问题。
- 新增班级报告：按考试视图给出考试选择、提交情况（已交卷、作答中、还没开始）、逐题正确率与未交名单；按知识点视图给出全班知识点错误率分布、每个学生的最近一次分数与错题数、这个班考过几次。
- 班级统计只统计考试作答，且按发布时的班级快照归集；练习记录没有班级快照，不进入班级报告。
- 老师从班级页下钻学生报告：新增老师专用读取接口，按当前班级归属判定；现有学生自助弱项接口保持只允许本人与管理员。
- 前端新增 `/teacher/class` 班级报告页，学生报告页补掌握度、分数走势、待复习数与三种空态。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `reporting`: 增加掌握度、最近五次分数、待复习数、班级报告两视图与老师下钻；修改旧要求「老师请求学生弱项返回 403」，并收窄弱项为错误率大于 0 的知识点。

## Impact

- 后端：`backend/app/reporting.py`（掌握度与报告汇总）、`backend/app/reporting_routes.py`（学生报告与老师下钻）、新增班级报告查询与路由；首次接线 `backend/app/auth.py` 的 `require_own_class`；复用 `backend/app/review.py` 的到期日口径。
- 前端：`frontend/src/pages/student/Report.jsx`、新增 `frontend/src/pages/teacher/TeacherClassReport.jsx`、`frontend/src/App.jsx` 路由、`frontend/src/api.js`、老师导航入口。
- 数据：不新增表、不做迁移。`answer_records.class_id` 已是发布时快照；`practice_records` 没有班级字段，因此班级报告不含练习。
- 接口：新增学生报告汇总接口与班级报告接口；`GET /api/reports/weak` 的可见范围调整只涉及老师下钻路径，学生与管理员的既有行为不变。
- 规格：`openspec/specs/reporting/spec.md` 需要增量修改；`access-control` 的三条规则不变，只是首次在报告接口上落地「只能看自己带的班」。
