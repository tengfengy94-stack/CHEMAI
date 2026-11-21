# Design

## Context

后端是 FastAPI + SQLAlchemy + SQLite，表结构只由 Alembic 迁移创建；接口统一走 `{success, data, error}` 信封，权限分登录校验、归属判断、查询过滤三层。现有 `Question` 已有草稿/待复核/已通过三态，`Class` 记录班主任，`User` 记录学生班级；`routes.py` 里的 `papers_using_question` 还是恒返回 0 的占位实现，注释已写明组卷章节必须先替换它。前端是 React 19 + Ant Design + Vite，已有老师题库页、学生考试占位页和统一 `request()` 封装。

本设计只解决 proposal 里“题 → 卷 → 发布 → 作答 → 判分”的主链路；动机见 `proposal.md`，行为契约见 `specs/exam/spec.md`。

## Goals / Non-Goals

**Goals:**

- 用四张新表承载卷子、卷内题目、作答记录、逐题作答，并用唯一约束守住“一题一卷一次、一人一卷一条”。
- 用条件更新、条件 DML 和两段提交实现：并发交卷只有一个请求收下答案；发布与加题/减题互斥；判分失败时答案不丢、分数不写半截。
- 明确所有非法状态转移返回 400 的中文拒绝语义，并与现有 403/404/422 分工。
- 两个页面覆盖老师组卷/发布和学生列表/作答/结果三态。

**Non-Goals:**

- 不做班级报告、成绩统计、错题本页面；逐题作答数据可供后续章节读取，但本次不开放对应页面。
- 不改题目审核状态机，不改题库删除接口现有的 409 语义。
- 不做撤回发布、重考、限时、自动交卷、拖动排序、答案草稿保存、主观题与多空填空。
- 不做发布记录/考试场次对象；一次发布只体现为“给这个班补建了哪些作答记录”。

## Decisions

### Decision 1: 四张表，不建发布表、成绩表、错题表

| 表 | 关键字段 | 约束与说明 |
|---|---|---|
| `papers` | `id`, `title`, `created_by`, `status`, `created_at` | `status` 只有 `draft` / `published`；`created_by` 存用户名，沿用 `Question.created_by` 的写法 |
| `paper_questions` | `id`, `paper_id`, `question_id`, `position` | `UNIQUE(paper_id, question_id)` 守住一题只出现一次；`UNIQUE(paper_id, position)` 守住顺序不重复；按 `position` 升序读取 |
| `answer_records` | `id`, `paper_id`, `student_id`, `class_id`, `status`, `score`, `started_at`, `submitted_at`, `graded_at`, `grading_started_at`, `created_at` | `UNIQUE(paper_id, student_id)` 守住一人一卷一条；`class_id` 是发布时的班级快照；`score` 可空；`grading_started_at` 是交卷/重试判分的租约，不是状态 |
| `answer_items` | `id`, `record_id`, `question_id`, `position`, `student_answer`, `is_correct` | `UNIQUE(record_id, question_id)` 守住每题一条；交卷时未答的题写空串；`is_correct` 判分前为空 |

理由：

- **发布不需要独立表。** 发布的效果就是一组作答记录；记录的 `class_id` 已经回答了“这次发给了哪个班”。再加发布表，作答记录仍要存班级，反而多一处可能对不上的数据。
- **成绩不需要独立表。** 总分写在作答记录上，逐题对错写在逐题作答上；拆成绩表每次查分都要再关联一次。
- **错题不需要独立表。** 判分时把 `answer_items.is_correct` 写成假，错题就是一次查询；另存一份会出现两处不一致。
- **班级快照放在作答记录上。** 学生转班后不改这条记录，班级统计才不会在事后变掉。同一份卷子发给两个班，得到两批各自带班级的记录。

`answer_records.class_id` 与 `paper_id`、`student_id` 都建外键；`paper_questions.question_id` 建外键，配合 `PRAGMA foreign_keys=ON` 作为“被卷子用过的题不能删”的最后一道保险。

**记录不变量（实现和测试都必须守）**：

