# Design

## Context

- 后端是 FastAPI + SQLAlchemy 2 + SQLite，所有接口集中在 `backend/app/routes.py`，判分规则在 `backend/app/answers.py`。`grade_record()` 逐题写 `is_correct`、算总分、把状态推进到 `graded` 后提交；交卷与重试判分都走它。
- 现有表只有题目、卷子、作答记录、逐题作答，迁移头是 `0003_exam`。没有复习任务、知识点、别名或题目关联表。
- 设计 00 要求时间统一按 UTC 存、显示转本地；到期日是本地日历日。设计 00 同时要求依赖单向：题库与考试不依赖复习。
- 测试每个用例一份临时库，用 Alembic 建结构；没有时间冻结库。前端是 React + antd，学生页目前各自渲染页头，没有全局导航。

## Goals / Non-Goals

**Goals:**

- 让判分产生的每道错题在判分事务内进入复习队列，不依赖后台任务或定时器。
- 用固定级别与间隔实现到期、升级、归零、出队；到期日按 UTC+8 业务日期计算，读取列表不修改任务。
- 复习作答复用考试判分函数，结果不回写考试数据。
- 提供两层知识点、别名、题目关联与合并的后端最小闭环，让弱项统计有可靠归类。
- 按固定错误率口径返回学生弱项前三，并区分无学习记录与无可用弱项。
- 学生复习页与报告弱项区块覆盖加载、空、正常、出错四态。

**Non-Goals:**

- 不做练习出题、难度升降、练习页；弱项统计暂不接练习记录。
- 不做班级报告、掌握度、最近五次分数、待复习数聚合。
- 不做知识点页 UI、AI 工具、通知或推送。
- 不按个人记忆曲线调参，不做后台定时任务；到期只在查询时判断。

## Decisions

### 1. 到期日存业务日期，不存时刻

新增 `review_tasks.due_on` 用 `Date` 列，表示 UTC+8 的业务日期；`created_at / answered_at / graded_at` 等事件时间仍用 UTC 时间戳。`business_today()` 固定按 UTC+8 计算，`business_date_of(dt)` 把任意时刻转成业务日期。

理由：设计只要求"今天/明天/几月几日"，到期列表按"今天及以前"筛选，逾期按天判断；存日期能避免 23:59 答错却要等到两天后才到期的问题，也不受 DST 影响。备选方案是存 UTC 时间戳再在查询时换算，但那会让"明天"在跨零点时依赖具体时刻，测试和显示都更复杂。

### 2. 四张新表

| 表 | 关键字段 | 约束 |
|---|---|---|
| `review_tasks` | `student_id`、`question_id`、`level`、`due_on`、`review_count`、`last_answer`、`last_answered_at`、`last_is_correct`、`last_wrong_answer`、`last_wrong_at`、`last_wrong_attempt_id`、`created_at`、`updated_at` | `(student_id, question_id)` 唯一；`due_on` 与 `student_id` 建索引 |
| `knowledge_points` | `name`、`parent_id`、`created_by`、`created_at`、`updated_at` | `name` 唯一；`parent_id` 自引用，最多两层 |
| `knowledge_point_aliases` | `knowledge_point_id`、`alias` | `alias` 全局唯一 |
| `question_knowledge_points` | `question_id`、`knowledge_point_id` | `(question_id, knowledge_point_id)` 唯一；两边建索引 |

`review_tasks` 同时保留"最近一次复习答案"和"最近一次复习答错"两组字段：前者用于复习页显示上次答案，后者为后续把错题来源扩展到复习留出数据，不在本次接口中暴露。

### 3. 判分完成用中立事件通知复习模块

在 `app/events.py` 放一个极小的进程内订阅表；`grade_record()` 在 `session.commit()` 之前发布 `attempt_graded`，`app/review.py` 在导入时订阅并把任务写入同一事务。题库与考试不 import 复习模块，依赖方向仍是复习读考试数据。

