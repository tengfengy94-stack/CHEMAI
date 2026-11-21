# Tasks

## 1. 判分基线核对

- [x] 1.1 运行既有判分与状态机测试，确认三种题型规则、总分公式、已交卷到已判分的转移和失败重试全绿；验证：`bash scripts/check.sh 06` 通过，且 `git diff` 中 `backend/app/answers.py` 与 `grade_record` 无改动。
- [x] 1.2 记录现有判分测试覆盖的用例（`test_answers.py`、`test_exam_attempts.py` 的判分、失败重试、并发交卷），作为本次错题实现的回归基线；验证：实现结束后这些测试仍全部通过。
- [x] 1.3 修正填空归一：只把全角 ASCII 转半角，下标和电荷保持原样；验证：`H₂O`/`H2O` 与 `NH₄⁺`/`NH4+` 判错，全角 `NaCl` 与全角 `Ｈ₂Ｏ` 判对，`pytest tests/test_answers.py` 全绿。

## 2. 后端错题清单接口

- [x] 2.1 在 `backend/app/routes.py` 新增 `GET /api/wrong-questions`，用 `answer_items` / `answer_records` / `questions` / `papers` 联查，并用窗口函数按 `question_id` 取最近一次答错；验证：请求返回每条错题含题干、选项、学生答案、标准答案、解析、来源、卷子标题、最近答错时间。
- [x] 2.2 排序用 `submitted_at DESC`、同时间用 `answer_items.id DESC` 兜底，外层按最近答错时间倒序；验证：两道题不同时间答错时后错的排在前面。
- [x] 2.3 只取 `is_correct = false` 且 `status = graded` 的记录，`score = 0.0` 的卷子也返回错题，判分失败的记录不返回；验证：白卷判分后每道题都出现，`submitted + 空分` 的记录不出现。
- [x] 2.4 加角色过滤：学生只看自己的，管理员看全部，老师返回 403 且不返回数据；验证：三类账号分别请求的响应符合预期。
- [x] 2.5 来源字段固定返回 `exam`，条目带 `attempt_id` 与 `paper_id` 便于回看；验证：响应字段与 `specs/exam/spec.md` 的条目描述一致。

## 3. 后端测试

- [x] 3.1 新增 `backend/tests/test_wrong_questions.py`，覆盖同一题多次答错只留一条、答案取最近一次、按时间倒序、答对不移除；验证：`cd backend && ../.venv/Scripts/python.exe -m pytest tests/test_wrong_questions.py -q` 通过。
- [x] 3.2 覆盖字段完整性、未作答空答案、白卷零分、判分失败不产生错题、重试成功后错题出现；验证：新增用例全部通过。
- [x] 3.3 覆盖空清单、学生之间隔离、老师 403、管理员看全部；验证：权限与空状态用例通过。
- [x] 3.4 跑后端全量测试，确认 ch05 的判分、交卷、重试与并发用例没有回归；验证：`bash scripts/check.sh 06` 通过。

## 4. 前端结果态与错题抽屉

- [x] 4.1 在 `frontend/src/api.js` 增加 `listWrongQuestions`，复用现有 `request` 信封与 401 刷新逻辑；验证：`cd frontend && npm run lint` 通过。
- [x] 4.2 在 `frontend/src/constants.js` 增加错题来源标签（`exam` → 考试）；验证：抽屉里来源显示为中文。
- [x] 4.3 在 `frontend/src/pages/student/Exams.jsx` 的结果态增加「看错题」按钮，只在 `graded` 时显示；点击打开抽屉并在打开时重新请求；验证：已判分记录可见按钮，`submitted + 空分` 不显示。
- [x] 4.4 抽屉覆盖加载中、空、出错三种状态，条目展示题干、选项、自己的答案、标准答案、解析、来源和最近答错时间；验证：手工断开后端看到出错与重试，无错题时看到明确空状态。
- [x] 4.5 跑前端检查；验证：`cd frontend && npm run lint && npm run build` 均通过且无新增告警。

## 5. 集成验收

- [x] 5.1 用演示账号完整走查：老师建卷发卷，学生用单选、多选、填空各答错一题后交卷，结果态出现分数与逐题对错，点「看错题」看到三条且来源为考试；验证：页面行为与 `specs/exam/spec.md` 场景一致。
- [x] 5.2 让同一道题在第二份卷子里再次答错，确认错题清单仍只有一条且答案是后一次；再答对一次，确认该题不消失；验证：两次操作后的清单条数与内容正确。
- [x] 5.3 运行章节检查与体检；验证：`bash scripts/check.sh 06` 与 `bash scripts/doctor.sh` 全绿。

## Workflow follow-up

- 评审通过后运行 `openspec archive add-grading-wrong-answers` 归档变更，并检查归档后的 `openspec/specs/exam/spec.md` 与任务状态。
