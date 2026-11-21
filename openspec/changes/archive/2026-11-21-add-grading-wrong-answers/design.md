# Design

## Context

判分链路已经在 ch05 完成：`backend/app/answers.py` 的 `judge_answer` 与 `score_for` 负责三种题型的比较和总分，`backend/app/routes.py` 的 `grade_record` 在交卷请求内把逐题对错、总分和 `graded` 状态写在同一个事务里；判分失败时答案保留、状态停在 `submitted`、`score` 为 `NULL`，重试只重跑判分。现有 `answer_items` 已经保存每题的学生答案与 `is_correct`，`answer_records` 保存 `student_id`、`paper_id`、`class_id`、状态和交卷时间。因此本次不需要改判分引擎，也不需要新表。

约束来自设计 02：错题不是一份新记录，而是逐题作答里答错的那部分（§2）；错题按题去重、显示最近一次答错的答案和来源、按最近答错时间倒序（§4.8）；错题的可见范围和结果一致（§4.8、§4.9）。设计 05 又规定考试页是一页三态，错题列表最终属于复习页的「全部错题」页签。本变更的动机见 `proposal.md`，行为契约见 `specs/exam/spec.md`。

## Goals / Non-Goals

**Goals:**

- 用一个只读查询从现有作答数据得到跨卷子的错题清单，按题去重，保留最近一次答错的答案、来源和时间。
- 在已判分结果态增加「看错题」动作，同时保留既有「查看结果」，并覆盖加载、空、出错三种界面状态。
- 用测试固定判分基线不变：三种题型规则、总分公式、已交卷到已判分的转移与失败重试仍按 ch05 的行为工作。

**Non-Goals:**

- 不建错题表，不写 Alembic 迁移，不把错题复制成第二份数据。
- 不做复习排期、错题出队、错题重做、练习错题、错题导出。
- 不做老师按班查看错题或班级结果视图；老师结果入口留给班级报告章节。
- 不新增独立页面或路由；错题清单以抽屉形式挂在现有考试页。

## Decisions

### Decision 1: 错题是查询，不是新表

错题清单直接从 `answer_items`、`answer_records`、`questions`、`papers` 四张现有表查询：

- `answer_items.is_correct = false` 是错题的唯一事实来源；
- `answer_records.status = 'graded'` 排除判分失败、分数为空的记录；
- `questions` 提供题干、选项、标准答案、解析；
- `papers` 提供卷子标题。

备选方案是新增 `wrong_questions` 表，在判分时写入一条。放弃的理由：判分事务已经写了 `is_correct`，再写一份会出现两处不一致；错题表还要处理同一题多次答错、答对后是否删除、来源扩展，维护成本高于一次查询。设计 02 §2 已明确选择“不单独存一份”。

代价是后续练习、复习来源不能在本次查询里直接出现；本变更用响应里的 `source` 字段固定返回 `exam`，等 ch07 有练习/复习数据时再扩展查询或引入统一视图，不改变本接口对外的条目结构。

### Decision 2: 去重在 SQL 里做，用窗口函数取每题最近一次答错

查询在数据库内按「学生 + 题目」分组，用窗口函数给每条错题编号：

```sql
ROW_NUMBER() OVER (
  PARTITION BY answer_records.student_id, answer_items.question_id
  ORDER BY answer_records.submitted_at DESC, answer_items.id DESC
)
```

外层只取 `rn = 1`，再按 `submitted_at DESC, answer_items.id DESC` 排序。这样一次查询就得到“每名学生每题一条、最近答错在前”，不需要把全部错题拉回 Python 再去重；管理员看全部时，不同学生的同一道题也不会互相覆盖。

排序键用 `submitted_at` 而不是 `graded_at`：错题发生的时间是学生交卷作答的时间，判分失败后隔很久重试成功不应把一道旧错题顶到最前面。`answer_items.id DESC` 只做同一交卷时间下的确定性兜底。

备选方案：

