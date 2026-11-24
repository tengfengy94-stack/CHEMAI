# Tasks

## 1. 依赖与服务下沉

- [x] 1.1 在 `backend/requirements.txt` 锁定 `langchain==1.5.2`、`langgraph==1.2.24`、`langgraph-checkpoint-sqlite==3.1.3`；验证：`.venv/Scripts/python.exe -m pip install -r backend/requirements.txt` 成功，`cd backend && .venv/Scripts/python.exe -m pytest -q` 全绿。
- [x] 1.2 把 `build_question_query` 从 `routes.py` 下沉到 `app/question_search.py`，题目列表与组卷池改为调用 service；验证：题库列表、筛选、分页、组卷池现有测试全绿，接口响应字段不变。
- [x] 1.3 把 `_wrong_questions_query` 与 `_attempt_detail` 下沉到 `app/attempts.py`，错题接口与作答详情接口改为调用 service；验证：错题清单与作答详情现有测试全绿。
- [x] 1.4 新增 `knowledge.find_point`：名称与别名匹配，精确命中优先，多个候选取最接近，匹配不到返回空；验证：新增单测覆盖名称命中、别名命中、无匹配、多候选四种情况。

## 2. Agent 图与流

- [x] 2.1 新增 `ChatContext`（用户、角色、班级、场景、考试中标记）与 `build_agent`，用 `langchain.agents.create_agent` 装配 `AsyncSqliteSaver`，在 `create_app` lifespan 挂到 `app.state.agent`；验证：应用能启动，假模型完成一轮无工具回答，`/api/health` 正常。
- [x] 2.2 新增场景提示中间件：在 `wrap_model_call` 里按四段固定顺序生成 `SystemMessage` 并 `request.override(...)`；验证：练习、错题、普通对话、老师四类场景测试各自的提示词内容与顺序。
- [x] 2.3 接入 `SummarizationMiddleware`，配置 `trigger=("messages", 30)` 与 `keep=("messages", 20)`，摘要提示词用中文；验证：31 条消息触发压缩并保留最近 20 条，29 条不触发。
- [x] 2.4 接入 `ModelCallLimitMiddleware(run_limit=8, exit_behavior="end")`，并把内置英文收尾换成中文；验证：脚本化模型试图进行第 9 次调用时只发生 8 次，客户端收到中文收尾且已有正文保留。
- [x] 2.5 把 `FakeChatModel` 改成支持 `bind_tools` 的模型，按关键词脚本化调用看学生画像、看到期复习、布置练习、讲错题；验证：四类意图各命中一次对应工具，无密钥也能完成工具流程。
- [x] 2.6 `agent_routes` 用 `astream_events` 映射 `tool`/`text`/`end`，过滤 `tool_call_chunks` 与工具内部片，保证工具事件先于正文；验证：流测试断言事件顺序、`tool` 不含参数、`end` 最后且只一次、心跳不算事件。

## 3. 十个工具

- [x] 3.1 实现搜题、找知识点、看知识地图三个工具：搜题只取已通过题、默认 5 最多 20、不带答案解析；知识地图只返回目标节点的父/子名称；验证：三个工具的单测覆盖正常、空结果、匹配不到、超量截断。
- [x] 3.2 实现看学生画像、看到期复习两个工具：画像每次现查弱项前三、最近五次分数、待复习数；到期列表只含级别 0–4 且今天及以前到期，逾期在前并返回剩余数；验证：新增测试覆盖刚练习后的弱项变化、未来任务排除、逾期排序。
- [x] 3.3 实现讲错题与看考试结果（学生路径）：错题返回最近错误答案、答案解析、错因、正确思路、同类题；没答错过的题不编；未判分说没有结果；验证：单测覆盖错题、未答错、未判分、考试中拒绝四类。
- [x] 3.4 实现布置练习与加复习：练习按弱项与当前难度选一组题且不写练习记录；加复习新任务 0 级明天到期，已有 0–4 级保留级别只提前到期日，5 级重置为 0；验证：单测覆盖新任务、已有任务、5 级重入队、不能给别的学生加。
- [x] 3.5 实现看班级概况与老师考试摘要：班级概况只返回本班知识点分布与学生人数；老师摘要按班、按姓名（同名可补用户名）、只读已判分且快照属于本班；验证：单测覆盖本班、别班、转出、同名、未判分五类。
- [x] 3.6 统一工具错误、长度与身份边界：工具不抛异常，失败返回中文“没找到/参数不合法/这一项没查到”；列表默认 5 最多 20 并告诉剩余数；工具参数不接受学生编号、用户编号、班级编号；验证：单测覆盖异常、非法参数、超长列表、模型尝试传身份参数四类。