- `pending` / `in_progress` / `submitted` 的 `score` MUST 为 `NULL`；`graded` 的 `score` MUST 非空。`0.0` 是合法分数，`NULL` 不是 0。
- 判分前所有 `answer_items.is_correct` MUST 为 `NULL`；`graded` 后 MUST 全部非空。
- `started_at` 从 `in_progress` 起非空；`submitted_at` 从 `submitted` 起非空；`graded_at` 只在 `graded` 时非空；三个时间 MUST 单调递增。
- `grading_started_at` 在交卷判分或重试判分进行时非空；判分成功或失败后 MUST 清空（失败时用独立清理事务）；租约过期只表示可被下一次重试覆盖，不要求后台清理。
- 状态值不属于四种枚举时 MUST 拒绝，MUST NOT 落进任何默认放行分支。

### Decision 2: 发布是 `(卷子, 班级)` 上的幂等操作

发布接口接收 `class_id`。整个操作在一个写事务里完成：

1. 校验卷子归属：老师只能发布自己的卷子，管理员不受限。
2. 若卷子还是 `draft`，先抢状态：`UPDATE papers SET status='published' WHERE id=:id AND status='draft'`。这是发布与加题/减题之间的互斥点；若卷子已是 `published`，跳过这一步；若正好被另一个发布请求抢先，抢不到也按“再发布”路径继续。
3. 校验班级归属：老师只能发布自己带的班（`require_own_class`）。
4. 班级当前学生数为 0 → 400「该班还没有学生」；回滚第 2 步的状态变更。
5. 卷子没有任何题 → 400「卷子里还没有题」；回滚第 2 步的状态变更。
6. 查出该班当前学生（`role='student'` 且 `class_id=:class_id`），按 `(paper_id, student_id)` 插入缺失的作答记录；已有记录跳过。
7. 提交事务。若第 2 步抢到了状态，卷子从这里开始对内容只读。第 3–5 步任一失败，整个写事务回滚，包括第 2 步的状态变更。

**为什么先抢状态再校验**：如果先查题目数再改状态，发布和减题并发时可能都通过 `draft` 检查，最后发出空卷。先做一次条件更新拿到写锁，后面的加题/减题必须用条件 DML（`... WHERE EXISTS (SELECT 1 FROM papers WHERE id=? AND status='draft')`）或在同一个 `BEGIN IMMEDIATE` 事务里检查，才能保证“发布那刻的内容集合”不再变。已发布卷子的内容本来就不可变，再发布不需要抢内容锁。

**加题/减题同样要防并发**：`position` 取 `max(position)+1`，不能取 `count`（减题会留空位）；两个加题请求撞上 `UNIQUE(paper_id, position)` 时，重算位置重试一次，不要直接返回 500。

插入用 SQLite 的 `INSERT ... ON CONFLICT(paper_id, student_id) DO NOTHING`，并用 `rowcount` 统计实际新增条数。本机 SQLite 3.53 + SQLAlchemy 2.x 实测：三行 upsert 中一行冲突时 `rowcount=2`，单行冲突时 `rowcount=0`，所以 `created` 计数可用。前提是使用 dialect 的 `sqlite_insert(...).on_conflict_do_nothing(...)`，不能用 `session.add_all` 后捕 `IntegrityError`——那会让整个事务失效，第二个请求变成 500。返回的 `skipped` 按本次名单中已有记录的当前学生数计算（`len(roster)-created`）；已转出的学生不在本次名单里，不计入 `skipped`。错误路径不提交事务，必要时显式 `rollback()`。

**“幂等”的准确含义**：重复调用不会为同一 `(paper_id, student_id)` 产生第二条记录，也不会删除已有记录；它不是“班级名单同步”。新转进的学生会被补建，转出的学生记录保留，已在其他班有该卷记录的学生会被跳过且班级归属不变。

**发布后仍可再发布**：卷子已是 `published` 时，第 2 步不执行，不改变状态；仍然可以给另一个班、或给班里新转进的学生补记录。这与“发布后内容只读”不冲突：锁定的是内容，不是发给谁。

**班级当前 0 人但历史上有记录**：仍按空班返回 400「该班还没有学生」，不删除任何历史记录。这是“空班不能发布”的直接结果，spec 已写死。

### Decision 3: 状态机在路由层显式判定，非法转移返回 400