- **先按时间倒序取出全部错题，再在 Python 里按 `question_id` 去重。** 学生自己的数据量不大，但管理员可以看全部，数据量随考试次数增长；SQL 去重更稳，也避免把不需要的旧答案读进内存。
- **用 `GROUP BY question_id` 加 `MAX(submitted_at)` 再回连。** 同一时间戳下回连可能命中多条，仍需额外 tie-breaker；窗口函数一次解决。

本机 SQLite 3.53 支持窗口函数（3.25 起），测试临时库与开发库同源，不需要降级方案。

### Decision 3: 只读已判分记录，空答案也算错题

过滤条件是 `AnswerItem.is_correct IS FALSE` 且 `AnswerRecord.status = 'graded'`。`is_correct` 在判分前是 `NULL`，天然被排除；再加状态条件是为了防住“记录已交卷但判分没完成”的中间态。`score = 0.0` 是合法已判分记录，卷内每道题都会进错题清单；未作答的题在交卷时写入空串，判分后同样进清单。

`is_correct` 用 `IS FALSE` 而不是 `= 0`，避免 SQLite 布尔列在 ORM 层被写成其他假值；在 SQLAlchemy 里用 `AnswerItem.is_correct.is_(False)`。

### Decision 4: 权限沿用结果入口，老师本次不开放

新增路由 `GET /api/wrong-questions`，角色过滤与现有 `GET /api/attempts` / `GET /api/attempts/{id}` 保持一致：

| 角色 | 范围 |
|---|---|
| 学生 | 只能看 `student_id = 当前用户` 的错题 |
| 管理员 | 全部错题 |
| 老师 | 403，提示没有错题入口 |
| 未登录 | 401，由 `get_current_user` 统一处理 |

不把老师按班查看放进本次：现有 `require_attempt_reader` 明确写着“老师没有这里的结果入口”，老师结果视图属于班级报告章节；如果现在单独给老师开错题接口，会出现“能看错题、点不进结果”的半截入口。设计 02 §4.8 的“老师看本班学生”在班级报告章节连同结果一起补齐。

实现上新增一个 `require_wrong_reader(user)` 之类的判定，或在路由里显式分支；不修改 `require_attempt_reader` 的现有语义。

### Decision 5: 响应条目固定字段，来源先只有 exam

返回 `{ "items": [...] }`，每条：

| 字段 | 说明 |
|---|---|
| `question_id` | 题目 ID，用于去重和前端 key |
| `stem` | 题干 |
| `type` | `single` / `multiple` / `blank` |
| `options` | 选择题选项列表；填空题为 `null` |
| `student_answer` | 最近一次答错时提交的答案，未作答为空串 |
| `answer` | 标准答案 |
| `explanation` | 解析，可为 `null` |
| `source` | 本章固定 `"exam"` |
| `paper_id` / `paper_title` | 这道错题最近一次出现的卷子 |
| `attempt_id` | 最近一次答错的作答记录 ID，便于回看结果 |
| `last_wrong_at` | 最近一次答错时间，取 `submitted_at`，ISO UTC |
| `student_id` / `student_name` | 管理员看全部时用于区分学生；学生视角就是自己 |

不返回 `is_correct`（清单里恒为 false）。学生只能看到自己的记录，管理员会看到多人的记录，所以带上学生身份；标准答案和解析只在已判分后可见，与现有结果详情一致。

### Decision 6: 结果态的「看错题」用抽屉，不新增页面

设计 05 把考试页定为一页三态，错题列表最终归复习页的「全部错题」页签。本次在 `frontend/src/pages/student/Exams.jsx` 的结果态加一个「看错题」按钮，点击后用 Ant Design `Drawer` 打开全局错题清单：

- 只有 `status === 'graded'` 时显示按钮；`submitted + 空分` 的判分失败态不显示，避免给出空清单。
- 每次打开重新请求，避免判分或新考试后看到旧缓存。
- 抽屉内覆盖加载中（`Spin`）、空（`Empty`，文案“还没有错题”）、出错（`Alert` + 重试）三种状态。
- 条目展示题干、选项、自己的答案、标准答案、解析、来源（“考试 · 卷子标题”）和最近答错时间；选项沿用 `optionLetter` 的 A/B/C 显示。
- 不新增路由、不改 App.jsx；ch07 做复习页时直接复用同一个接口，把清单挂到「全部错题」页签。