## 4. 线程、历史与班级请求

- [x] 4.1 实现线程编号与学生/老师历史接口：学生 `student:{id}`，老师 `teacher:{id}:class:{class_id}`，历史只返回当前线程的 Human/AI 文字消息；验证：单测覆盖刷新恢复、两个学生隔离、老师换班隔离、客户端传 thread_id 被忽略。
- [x] 4.2 `ChatRequest` 增加 `scene` 与 `class_id`：老师单班自动补、多班必填、别班 403；学生传 `class_id` 返回 422；验证：接口测试覆盖四种情况，失败发生在建立事件流之前。
- [x] 4.3 同一线程串行：用按线程的 `asyncio.Lock` 让上一轮未结束时新消息排队；验证：并发测试断言只执行一轮、第二条等待、回答不交错。

## 5. 前端

- [x] 5.1 `Chat.jsx` 打开时加载历史、渲染 `tool` 提示、接收场景参数；验证：`cd frontend && npm run build` 通过，浏览器走查刷新后历史仍在、工具提示不显示参数。
- [x] 5.2 老师对话页增加班级选择器：多班必选、显示当前班名、切换后加载对应线程；验证：`npm run build` 通过，浏览器走查切换班级后历史与回答范围随之变化。
- [x] 5.3 练习页支持题单模式：从对话带题单进入按顺序出题，答完或离开失效，默认模式仍按弱项出题；验证：`npm run build` 通过，浏览器走查题单顺序、离开后回默认模式、未作答不产生记录。
- [x] 5.4 练习页与错题页增加“问一句”入口，带对应场景进入对话页；验证：`npm run build` 通过，浏览器走查入口跳转与场景提示。
- [x] 5.5 去掉“本轮对话不会保存，刷新页面后清空”文案，补历史和错误重试文案；验证：`npm run build` 通过，页面不再出现旧文案，断流后保留已收到正文并可重试。

## 6. 集成验证

- [x] 6.1 运行 `cd backend && .venv/Scripts/python.exe -m pytest -q`、`bash scripts/check.sh 12`、`bash scripts/doctor.sh`、`cd frontend && npm run build`，全部通过；验证：四条命令退出码均为 0。
- [x] 6.2 运行 `openspec validate add-agent-tools --strict`，确认 proposal、六个 spec delta、design、tasks 全部通过；验证：命令退出码为 0。
- [x] 6.3 浏览器走查三条线：学生对话查画像/错题/复习并刷新恢复；老师选班查班级概况与某个学生考试摘要；学生从对话题单进练习；验证：截图存入 `gui-test-screenshots/`，关键状态与文案符合设计 05 §4.2。

## Workflow follow-up

- 实现与评审完成后更新 `docs/进度.md`，记录第 12 章做了什么、卡在哪。
- 归档 change 前确认 `openspec validate add-agent-tools --strict` 全绿；归档后把 `openspec/specs/agent-chat/spec.md` 的 Purpose 改成不再写“本章不调用工具、不保存任何历史”。
- 按项目惯例提交并打 `ch12-ok` 标签。