**卷子转移表**：

| 当前状态 | 加题/减题 | 发布 |
|---|---|---|
| `draft` | 200，状态不变 | 200 → `published`；空卷/空班 400，状态不变 |
| `published` | 400，状态不变 | 200，状态保持；只补缺；空班 400 |

**作答记录转移表**：

| 当前状态 | 开始 | 交卷 | 重试判分 | 读取 |
|---|---|---|---|---|
| `pending` | 200 → `in_progress` | 400 | 400 | 卷子元数据，不下发题目 |
| `in_progress` | 200，状态保持（继续） | 200 → `submitted`，随后判分 | 400 | 题目，不含答案与解析 |
| `submitted` + `score IS NULL` | 400 | 400（重复交卷） | 200 → `graded`；判分进行中 400 | 题目 + 自己的答案，不含标准答案 |
| `submitted` + `score NOT NULL` | 400 | 400 | 400 | 不应存在，按 500 处理 |
| `graded` | 400 | 400 | 400 | 完整结果 |

**能触发转移的人**：

| 转移 | 触发者 |
|---|---|
| `draft → published` | 卷子所属老师；管理员可操作卷子 |
| `pending → in_progress` | 记录所属学生 |
| `in_progress → submitted` | 记录所属学生 |
| `submitted → graded` | 系统，由所属学生的交卷或重试请求触发 |

老师、管理员 MUST NOT 代替学生开始或交卷。管理员可以读全部记录。

状态推进用条件更新兜底：

```sql
UPDATE answer_records
SET status = 'in_progress', started_at = COALESCE(started_at, :now)
WHERE id = :id AND status IN ('pending', 'in_progress');

UPDATE answer_records
SET status = 'submitted', submitted_at = :now, grading_started_at = :now
WHERE id = :id AND status = 'in_progress';
```

`rowcount == 0` 时重新读状态：`pending` 或 `graded` → 400；`submitted` → 400「已经交过了」。交卷请求不再从 `submitted` 走重试；重试只走独立入口。

**400 与其他状态码的分工**：

- 400：状态机非法转移、空卷、空班、答案里的题不属于这份卷子等业务规则。
- 403：不是自己的卷子、不是自己带的班、不是自己的作答记录；管理员代替学生开始/交卷。
- 404：卷子、班级、作答记录不存在。
- 422：请求体字段格式不对。Pydantic 在进入路由前校验，所以格式错误优先 422，不进入状态机判定。

题目审核的现有接口仍用 409，本次不改；考试流程按用户要求统一用 400。两套语义在各自模块内保持一致。

### Decision 4: 交卷与重试判分分开，两段事务保住“判分失败”回路

**交卷**只在 `in_progress` 被接受，分两段事务：

1. **收答案事务**：条件更新 `in_progress → submitted`，同时写 `submitted_at`、`grading_started_at=now`；然后为卷内每道题写一条 `answer_items`。请求里没提供的题写空串；请求里出现不属于这份卷子的题、或重复的 `question_id`，整个请求 400，不落任何答案。提交。
2. **判分事务**：用已落库的答案在内存里逐题比较，写入每条 `is_correct`，再写 `score`、把状态推到 `graded` 并清空 `grading_started_at`。这几步在同一个事务里，要么全成，要么全回滚。

判分事务失败时，第一段事务已经提交，所以答案还在、状态停在 `submitted`、`score` 仍为 `NULL`。随后用一个清理事务把 `grading_started_at` 置空；清理也失败时，租约到期后自动可重试。学生看到“答案已收，判分没完成”。

**重试判分**走独立入口 `POST /api/attempts/{id}/retry-grading`：

- 只接受 `submitted` 且 `score IS NULL`；
- 先抢租约：`UPDATE ... SET grading_started_at=now WHERE status='submitted' AND score IS NULL AND (grading_started_at IS NULL OR grading_started_at < :lease_cutoff)`；
- `rowcount=0` 时返回 400「判分正在进行」或「没有可重试的判分」；
- 抢到租约后只重跑判分事务，不读请求体里的答案；
- 成功或失败后清空 `grading_started_at`。

