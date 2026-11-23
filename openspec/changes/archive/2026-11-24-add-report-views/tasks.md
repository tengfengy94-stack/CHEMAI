# Tasks

## 1. 统计核心与旧弱项兼容

- [x] 1.1 重构 `backend/app/reporting.py`：抽出 `knowledge_stats(session, student_id)` 返回每个知识点的作答数与错题数，`weak_items(stats)` 与待实现的 `mastery_value(stats)` 共用同一份统计；运行 `cd backend && ../.venv/Scripts/python.exe -m pytest -q tests/test_weak_report.py`，现有弱项用例全绿。
- [x] 1.2 在弱项候选阶段增加 `wrong_count > 0` 条件；在 `tests/test_weak_report.py` 增加「唯一达标知识点全对 → 弱项为空」「0% 错误率不占前三」用例，运行该文件全绿。
- [x] 1.3 实现掌握度：只取作答数 >= 2 的知识点，知识点等权平均正确率 ×100，保留一位小数；新增 `backend/tests/test_report_views.py`，覆盖设计示例 37.5/50/50/100 → 59.4、全对唯一知识点 → 100.0、样本不足不参与、一题多知识点、复习与未判分不计；运行 `pytest tests/test_report_views.py -k mastery` 全绿。
- [x] 1.4 实现最近五次分数：`status='graded'` 且 `graded_at` 非空，按 `graded_at DESC, id DESC` 取 5 条再正序返回；测试六次取五、未判分不计、不足五次、同时间按记录 ID 稳定排序；运行 `-k recent` 全绿。
- [x] 1.5 在 `backend/app/review.py` 抽出 `due_task_count(session, student_id)`，到期列表与报告共用同一条件（级别 0–4、`due_on <= 业务今天`）；测试今天、逾期、未来、5 级出队四种计数；运行 `pytest tests/test_review_tasks.py tests/test_report_views.py -k due` 全绿。

## 2. 学生报告接口

- [x] 2.1 实现 `student_report(session, student_id)`：一次组装弱项、掌握度、最近五次分数、待复习数；测试四块来自同一份事实、练一道题后重新请求数字变化（现算无快照）；运行 `pytest tests/test_report_views.py -k student_report` 全绿。
- [x] 2.2 新增 `GET /api/reports/me`（`backend/app/reporting_routes.py`），只允许学生本人，老师与管理员 403；在 `main.py` 挂路由；测试未登录 401、学生 200、老师 403、返回字段完整且不含标准答案；运行 `pytest tests/test_report_views.py -k me` 全绿。
- [x] 2.3 确认 `GET /api/reports/weak` 行为不变（学生本人、管理员指定学生、老师 403）；运行 `pytest tests/test_weak_report.py tests/test_permissions.py` 全绿。

## 3. 班级报告查询与接口

- [x] 3.1 实现班级考试列表：按 `answer_records.class_id` 快照去重 `paper_id`，返回标题、发布时间、题数、名单人数，按发布时间倒序；测试只含本班、同卷发两个班互不影响、重复发布只补缺、无考试返回空；运行 `pytest tests/test_class_report.py -k exams` 全绿。
- [x] 3.2 实现单次考试提交情况与未交名单：`已交卷 = submitted + graded`、`作答中 = in_progress`、`还没开始 = pending`，三类之和等于名单人数；未交名单含姓名与状态；测试转班学生仍算原班、已交卷不出现在未交名单；运行 `-k submission` 全绿。
- [x] 3.3 实现逐题正确率：按卷内顺序，分母只含已判分记录，空白答案按错，分母为 0 返回空值；测试 60 人 52 已判分 → 分母 52、未判分不入分母、白卷计错、无人判分返回「—」；运行 `-k questions` 全绿。
- [x] 3.4 实现按知识点分布与学生表：全班错误率用班级版事实子查询合并分子分母，学生表给最近一次分数与按题去重的错题数；测试池化不是平均、同一题错两次错题数只加 1、没作答显示「未作答」、没考过试返回空、知识点合并后重算；运行 `-k knowledge` 全绿。
- [x] 3.5 新增 `GET /api/reports/classes/{class_id}` 与 `GET /api/reports/classes/{class_id}/exams/{paper_id}`，在入口调用 `require_own_class`，所有查询再带 `class_id` 条件；测试老师本班 200、别班 403、学生 403、管理员 200、班级不存在 404；运行 `pytest tests/test_class_report.py` 全绿。
- [x] 3.6 验证班级报告数据范围：练习记录不进任何班级数字、未判分记录不进正确率与知识点、转班不重算历史；在 `tests/test_class_report.py` 补用例并运行全绿。

