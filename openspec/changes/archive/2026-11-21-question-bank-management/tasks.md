# Tasks

## 1. 后端接口

- [x] 1.1 `app/schemas.py` 增状态变更请求模型（`status` 只收 `pending` / `approved`）；编辑复用 `QuestionCreate` 与 `validate_new_question`；验证：模块可导入，`pytest -q` 既有测试不红
- [x] 1.2 `app/routes.py` 增 `PUT /api/questions/{id}`：按 `require_owner` 校验归属，已通过拒绝“已通过的题不能修改”，复用建题校验与答案规范化，不改 `status` 与 `created_by`；验证：编辑草稿/待复核成功、已通过 403、非创建者 403、管理员放行的接口测试全绿
- [x] 1.3 `app/routes.py` 增 `POST /api/questions/{id}/status`：按显式转移表只放行 `draft→pending`、`draft→approved`、`pending→approved`，其余拒绝并给中文原因；验证：六个流转场景（含待复核退回、已通过再改、非创建者）的接口测试全绿
- [x] 1.4 `app/routes.py` 增 `papers_using_question()`（本章恒 0）、`GET /api/questions/{id}/usage` 与 `DELETE /api/questions/{id}`：归属校验、`count > 0` 拒绝并给出份数；验证：未使用的题删除成功且列表消失、非创建者 403、usage 返回 0 的接口测试全绿

## 2. 列表筛选、分页与角色范围

- [x] 2.1 `app/routes.py` 把列表查询集中到 `build_question_query()`：角色条件先加（老师自己的、学生已通过、管理员全量、**未知角色 403**），再叠加 `difficulty`、`status`、`q`（匹配题干）三个筛选，条件取交集；验证：角色分叉、未知角色拒绝、学生筛选不放宽三个场景的测试全绿
- [x] 2.2 列表分页：`page` 从 1 开始、每页固定 20 条，响应改为 `{items, total, page, page_size}`；非法 difficulty/status/page 拒绝并给中文提示；验证：难度、状态、关键词、组合、分页（25 条取第 2 页）与非法值的接口测试全绿
- [x] 2.3 同步改造既有测试对新列表结构的断言（`test_questions_api`、`test_auth_api`、`test_question_access` 直接读 `data` 的地方改读 `data["items"]` / `data["total"]`）；验证：`pytest -q` 全量全绿，条数不少于 82

## 3. 前端题库页

- [x] 3.1 `src/api.js` 增 `updateQuestion`、`changeQuestionStatus`、`deleteQuestion`、`getQuestionUsage`，`listQuestions` 接受筛选与页码并返回分页对象；验证：`npm run build` 通过
- [x] 3.2 `QuestionBank.jsx` 顶部筛选条（难度、审核状态、关键词）＋服务端分页；筛选后为空显示“没有符合条件的题”，与“题库里还没有题”区分；验证：手动走查三种筛选与翻页
- [x] 3.3 `QuestionBank.jsx` 行操作按状态显示：草稿→编辑/标待复核/通过/删除，待复核→编辑/通过/删除，已通过→只留删除；编辑抽屉可保存；删除先查 `/usage`，为 0 才弹确认，大于 0 直接提示；验证：手动走查编辑保存、两步审核、删除与已通过行按钮消失

## 4. 验收

- [x] 4.1 `bash scripts/check.sh 04` 全绿（全量 pytest）
- [x] 4.2 `bash scripts/doctor.sh` 全绿
- [x] 4.3 `bash scripts/dev.sh` 起服务后手动验收：老师按状态/难度/关键词筛选与翻页；改一道草稿题；草稿标待复核再通过；已通过行没有编辑与审核按钮；删一道未使用题；学生只看到已通过题

## Workflow follow-up

- 组卷章节的第一件事：用卷子表替换 `papers_using_question()`，并补“删除被卷子使用的题被拒”的接口测试（本 spec 中该场景在本章无卷子可建，测试随组卷接线）。
- 按章节流程收尾：提交、打 tag `ch04-ok`、在 `docs/进度.md` 记第 04 章。
- 验收通过后归档本变更（`openspec archive`），归档前经用户确认。