备选方案一是让 `grade_record()` 直接调用复习函数，简单但形成考试→复习的反向依赖。备选方案二是查询时惰性补建任务，虽然能避开依赖，但任务不在判分后立即存在，还要额外记录"这次判分是否已处理"，与"判分完成即入队"的要求不符。事件注册表只解决通知，不放业务规则。

### 4. 入队是 upsert，不是插入

对每道 `is_correct = false` 的逐题作答，按 `(student_id, question_id)` 找任务：

- 没有任务：建一条第 0 级、`due_on = 判分业务日 + 1`、`last_wrong_attempt_id = 本次作答记录`。
- 有任务且 `last_wrong_attempt_id` 不同：把级别重置为 0、到期日按本次判分重排、更新 `last_wrong_attempt_id`；不新增记录。
- 已出队（第 5 级）同样走重置。
- 同一份判分被重复通知时，`last_wrong_attempt_id` 相同，跳过，避免把刚升上去的级别误清零。

未判分或判分失败的记录没有 `graded` 状态，不会触发入队。入队失败会让整个判分事务回滚，记录停在"已交卷 + 空分"，沿用现有重试判分路径。

### 5. 级别与日期推进

间隔表按"作答后的级别"取：0 级 1 天、1 级 3 天、2 级 7 天、3 级 14 天、4 级 30 天、5 级出队。

| 本次结果 | 新级别 | 新到期日 |
|---|---|---|
| 答对，原级别 0–3 | 原级别 + 1 | 本次作答业务日 + 新级别间隔 |
| 答对，原级别 4 | 5 | 无（出队） |
| 答错，任意级别 | 0 | 本次作答业务日 + 1 |

答对第 0 级用第 1 级的 3 天，不是第 0 级的 1 天；这是最容易被写成"按旧级别取间隔"的地方。逾期只影响到期列表的排序，不参与级别计算；级别只在作答时变化。

### 6. 复习作答用乐观并发

复习作答先读任务并计算新级别、新到期日，再用 `WHERE id = ? AND review_count = ?` 的条件更新，同时 `review_count = review_count + 1`。更新行数为 0 说明另一个请求已经改过这条任务，返回 400 让客户端刷新，不重试、不叠加升级。

用 `review_count` 而不是级别做版本号，是因为第 0 级答错时级别不变，只看级别无法区分并发。顺序到达的两次作答会读到新版本并各自成功，满足"同一天答两次照常升级"。

### 7. 复习作答不改考试数据

复习作答只更新 `review_tasks` 的级别、到期日、最近答案、复习次数，不写 `answer_items / answer_records`，不改考试分数，也不更新错题清单。判分直接调用 `judge_answer()`，保证单选、多选、填空的比较规则与考试一致。响应里的"上次答案"在覆盖前从任务读出；第一次作答时为 `null`。

### 8. 知识点用三张表表达两层树

`knowledge_points.parent_id` 为空是根，指向根是第二层；创建时校验上级必须是根，从结构上禁止第三层。名称和别名共用一套全局唯一检查：写入前把名称、别名都去首尾空白，再与 `knowledge_points.name` 和 `knowledge_point_aliases.alias` 的并集比较。改名时把旧名称写进别名表，避免旧叫法变成无主词。

合并 `source → target`：

1. 校验 `source != target`。
2. 校验 `target` 不是 `source` 的下级。
3. 若 `source` 有子节点且 `target` 本身是子节点，拒绝——把子节点挂到子节点下会产生第三层。设计 03 只写了"子节点改挂到目标"，没有覆盖这个组合；这里补一条 400，宁可不合并也不破坏两层约束。
4. 把 `source.name` 和 `source` 的别名并入 `target` 的别名，重复的跳过。
5. 把题目关联改为 `target`，重复关联去重。
6. 把 `source` 的子节点改挂到 `target`。
7. 删除 `source`。