交卷和重试使用不同的入口后，另一个窗口的重复交卷看到 `submitted` 会直接 400，不会滑进重试路径。

**为什么不用一个事务**：一个事务里判分失败会把答案一起回滚，学生得重填整份卷子；设计要的是答案保留、只重判。
**为什么不用后台任务**：异步会多出“判分中”状态、轮询和超时处理；设计明确要求交卷同一次请求内出分。`grading_started_at` 只是判分租约，不改变四态。
**为什么需要租约**：如果两个重试同时判分，虽然答案只读、结果确定，会重复写 `is_correct` 和 `score`，还可能触发 SQLite 锁竞争。租约让后到的重试返回 400；进程崩溃时租约到期，记录仍可重试。

**响应一致性**：判分失败后返回前重新读一次记录。如果并发重试已经把记录判成 `graded`，首个交卷请求返回已判分结果，不返回过期的 `submitted` 快照。

### Decision 5: 判分比较放在 `answers.py`，与建题共用同一套规范化

在现有 `answers.py` 增加比较函数，不另起一套：

- 单选：`student.strip() == standard.strip()`，按设计只去首尾空白，大小写敏感。
- 多选：去掉空白与分隔符、转大写、按字母升序，比较集合是否完全相等；空集、含非字母、字母超出选项范围一律判错。漏选、多选都不得分。
- 填空：`unicodedata.normalize("NFKC", text)` 把全角转半角，再用正则去掉所有空白，最后原文比较；大小写敏感。

总分用 `Decimal` 做 `ROUND_HALF_UP` 保留一位小数，再存成浮点数。不用 Python 内置 `round()`，因为它是银行家舍入，遇到 `6.25` 会得到 `6.2`，与“保留一位小数”的日常预期不一致。`score` 为 `NULL` 表示未判分，`0.0` 表示判了零分，两者在序列化和前端显示上必须分开。

### Decision 6: 接口面

老师端：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/papers` | 自己创建的卷子列表（管理员全部）；含题目数、状态、创建时间 |
| `POST` | `/api/papers` | 新建草稿卷，只收标题；标题创建后不改 |
| `GET` | `/api/papers/pool` | 组卷题目池：自己创建的已通过题，可按难度、关键词筛选；只返回 `id/stem/type/difficulty` |
| `GET` | `/api/classes` | 发布弹窗用：老师自己带的班（含学生人数）；管理员全部班级 |
| `GET` | `/api/papers/{id}` | 卷子详情与卷内题目；已发布也只读返回 |
| `POST` | `/api/papers/{id}/questions` | 加题；仅草稿；重复加返回 200 且不新增 |
| `DELETE` | `/api/papers/{id}/questions/{question_id}` | 减题；仅草稿；不在卷内返回 404 |
| `POST` | `/api/papers/{id}/publish` | 发布给一个班；返回 `{created, skipped}`；已发布卷子也可调用 |

`/api/papers/pool` 必须注册在 `/api/papers/{id}` 之前，避免被路径参数吞掉。

学生端：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/attempts` | 自己的作答记录列表；管理员可看全部 |
| `GET` | `/api/attempts/{id}` | 自己的记录详情；按状态决定题目字段 |
| `POST` | `/api/attempts/{id}/start` | 首次开始或继续；返回记录详情（含题目）；交卷后调用返回 400 |
| `POST` | `/api/attempts/{id}/submit` | 只接受 `in_progress`；收答案并同步判分；`submitted`/`graded` 返回 400 |
| `POST` | `/api/attempts/{id}/retry-grading` | 只接受 `submitted + score=NULL`；只重判，不读答案；判分进行中 400 |

**不提供通用判分接口**。判分只能由交卷或重试判分触发，从入口上排除“没作答就判分”。

详情接口的字段随状态变化：

- `pending`：只返回卷子标题、状态、时间，不返回题目；学生必须先开始。
- `in_progress`：题目含 `id/position/stem/type/options`，不含标准答案与解析。
- `submitted`（分数为空）：同上，另加学生自己的答案与 `grading_in_progress` 布尔值（租约未过期时为真）；仍不含标准答案与解析。
- `graded`：题目另加 `answer/explanation/is_correct`，记录带 `score`。

