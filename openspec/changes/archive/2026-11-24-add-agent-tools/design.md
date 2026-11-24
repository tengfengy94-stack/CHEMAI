# Design

## Context

第 11 章的 `backend/app/agent.py` 只有单轮模型调用：`build_messages` 固定 system + user 两条，`agent_routes.stream_events` 只转发正文分片，没有工具、没有历史、没有线程。`Chat.jsx` 也只处理 `text` 与 `end`。

现有业务能力已经齐了：`reporting.student_report`、`review.list_tasks`、`practice.current_difficulty`、`knowledge.tree`、`class_reporting.class_overview` 等都能直接复用。问题在于这些查询有的在 service 层，有的还留在 `routes.py` 的私有函数里，工具不能直接 import 路由层。

约束：

- 设计 04 §4.1 要求一个智能体、一个循环、五个部件，不自己写状态机。
- 设计 04 §4.2 要求三层记忆：最近 20 条、超过 30 条压缩、学生画像每次现查。
- 设计 04 §4.4 要求身份从运行时注入，模型不能传学生编号。
- 设计 05 §4.7 指定 Agent 用 LangChain + LangGraph。
- 单机 SQLite、单进程 FastAPI，不引入消息队列或外部服务。

## Goals / Non-Goals

**Goals:**

- 用框架内置循环接十个工具，8 次模型调用封顶。
- 用框架 checkpointer 做按线程的对话存档，补历史接口。
- 工具全部复用服务层函数，不在工具里发 HTTP。
- 老师按班级隔离；老师只能读本班学生已判分考试摘要。
- 学生只能通过 Agent 看单个知识点的名称与上下级；知识点管理接口权限不变。
- 假模型也能跑通工具流程，无密钥可测试。

**Non-Goals:**

- 不做 AI 出题、判分、改分、改答案。
- 不做向量检索、跨学生记忆、长期性格总结。
- 不做老师专用智能体、第二套页面、外部工具协议。
- 不改考试、复习、报告、题库的既有业务规则；只增加 Agent 入口需要的权限例外。
- 不做多进程/多实例部署；checkpointer 的 SQLite 写并发按单机规模处理。

## Decisions

### 1. 用 `langchain.agents.create_agent` + LangGraph，不用 `langgraph.prebuilt.create_react_agent`

`create_react_agent` 在 LangGraph 1.x 已标废弃，源码里提示迁移到 `langchain.agents.create_agent`。`create_agent` 底层仍是 LangGraph，但自带 middleware、checkpointer、context schema，正好对应设计里的“中间件 + 循环”。

依赖按当前 PyPI 解析锁定：

```
langchain==1.5.2
langgraph==1.2.24
langgraph-checkpoint-sqlite==3.1.3
```

`pip install --dry-run` 与现有 `langchain-core==1.8.4` 可解析到一起；实际锁定前跑完整测试。备选是继续用 `langgraph.prebuilt.create_react_agent`，少一个 `langchain` 依赖，但走废弃接口，后续升级要再改一次，不选。

### 2. 图只编译一次，checkpointer 跟应用同一个 SQLite

在 `create_app` 的 lifespan 里建图，挂到 `app.state.agent`；`create_app(database_url)` 的临时库也拿到自己的 checkpointer。测试用 `InMemorySaver`，开发/演示用 `AsyncSqliteSaver`，落在同一个 `chemai.db`。

checkpointer 的表（`checkpoints`、`writes` 等）由框架管理，不进 Alembic，不进业务模型。备选是单独 `agent_checkpoints.db`，文件更干净，但破坏“一个 SQLite 文件拷走就能跑”的约束，不选。

图装配概念：

```
START
  |
  v
[pre_model: 场景提示 + 摘要压缩] --> [agent: 模型]
                                      |
                                      v
                              [tools: 十个工具]
                                      |
                                      +--> 回到 agent，最多 8 次模型调用
                                      |
                                      v
                              [post_model: 红线/收尾] --> END
```

### 3. 中间件分工