统计只读 `question_knowledge_points`，合并不需要重算缓存，下一次查询自然按目标节点汇总。

### 9. 弱项统计一次分组查询，Python 里排序取前三

一次 `answer_items JOIN answer_records JOIN question_knowledge_points JOIN knowledge_points` 的分组查询，按知识点算 `count(*)` 与 `sum(is_correct = false)`，过滤 `answer_records.status = 'graded'`、`is_correct IS NOT NULL`、学生本人。把分组结果取回后在 Python 里：

- 丢弃作答数小于 2 的知识点；
- 按错误率降序、作答数降序、知识点 ID 升序排序；
- 取前三；
- 用 `Decimal` 做 `ROUND_HALF_UP`，错误率转成百分比并保留一位小数。

`has_data` 单独查一次"该学生是否有任何已判分逐题作答"：没有就是"还没有学习记录"；有但分组为空或全被门槛过滤，就是"暂无可统计的弱项"。统计不落表、不缓存。

练习接入时的扩展点在查询的"作答事实"层：现在事实只来自考试，未来把练习记录投影成同样的 `(student_id, question_id, is_correct)` 再合并即可，不改上层排序与门槛。

### 10. 接口与角色

| 接口 | 作用 | 角色 |
|---|---|---|
| `GET /api/review/tasks?scope=due\|all` | 到期列表 / 全部任务（含已出队）；`due` 默认 | 学生看自己；管理员看全部；老师 403 |
| `POST /api/review/tasks/{id}/answer` | 复习作答 | 仅任务所属学生；老师、管理员 403 |
| `GET /api/knowledge-points` | 两层树，带别名与题目数 | 老师、管理员；学生 403 |
| `POST /api/knowledge-points` | 建节点 | 老师、管理员 |
| `PUT /api/knowledge-points/{id}` | 改名称、整体替换别名 | 老师、管理员 |
| `POST /api/knowledge-points/{id}/merge` | 合并到目标 | 老师、管理员 |
| `PUT /api/questions/{id}/knowledge-points` | 整体替换一道题的关联 | 题目创建者；管理员任何题；他人题 403 |
| `GET /api/reports/weak?student_id=` | 弱项前三 | 学生看自己；管理员必须指定学生；老师 403 |

全部沿用 `{success, data, error}` 信封和现有中文错误文案；新增错误只用 400/403/404，不引入新的状态码。

### 11. 前端两个新页面与入口

- `/student/review`：顶部 `Tabs` 两个页签。"今日到期"用 `GET /api/review/tasks?scope=due`；"全部错题"用现有 `/api/wrong-questions`，并同时取 `scope=all` 的任务列表，在前端按 `question_id` 合并出"是否在复习队列"。在队列里的条目可以进入答题态；已出队或没有任务的条目只读展示，因为设计只允许 AI 手动加复习，不给学生手动重入队。
- 答题态一题一屏：题干、题型、选项/输入框；提交后显示对错、学生答案、标准答案、解析、上次答案、新级别与下次到期日。答完刷新两个列表并回到当前页签。
- `/student/report`：只做弱项前三区块。`has_data=false` 显示"还没有学习记录"并给去考试的按钮；`has_data=true` 且列表为空显示"暂无可统计的弱项"；有数据用表格显示知识点、作答数、错题数、错误率（一位小数）。
- 两个页面各自处理加载、空、正常、出错四态，出错给重试按钮。学生页头加"复习""学习报告""考试"三个入口，避免新页面只能靠手输 URL。

### 12. 迁移与历史数据

新增 Alembic `0004_review_knowledge`：

1. 建四张表、唯一约束和索引。
2. 回填历史复习任务：扫 `status = 'graded'` 且 `is_correct = false` 的逐题作答，按 `(student_id, question_id)` 取判分时间最晚的一条，插一条第 0 级任务，`due_on = 该条判分的业务日 + 1`，`last_wrong_attempt_id` 指向该条作答记录。
3. 回填只新增任务，不修改现有题目、卷子、作答与分数；旧的复习答对/答错历史不存在，`review_count` 从 0 开始、`last_answer` 为空。