## 4. 老师下钻学生报告

- [x] 4.1 新增 `GET /api/reports/students/{student_id}`：学生只能看自己；老师要求目标学生当前班级属于自己带的班；管理员放行；学生不存在 404；测试本班学生 200、别班 403、学生看别人 403、转出学生原老师 403、管理员 200；运行 `pytest tests/test_report_views.py -k drilldown` 全绿。
- [x] 4.2 在班级学生表返回 `can_view_report`（学生当前是否仍在该班快照所属老师的班里），转出学生为 false；测试转出学生历史分数仍在、字段为 false、本班学生为 true；运行 `-k transferred` 全绿。

## 5. 前端学生报告页

- [x] 5.1 在 `frontend/src/api.js` 增加 `getMyReport`，`Report.jsx` 改用 `/reports/me`；运行 `cd frontend && npm run build` 通过。
- [x] 5.2 `Report.jsx` 增加掌握度卡片、待复习数、最近五次分数折线图（Recharts），实现三种空态与加载/出错/重试；`npm run build` 通过。
- [x] 5.3 抽出可复用的 `ReportView`：学生路由 `/student/report` 走 `/reports/me`，新增 `/teacher/students/:studentId/report` 走 `/reports/students/{id}`，注册路由与角色守卫；`npm run build` 通过。
- [x] 5.4 GUI 走查：有数据、从没作答、有作答但样本不足、接口失败重试四种状态；老师从班级页进入学生报告与跨班访问被拒各一次；记录走查结果。

## 6. 前端班级报告页

- [x] 6.1 在 `frontend/src/api.js` 增加 `getMyClasses`、`getClassReport`、`getClassExamReport`；`npm run build` 通过。
- [x] 6.2 新增 `frontend/src/pages/teacher/TeacherClassReport.jsx`：班级选择、考试选择、提交情况三数、逐题正确率表、未交名单；加载/空/正常/出错四态，无考试显示「还没有考试记录」；`npm run build` 通过。
- [x] 6.3 班级报告页补按知识点分布、学生表、学生行下钻；转出学生显示标记且不给报告链接；`npm run build` 通过。
- [x] 6.4 在 `App.jsx` 注册 `/teacher/class`（老师与管理员），在题库、组卷、知识点三页和班级报告页互相加入导航入口；`npm run build` 通过。
- [x] 6.5 GUI 走查：老师本班正常数据、无考试空态、别班请求被拒、点学生进报告、转出学生无链接；记录走查结果。

## 7. 集成验证

- [x] 7.1 运行后端全量测试 `cd backend && ../.venv/Scripts/python.exe -m pytest -q`，全绿。
- [x] 7.2 运行 `bash scripts/check.sh 10` 与 `bash scripts/doctor.sh`，全绿。
- [x] 7.3 运行 `openspec validate "add-report-views" --strict`，确认无 warning。
- [x] 7.4 用种子账号手工验收：学生报告四块数字、班级按考试三数相加等于名单、逐题分母只含已判分、老师跨班 403、转班学生原班数字保留；记录验收结果。

## 8. 评审后修复

- [x] 8.1 班级学生表返回 `grading_pending`，已交卷未判分显示「判分中」而不是「未作答」；补 `test_class_report.py` 用例并运行全绿。
- [x] 8.2 转班后原班报告按当前班判定 `can_view_report`，同一位老师别的班也不给原班入口；更新 spec 场景与测试。
- [x] 8.3 考试重试保留当前所选考试；班级报告与学生报告的错误态不再显示后端原文。
- [x] 8.4 班级三张表与未交名单每页 20 条；班级页显示「共考过几次」和每场题数/名单人数。
- [x] 8.5 弱项与最近分数空态加下一步按钮；清理重复的 `getMyClasses` 请求与无调用的 `formatErrorRate`。

## Workflow follow-up

- 在 `docs/进度.md` 追加第 10 章记录（做了什么、卡在哪）。
- 评审通过后归档变更并同步 `openspec/specs/reporting/spec.md`。
- 按前几章惯例提交并打 `ch10-ok` 标签。