交卷请求体为 `{ answers: [{question_id, answer}] }`。`question_id` 必须属于这份卷子且不能重复；未提供的题由服务端补空串。答案按字符串保存，前端和服务端都把单题答案限制在 500 字以内。

### Decision 7: 用真实卷子查询替换 `papers_using_question`

新实现统计 `paper_questions` 里该题当前出现的不同 `paper_id` 数量，草稿卷和已发布卷都算。这里的“用过”按**当前仍在某份卷子里**解释，不按“历史上加过一次”解释：

- 题加入草稿卷后，只要还在卷子里，就不能删；
- 从草稿卷减题后，若不再被任何卷子引用，可以删除——这份卷子还没发布，没有历史作答会失准；
- 已发布卷子的内容只读，题不可能被减掉，所以历史作答永远对得上题目；
- 现有题库删除接口的 409 提示“这道题已被 N 份卷子使用”开始有意义。

这与设计 02 §4.3“进过就不能删”的字面表述有差异；按历史作答完整性取“当前引用”，避免为未发布的草稿卷维护使用流水。如果以后要做题目审计，再加使用流水表。

`paper_questions.question_id` 的外键是第二道保险；即使路由检查被绕过，数据库也会拒绝删除被引用的题。

### Decision 8: 前端两个页面，按状态隐藏非法动作

**老师组卷页 `/teacher/exams`**：

- 列表：自己的卷子、状态标签、题目数；新建卷子弹窗只收标题。
- 草稿工作区：左侧题目池（已通过、可按难度/关键词筛），右侧已选题目；加入、移除；题目顺序即加入顺序，不做拖拽。
- 发布弹窗：只列自己带的班，显示每个班的学生人数；确认后显示新增/跳过条数；请求在途时禁用确认按钮，避免连点。
- 已发布卷子：详情只读，加题、减题、发布按钮消失；列表行保留“再发布”动作，用于发给另一个班或补新转进的学生。这样既守住“编辑页只读”，又不丢掉 §4.5 的再发布能力。
- 题库页和组卷页互相给一个入口链接；当前应用没有全局导航，先在页头放按钮。

**学生考试页 `/student/exams`**：

- 列表态：一条记录一行，状态标签；动作按状态给：待作答“开始作答”、作答中“继续作答”、已交卷且 `grading_in_progress` “判分中”、已交卷且不在判分“判分没完成 + 重试”、已判分“查看结果”。
- 作答态：一题一块；单选 Radio、多选 Checkbox、填空 Input；顶部“已答 x / 共 n”；交卷确认框写明未答题数，白卷再确认一次；顶部提示“答案在交卷时统一提交，请不要刷新”。
- 交卷按钮在请求在途时禁用。收到 400「已经交过了」时不只弹错误：重新拉一次记录，已判分就直接展示结果，未判分就显示“判分中/重试”。
- 结果态：总分按一位小数显示；逐题显示自己的答案、标准答案、解析、对错；没有解析显示“暂无解析”。
- 已判分记录不再显示交卷/重试动作；服务端仍然兜底拒绝。
- 重试按钮只在 `submitted + 空分 + grading_in_progress=false` 时出现；请求在途时禁用；收到 400「判分正在进行」时重新拉记录，不重复弹同一个错误。

前端所有错误直接展示服务端 `error` 文案；400 的中文原因就是给学生/老师看的。按钮该消失就消失，不靠“点了再报错”。

### Decision 9: 测试策略

后端沿用 pytest + 每测试独立临时库 + Alembic 建表：