回填让迁移前已经错过的题也能进入复习，代价是升级后列表里可能一次出现多条逾期任务；设计要求逾期不惩罚，这是可接受的状态。`downgrade` 只删除四张新表，现有数据不受影响。

### 13. 测试策略

- 后端用现有 `TestClient` + 每用例临时库，新增 `test_review_tasks.py`、`test_knowledge_points.py`、`test_weak_report.py`。
- 把 `test_wrong_questions.py` 里建卷、发布、取作答、交卷的流程提到 `exam_helpers.py`，三个新测试文件复用。
- 到期日断言用 `business_date_of(graded_at) + 1` 计算期望值；需要固定"今天"的用例 monkeypatch `app.clock.business_today`，不引入新依赖。
- 迁移回填单独一个测试：用 Alembic 升到 `0003_exam`，直接插一条已判分错误作答，再升到 head，断言生成一条第 0 级、逾期或次日到期的任务。
- 前端用 `npm run lint && npm run build`，不引入组件测试框架；四态与交互走手工验收。

## Risks / Trade-offs

- **固定 UTC+8** → 部署到其他时区时"今天"会错位。缓解：时区只在 `app/clock.py` 一处定义，测试与显示都走它；将来要支持多时区只改这里。
- **进程内事件订阅表** → 如果复习模块没有被导入，判分会静默不入队。缓解：`routes.py` 导入复习模块，并加一条"交卷后立即能查到任务"的集成测试；事件表不缓存业务状态。
- **入队放进判分事务** → 判分失败面变大。缓解：入队失败整体回滚到"已交卷 + 空分"，重试判分可重新触发，测试覆盖入队异常。
- **回填产生大量逾期任务** → 老学生一打开看到很长列表。缓解：按设计逾期不惩罚、按到期日排序；不做通知，不主动推。
- **合并的两层保护是补充规则** → 设计 03 没写"源有子节点且目标是子节点"的情况。缓解：在 spec 中明确返回 400，页面后续按错误文案提示换目标，不静默产生三层。
- **弱项暂不接练习** → 与设计 03 §4.5 的最终口径有差距。缓解：排序与门槛不写死在 SQL 里，练习落地时只扩"作答事实"来源；本次在提案和验收里写明这是分阶段落地。
- **SQLite 并发能力有限** → 复习并发用条件更新保证单条任务只升一次，但高并发下后到请求会收到 400。缓解：前端提交时禁用按钮，错误提示刷新后重试。
- **"全部错题"合并两个接口** → 任务接口失败时无法显示队列状态。缓解：错题列表仍可显示，队列标记区域单独报错并给重试，不让整页空白。
- **管理员不能代答** → 与管理员"全通"的直觉不同。缓解：与考试模块"管理员不能代替学生交卷"保持一致，管理员只读任务用于排障。

## Migration Plan

1. 合并代码后先在 `backend/` 执行 `../.venv/Scripts/python.exe -m alembic upgrade head`；`scripts/dev.sh` 已把这一步放在启动前。
2. 迁移先建表再回填；回填失败时整个迁移回滚，数据库停在 `0003_exam`，应用不要启动。
3. 回滚用 `alembic downgrade 0003_exam`，只丢四张新表；题目、卷子、作答、分数保持原样。
4. 迁移后知识点为空，弱项报告显示"还没有学习记录"或"暂无可统计的弱项"；老师需要先建知识点并给题挂上，才有弱项数据。验收脚本需覆盖这一步。

## Open Questions

- 知识点写入是否要在后续章节对学生或 Agent 开放只读查询？本次只给老师与管理员，等 Agent 章节再按工具需要扩展。
- 练习记录接入弱项后，"最近 20 条排除窗口"等练习规则是否影响统计口径？不影响错误率定义，等练习章节确认。