备选方案是新建 `/student/wrong-questions` 页面。放弃的理由：设计 05 的九页清单里没有这一页，且最终入口在复习页；现在建页会多一次迁移成本。

### Decision 7: 判分基线不改，只加回归约束

`backend/app/answers.py`、`grade_record`、交卷/重试路由本次不动。新增错题测试时同时保留并运行现有判分测试：

- `test_answers.py` 固定三种题型的比较与总分；
- `test_exam_attempts.py::test_grading_rules_through_api` 固定接口层的判分结果；
- `test_exam_attempts.py` 的判分失败、重试、并发用例固定状态转移。

任务清单里把“跑通这些既有测试”作为显式步骤，防止实现错题查询时误改判分路径。若实现中发现判分行为与规格不符，先停下来说明，不在本变更里顺手改判分。

### Decision 8: 测试策略

新增 `backend/tests/test_wrong_questions.py`，复用 `exam_helpers`、`classroom` fixture 和现有登录工具：

- **去重与最新答案**：同一道题在两份卷子里分别答错，清单只有一条，答案和时间取后一次。
- **答对不移除**：错过之后答对，清单仍有该题，最近答案仍是错的那次。
- **排序**：两道题不同时间答错，后错的排前面。
- **字段完整**：选择题带选项，填空题 `options` 为 `null`，标准答案、解析、来源、卷子标题齐全。
- **空答案**：未作答的题进清单，`student_answer` 为空串。
- **零分**：白卷判 0.0 后卷内每道题都进清单。
- **未判分排除**：判分失败的记录不产生错题；重试成功后出现。
- **权限**：学生 A 看不到学生 B 的错题；老师 403；管理员看到全部；空清单返回 `items: []`。
- **基线回归**：全量 `pytest` 必须继续覆盖并通过 ch05 的判分与状态测试。

前端继续用 `npm run lint`、`npm run build` 和手工走查；不引入 UI 测试依赖。

## Risks / Trade-offs

- **[错题清单无分页]** 一个学生考过很多次后清单可能变长，管理员看全部时更大。→ 本章先返回全部；后续需要时在接口上加 `limit/offset` 或在复习页做分页，当前数据规模（班级、周测）可接受。
- **[窗口函数依赖 SQLite 版本]** 低于 3.25 的 SQLite 不支持 `ROW_NUMBER()`。→ 项目与测试都使用本机 SQLite 3.53，Alembic 测试库同源；如果以后换数据库，窗口函数仍是主流支持。
- **[来源扩展要改查询]** 练习、复习错题不在 `answer_items` 里，ch07 需要扩展查询或引入统一视图。→ 响应结构已留 `source` 字段，扩展时不破坏前端条目形状；去重规则仍按题，跨来源取最近一次。
- **[老师看不到错题]** 设计 02 的“老师看本班学生”本次不开放。→ 与现有结果入口边界一致，班级报告章节连同结果一起补；不在本次造半截入口。
- **[抽屉不是最终形态]** 设计 05 最终把错题放在复习页页签，本次抽屉是过渡。→ 接口与条目结构按最终形态设计，ch07 只换壳不改数据契约。
- **[答对后旧错题仍在]** 学生可能困惑“我明明答对了为什么还显示错”。→ 这是设计 02 §4.8 的明确选择：错题本记录“错过”，不是“还差”；复习页会负责出队，文案上不承诺“当前薄弱项”。
- **[重试成功后时间变化]** 错题时间取 `submitted_at`，重试不改排序；但 `attempt_id` 指向同一记录，回看结果正常。→ 测试覆盖“判分失败后重试成功”的条目时间与来源。

## Migration Plan

1. 后端先发布：新增只读路由，不改表结构，不需要 Alembic 迁移；旧前端不受影响。
2. 前端随后发布：结果态多一个按钮，调用新接口；后端未发布时按钮请求 404，回滚前端即可。
3. 回滚：删除路由与前端按钮即可，数据库无变更、无数据需要清理。

## Open Questions

无。