- 状态机矩阵逐格测试：允许的边成功，状态保持操作返回 200，非法边 400 且数据不变；未知状态默认拒绝。
- 发布：空卷、空班、别班 403、重复发布 0 新增、第二个班独立记录、转班后班级快照不变；转出学生记录保留、转入只补一条、已在别班有记录时跳过；并发发布最终每人一条；发布与减题并发不得产生已发布空卷。
- 交卷：未开始 400、正常收答案、未答记空、白卷 0.0、已交卷/已判分重复交 400；用慢判分钩子让第一个请求停在判分阶段，断言第二个交卷返回 400 且答案不被覆盖。
- 判分：三种题型的比较规则、总分公式与一位小数、100.0、空分为 `NULL` 不是 0。
- 判分失败：让判分函数抛错，断言状态 `submitted`、分数空、答案还在、`grading_started_at` 被清理；重试只重判且答案不变。
- 重试并发：两个重试同时到达只有一个 200，另一个 400；租约过期后可以再次重试；已有分数的记录重试 400。
- 组卷并发：两个加题请求不会因为 `position` 冲突变成 500；减题后再次加题位置正确。
- 权限：老师操作他人卷子 403、学生看他人记录 403、管理员可读但不可代替学生开始/交卷。
- 题库联动：题加入草稿卷后删除返回 409 并给出份数；从草稿卷减掉后可删除。
- 错误优先级：格式错误返回 422，状态非法返回 400，测试不混淆两者。

前端以 `npm run build`、`npm run lint` 和开发服务器手工走查为主；不引入新的 UI 测试依赖。

## Risks / Trade-offs

- **[两段事务之间的窗口]** 交卷后、判分完成前，记录会短暂处于 `submitted` 且分数为空。按设计这是合法中间态，页面根据 `grading_in_progress` 显示“判分中”，租约过期后才显示“判分没完成 + 重试”；统计类代码后续必须跳过空分数，不能按 0 算。→ 在序列化层明确 `None`，测试覆盖空分与 0.0 的区分。
- **[重试租约过期]** 判分进程崩溃后，学生最多等待一个租期才能重试；租期过长影响体验，过短可能让两个判分重叠。→ 取 60 秒，页面提示稍后重试；测试覆盖租约过期后可重试。
- **[发布与内容修改互斥依赖条件 DML]** 只在路由层检查 `draft` 仍可能被并发绕过；必须用条件更新/条件 DML 或 `BEGIN IMMEDIATE` 把检查和写入放进同一个写事务。→ 测试覆盖发布与减题并发不产生空卷。
- **[422 优先于 400]** 请求体格式错误在进入路由前就被 Pydantic 拦下，会返回 422 而不是 400。→ spec 已写明优先级；测试分别断言 422 与 400，不把两者混为一谈。
- **[SQLite 并发能力有限]** 两个进程同时写会排队；条件更新能防重复交卷，但不能提供行级锁。当前单机部署足够。→ 所有状态推进都用 `WHERE status = ...` 条件更新，不只依赖先读后写。
- **[班级快照会与当前班级不一致]** 学生转班后，旧记录仍算原班。这是设计要的“成绩不被转班改写”。→ 统计一律读 `answer_records.class_id`，不关联学生当前 `class_id`。
- **[发布后仍可再发布]** 老师可能把同一份卷子误发给多个班，系统没有撤回。→ 发布确认框显示班级人数；重复发布幂等；撤回留到后续版本。
- **[答题不保存草稿]** 刷新页面会丢答案，容易被学生投诉。→ 作答页顶部提前写明，交卷确认框再提示未答数量；不引入自动保存接口。
- **[400 与题库模块的 409 不一致]** 同一系统里两种冲突语义并存。→ 这是本次用户明确要求；在路由层按模块区分，测试里写死期望状态码，避免以后被“统一”掉。
- **[现有测试会红]** `test_usage_reports_zero_papers` 等测试假设没有卷子表。→ 新迁移后更新相关测试，改成真实加入卷子再断言份数。

## Migration Plan

1. 新增 Alembic 迁移 `0003_exam.py`，按 `papers → paper_questions → answer_records → answer_items` 顺序建表；`answer_records` 包含 `grading_started_at`；`downgrade` 反序删表。
2. 不迁移任何旧数据；现有题目、账号、班级不动。
3. 部署顺序：先执行迁移到 head，再启动新后端。旧后端不认识新表，不影响运行；新后端缺表会直接报错，所以迁移必须先跑。
4. 回滚：`alembic downgrade 0002_auth` 只删四张新表，不碰题目数据。回滚后前端考试入口应同步下线，否则请求会 500。

## Open Questions

无。发布与内容修改的互斥、交卷与重试拆分、`papers_using_question` 的“当前引用”语义都已定下；没有留到实现阶段再猜的决策。