| 设计部件 | 实现 |
|---|---|
| 系统提示 | 自定义中间件在 `wrap_model_call` 里按场景生成四段提示，用 `request.override(system_message=...)` 替换；顺序固定为身份与范围、场景人设、四条红线、输出要求 |
| 历史压缩 | `SummarizationMiddleware(model=..., trigger=("messages", 30), keep=("messages", 20))`，摘要提示词用中文 |
| 循环上限 | `ModelCallLimitMiddleware(run_limit=8, exit_behavior="end")`，按模型调用次数卡 8 次 |
| 框架保险 | 每次调用仍传 `config={"recursion_limit": 100}`；带摘要/提示/工具节点时一轮约 5 步，100 足够跑完 8 轮，不直接把 8 当步数 |
| 输出检查 | `after_model` / `wrap_model_call` 检查红线话术；命中危险或羞辱表达时替换为中文拒绝加下一步 |

`ModelCallLimitMiddleware` 内置的收尾消息是英文，需要在输出层换成中文；同时确认摘要生成那次模型调用不占这 8 次，如果占就自定义计数中间件。

### 4. 线程编号与历史

| 身份 | 线程编号 |
|---|---|
| 学生 | `student:{user.id}` |
| 老师 | `teacher:{user.id}:class:{class_id}` |

线程编号由服务端从当前身份推导，客户端和模型都不能指定。历史接口从 checkpointer 读当前线程，只返回 Human/AI 的文字消息，过滤 ToolMessage、工具参数和调试字段。

老师按班级分线：切换班级就切一条线程，A 班与 B 班历史不混。备选是老师一人一条线，但多班上下文会串，不选。

同一线程用进程内 `asyncio.Lock` 串行化；上一轮未结束时新消息排队。单进程部署下够用；多进程不在这一版范围内。

### 5. 老师班级上下文与考试摘要

`ChatRequest` 增加 `class_id`（老师）与 `scene`。老师只带一个班时服务端自动补，带多个班时必须传；`require_own_class` 校验归属。学生传 `class_id` 返回 422。班级进入 `ChatContext`，工具从上下文读，工具签名里不出现班级编号。

老师看本班学生考试结果走新的服务函数，不复用学生作答接口：

1. `require_own_class(class_id, teacher, session)`。
2. 在本班范围内按姓名解析学生；同名时要求补充用户名，不猜。工具接受可选的 `student_username`，仍只在本班范围内校验。
3. 要求 `AnswerRecord.class_id == class_id` 且记录已判分、学生当前仍在班。
4. 只返回总分与每题对错。

不修改 `require_attempt_reader` / `list_attempts` 的现有语义；学生接口仍只允许本人与管理员。

### 6. 十个工具与复用

工具放在 `backend/app/agent_tools.py`，每个工具是带类型标注的函数，身份通过 `ToolRuntime[ChatContext]` 注入；工具内部从 `session_factory` 开短会话，调用 service 函数，捕获领域异常并转成中文结果。

| # | 工具 | 复用 | 需要补的 |
|:--:|---|---|---|
| 1 | 搜题 | `build_question_query`、`practice._approved_questions_for_point`、`schemas.question_pool_to_dict` | 把 `build_question_query` 从路由下沉到 service；补按知识点筛选 |
| 2 | 找知识点 | `knowledge.tree`、`knowledge.point_to_dict` | 新增 `find_point`，名称/别名匹配，匹配不到不猜 |
| 3 | 看学生画像 | `reporting.student_report` | 裁掉掌握度等不需要的字段，保持返回短 |
| 4 | 看知识地图 | `knowledge.tree` | 只取目标节点的父/子名称，不返回整棵树 |
| 5 | 讲错题 | `routes._wrong_questions_query`、`schemas.wrong_question_to_dict`、`practice._approved_questions_for_point` | 把错题查询下沉到 service；补同类题选择 |
| 6 | 看到期复习 | `review.list_tasks(scope="due")`、`review.task_to_dict`、`review.due_task_count` | 只取前几条并返回剩余数 |
| 7 | 布置练习 | `reporting.weak_report`、`practice.current_difficulty`、`practice.recent_question_ids`、`practice._approved_questions_for_point`、`practice._choose` | 新增 `pick_questions`，一次选一组，不写练习记录 |
| 8 | 加复习 | `ReviewTask`、`clock.business_today`、`LEVEL_MAX` | 新增 `review.add_manual_task`；级别 5 重置为 0 |
| 9 | 看考试结果 | `reporting.recent_scores`、`routes._attempt_detail`、`schemas.attempt_to_dict` | 老师路径新增服务函数；学生路径裁成总分 + 对错 |
| 10 | 看班级概况 | `class_reporting.class_overview`、`class_reporting.class_exams`、`reporting.class_knowledge_stats` | 裁掉整张学生表，只留知识点分布 + 学生人数 |

