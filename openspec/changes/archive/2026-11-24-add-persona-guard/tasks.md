# Tasks

## 1. 连续答错计数与人设提示

- [x] 1.1 在 `backend/app/practice.py` 新增 `consecutive_wrong_count(session, student_id)`：按 `PracticeRecord.id` 倒序数尾部连续 `is_correct=False`，遇到 `True` 停止；验证：新增单测覆盖空记录为 0、最近三条全错为 3、错错对错为 1、不同学生记录不串。
- [x] 1.2 `ChatContext` 增加 `consecutive_wrong: int = 0`；`_build_context` 在现有 session 里对学生查计数，老师与管理员固定 0；验证：上下文构建测试断言三类角色取值，直接构造 `ChatContext` 的现有测试不破。
- [x] 1.3 `backend/app/agent_context.py` 增加 `ENCOURAGEMENT_THRESHOLD = 3` 与 `ENCOURAGEMENT_PROMPT`；`build_system_prompt` 在场景人设与 `STUDENT_SCOPE` 之后叠加鼓励段，老师与管理员不加；验证：单测覆盖 count=2 不追加、count=3 追加且仍含“不直接给答案”、老师 count=3 无鼓励、四段顺序保持身份→场景→红线→输出要求。

## 2. 输出检查规则与可见姓名

- [x] 2.1 `ChatContext` 增加 `visible_names` 与 `forbidden_names` 元组；`_build_context` 用同一 session 查询：学生 visible 为本人姓名与用户名、forbidden 为同班其他学生；老师 visible 为当前班学生、forbidden 为其他班学生；管理员为空；验证：单测覆盖学生、老师、管理员三类，确认本班姓名可见、别班姓名不可见。
- [x] 2.2 新增 `backend/app/agent_guard.py`，实现无状态 `scan(text, context)`、四条红线规则表与固定替代话术；验证：单测覆盖 #1 考试答案命中且非考试不命中、#2 陌生姓名分数与同班他人姓名命中、#3 “直接闻”命中而“氯气为什么有毒”与“扇闻”不命中、#4 贬低短语命中，且命中顺序为 1→4。
- [x] 2.3 在 `agent_guard.py` 实现有状态 `OutputGuard`：按 `。！？!?；;`、换行或 160 字切段，`feed` / `flush` 返回可发送片段，命中后只返回一次替代话术并停止后续输出；验证：单测覆盖多句连续发送、残句 flush、第二句命中、命中后 `feed` 不再输出、替代话术只出现一次。

## 3. SSE 接入与状态清洗

- [x] 3.1 `backend/app/agent.py` 的 `FakeChatModel` 增加 `[[guard:exam]]`、`[[guard:other]]`、`[[guard:danger]]`、`[[guard:insult]]` 四个触发词及对应违规回答；验证：假模型单测断言四个触发词各自返回对应违规正文，普通消息仍走原回答。
- [x] 3.2 在 `_stream_agent_events` 接入 `OutputGuard`：安全片段按句发 `text`，命中后停发原文与工具事件、发替代话术、正常发 `end`；`_last_ai_text` 的收尾正文也过同一检查；验证：SSE 集成测试覆盖四条红线，断言输出不含违规原文、含替代话术、`end` 恰好一次，干净回答仍有多个 `text`。
- [x] 3.3 fallback 单轮路径 `stream_events` 也接入 `OutputGuard`（`use_agent_graph=False` 时）；验证：单轮路径的违规触发词被替换并正常发 `end`，原有模型配置错误测试保持通过。
- [x] 3.4 命中后清洗本轮 checkpoint：流开始记录已有消息 ID，结束时把本轮新增 AI 消息中的违规正文清空（带 `tool_calls` 的保留工具调用），最后一条 AI 正文改为“已发安全前缀 + 替代话术”；验证：命中后 `GET /api/chat/history` 不含违规原文，下一轮模型收到的上下文不含违规原文。
- [x] 3.5 命中后模型流失败仍发 `end` 与替代话术；命中前失败维持只关流、不发 `end`；验证：两个脚本化模型的 SSE 测试分别断言这两种收尾。

## 4. 集成验证

- [x] 4.1 运行 `cd backend && .venv/Scripts/python.exe -m pytest -q`、`bash scripts/check.sh 13`、`bash scripts/doctor.sh`，全部通过；验证：三条命令退出码均为 0。
- [x] 4.2 运行 `openspec validate add-persona-guard --strict`，确认 proposal、两个 spec delta、design、tasks 全部通过；验证：命令退出码为 0。
- [x] 4.3 确认前端无改动、SSE 契约不变：`git diff --stat` 不含 `frontend/`，流测试里仍只出现 `tool` / `text` / `end` 三类事件；验证：diff 与测试输出一致。

## Workflow follow-up

- 实现与评审完成后更新 `docs/进度.md`，记录第 13 章做了什么、卡在哪。
- 归档前确认 `openspec validate add-persona-guard --strict` 全绿；归档后确认新生成的 `openspec/specs/agent-guard/spec.md` 保留了 Purpose。
- 按项目惯例提交并打 `ch13-ok` 标签。
