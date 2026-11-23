# Tasks

## 1. 数据模型与迁移

- [x] 1.1 在 `backend/app/models.py` 增加 `PracticeRecord`（学生、题目、难度、对错、作答时间）及 `(student_id, id)`、`(question_id)` 索引；用 `cd backend && ../.venv/Scripts/python.exe -c "from app.models import PracticeRecord; print(PracticeRecord.__tablename__)"` 确认模型可导入、表名与字段和 design.md 一致。
- [x] 1.2 新增 `backend/alembic/versions/0005_practice.py`，`down_revision = "0004_review_knowledge"`，建表与两个索引；用临时库执行 `alembic upgrade head` 再 `alembic downgrade 0004_review_knowledge`，确认可往返。
- [x] 1.3 新增 `backend/tests/test_migration_0005.py`，断言表与索引存在、downgrade 后表消失；运行 `cd backend && ../.venv/Scripts/python.exe -m pytest -q tests/test_migration_0005.py` 全绿。

## 2. 练习核心逻辑

- [x] 2.1 实现难度重放 `current_difficulty(session, student_id)`：初始 2、答错降一档、每连续答对两题升一档、1/3 夹紧，忽略记录里的 `difficulty`；在 `tests/test_practice.py` 写初始 2、连对一题不升、连对两题升、答错降、1 档兜底、3 档封顶、从 1 档连对四题、放宽题不改难度用例；运行 `-k difficulty` 全绿。
- [x] 2.2 实现最近窗口与候选查询：按 `(student_id, id DESC)` 取最近 20 条、按 `question_id` 去重、窗口前缀 20/10/5/0；写 20 条内排除、第 21 条可用、跨知识点共享、不足 20 条按实际条数用例，运行 `-k window` 全绿。
- [x] 2.3 实现按弱项顺序选点与五步放宽阶梯（当前档/20 → 任意/20 → 任意/10 → 任意/5 → 任意/0），全空返回空态；写第一弱项优先、第一空顺延、三个全空、不跨弱项抓题、一题多知识点、放宽优先于缩窗用例，运行 `-k selection` 全绿。
- [x] 2.4 实现无弱项分支：全部已通过题、同一阶梯、`has_weak_data` 与 `no_data`/`no_weak_point` 原因；写新学生 2 档、练过但未形成弱项按推导档、题库为空空态用例，运行 `-k no_weak` 全绿。
- [x] 2.5 实现练习作答：复用 `answers.judge_answer`、500 字上限、写记录、返回下一题难度；写单选/多选/填空、超长 422、题目不存在/未通过 404、记录内容、同一题两次两条用例，运行 `pytest tests/test_practice.py` 全绿。
- [x] 2.6 验证副作用边界：练习答错不建复习任务、不改考试分数/逐题对错/错题清单、不改已有复习级别；在 `tests/test_practice.py` 写用例并运行全绿。

## 3. 弱项统计合并练习

- [x] 3.1 改 `backend/app/reporting.py` 为 `exam_facts UNION ALL practice_facts`，`has_data` 也基于合并事实；运行现有 `tests/test_weak_report.py`，确认原有用例不回归。
- [x] 3.2 在 `tests/test_weak_report.py` 增加练习计分、考试+练习合并、练习未挂知识点不计、只有练习记录时 `has_data=true`、样本门槛合并用例；运行该文件全绿。
- [x] 3.3 在 `tests/test_weak_report.py` 增加合并知识点后练习记录重算用例；运行该文件全绿。

## 4. API 与权限

- [x] 4.1 在 `backend/app/schemas.py` 增加 `PracticeAnswerRequest`（`question_id`、`answer`、`difficulty`），补 `FIELD_LABELS` 的 `difficulty`；运行 `pytest tests/test_questions_api.py tests/test_exam_attempts.py` 确认现有请求校验不回归。
- [x] 4.2 新增 `backend/app/practice_routes.py` 的 `GET /api/practice/next` 与 `POST /api/practice/answers`，在 `main.py` 挂路由；测试响应字段、空态信封、`next` 不含标准答案与解析、提交后才返回。
- [x] 4.3 实现权限：学生只用当前身份，老师与管理员 403；写三种角色调用两个接口的用例，确认 403/200 与不泄露数据。
- [x] 4.4 测试作答失败路径：答案超长 422、题目不存在 404、未通过 404，且都不写练习记录；运行 `pytest tests/test_practice.py` 全绿。

## 5. 删题限制

- [x] 5.1 在 `backend/app/routes.py` 的 `delete_question` 增加练习记录检查，返回 409「这道题已被学生练习过，不能删除」；写练过的题被拒且记录保留用例，运行 `pytest tests/test_practice.py -k delete` 全绿。
- [x] 5.2 更新 `tests/test_question_management.py`，确认未练过、也未进卷子的题仍可删除；运行该文件全绿。

## 6. 前端练习页

- [x] 6.1 在 `frontend/src/api.js` 增加 `getNextPracticeQuestion` 与 `answerPracticeQuestion`；运行 `cd frontend && npm run build` 确认编译通过。
- [x] 6.2 新增 `frontend/src/pages/student/Practice.jsx`：三格难度、三种题型输入、提交反馈（对错/标准答案/解析/下一题）、无弱项提示、暂无题、出错重试；在 `App.jsx` 注册 `/student/practice`，`StudentHeader` 加"练习"入口；`npm run build` 通过。
- [x] 6.3 GUI 走查六态：正常出题、答对/答错反馈、升档/降档、无弱项提示、暂无题、加载失败重试；确认老师与学生路由守卫生效；记录走查结果。
- [x] 6.4 页面与接口字段联调：确认 `served_difficulty`、`next_difficulty`、空态 `reason` 与后端响应一致；`npm run build` 通过且控制台无报错。

## 7. 集成验证

- [x] 7.1 运行后端全量测试 `cd backend && ../.venv/Scripts/python.exe -m pytest -q`，全绿（含练习、弱项、删题、迁移用例）。
- [x] 7.2 运行 `bash scripts/check.sh 09` 与 `bash scripts/doctor.sh`，全绿。
- [x] 7.3 用种子账号手工验收：学生练习到升档/降档、弱项报告出现练习计数、老师删练过的题被拒、无弱项与暂无题文案正确；记录验收结果。
- [x] 7.4 运行 `openspec validate "add-adaptive-practice" --strict`，确认规格无 warning。

## Workflow follow-up

- 在 `docs/进度.md` 追加第 09 章记录（做了什么、卡在哪）。
- 评审通过后归档变更并同步 specs。
- 按前几章惯例提交并打 `ch09-ok` 标签。