`_wrong_questions_query`、`_attempt_detail`、`build_question_query` 现在都在 `routes.py`；先下沉到 service 模块再让工具复用，避免 Agent 依赖 HTTP 层。工具失败返回中文“没找到/参数不合法/这一项没查到”，不抛异常。

### 7. 流式事件映射

`graph.astream_events(..., version="v2")`：

| 事件 | SSE |
|---|---|
| `on_tool_start` | `tool`，只发中文提示 |
| `on_chat_model_stream` 的正文分片 | `text` |
| 图结束 | `end` |
| 心跳 | SSE 注释 `: ping` |

过滤 `tool_call_chunks` 和工具节点内部片。设计要求工具事件先于正文；如果模型在工具调用前先产生正文，服务端缓存这段正文，等工具结果后再发，或者提示词明确“先查后答”。

### 8. 假模型与测试

当前 `FakeChatModel` 只有 `astream`，`create_agent` 需要能 `bind_tools` 的 `BaseChatModel`。改成 `BaseChatModel` 子类或用 `GenericFakeChatModel`，按关键词脚本化工具调用：

- “哪块弱” → 看学生画像
- “今天复习什么” → 看到期复习
- “给我出几道题” → 布置练习
- “为什么错” → 讲错题

测试覆盖工具选择、线程隔离、历史恢复、8 次上限、30→20 压缩、老师本班权限、学生知识点只读范围、手动加复习、题单练习。评测章需要每条用例独立线程；本章的线程隔离与测试用独立用户/临时库为其提供基础，不在这里写三十条用例。

## Risks / Trade-offs

- [框架版本升级导致 API 变化] → 锁定 `langchain`/`langgraph`/`langgraph-checkpoint-sqlite` 三个版本，升级时先跑完整测试与评测。
- [`ModelCallLimitMiddleware` 把摘要调用算进 8 次] → 落地先跑一条触发摘要的用例，确认计数；若算进去，改成自定义计数中间件。
- [工具事件晚于正文] → 流式层缓存工具调用前的正文，或提示词强制先查后答；用测试断言事件顺序。
- [SQLite checkpointer 写并发] → 单机单进程；同一线程串行；不支持多实例。
- [checkpointer 表混进业务库] → 文档注明框架表不归 Alembic 管；备份整个 `chemai.db` 即可；测试用 `InMemorySaver`。
- [老师同名解析歧义] → 要求补充信息，不猜；只在本班范围内列候选。
- [摘要质量差或假模型摘要写坏] → 中文摘要提示；假模型用确定性 summarizer；摘要失败不伪造。
- [旧测试仍按“无工具、无历史”断言] → 第 11 章的 agent-chat 测试同步改写；保留鉴权、防缓冲、心跳、中断不发 end 的测试。
- [学生知识点只读例外被误用成完整树读取] → 工具只返回单个节点的名称/别名/上下级，不返回题目数和整棵树；测试覆盖。

## Migration Plan

1. 安装并锁定 LangChain / LangGraph / SQLite checkpointer；现有依赖测试先跑绿。
2. 把 `build_question_query`、`_wrong_questions_query`、`_attempt_detail` 从 `routes.py` 下沉到 service，保持现有接口行为不变，先跑旧测试。
3. 新增 `agent_tools.py`、`ChatContext`、图装配与 checkpointer；`create_app` 挂 `app.state.agent`，保留旧 `chat_model_factory` 供测试过渡。
4. 改 `agent_routes.py`：`class_id`/`scene` 校验、线程推导、历史接口、`tool` 事件、8 次上限收尾。
5. 改前端：Chat 历史恢复、工具提示、老师班级选择器、场景入口；练习页题单模式；错题页“问一句”。
6. 新增/改写测试与三十条评测，跑 `doctor`、`check`、`npm run build`。
7. 回滚：代码回退到第 11 章路径即可；checkpointer 表是新增表，留在 `chemai.db` 不影响旧逻辑。

## Open Questions

- 假模型脚本覆盖多少种意图。先覆盖四类核心工具，评测用例再按需扩展。
