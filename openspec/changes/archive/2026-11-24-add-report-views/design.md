# Design

## Context

当前 `backend/app/reporting.py` 只做一件事：把已判分考试的逐题作答与练习记录 `UNION ALL` 成 `answer_facts`，按知识点汇总后取错误率前三。`GET /api/reports/weak` 只对学生本人与管理员开放，老师一律 403（`backend/app/reporting_routes.py:31`）。前端 `Report.jsx` 也只有一张弱项表。

已有、可直接复用的约束：

- `answer_records.class_id` 是发布时的班级快照（`backend/app/models.py:109`），学生转班不改。
- `answer_records.status` 四态：`pending / in_progress / submitted / graded`；`submitted` 可能已有分数，也可能判分没完成。
- `answer_items.is_correct` 在判分前为 NULL；空白答案按错判。
- `review_tasks.due_on` 是 UTC+8 业务日期，级别 5 出队后为 NULL。
- `practice_records` 只有 `student_id`，没有班级快照（`backend/app/models.py:186`）。
- `require_own_class(class_id, user, session)` 已定义（`backend/app/auth.py:141`），但目前没有调用者；发布卷子用的是内联等价判断。

## Goals / Non-Goals

**Goals:**

- 学生报告一次返回弱项、掌握度、最近五次分数、待复习数，四块共用同一份作答事实。
- 班级报告支持按考试和按知识点两个视图，按发布时班级快照归集。
- 老师从班级报告下钻本班学生报告，权限落在服务端归属判断层。
- 补丁式修改现有弱项行为：0% 错误率不再进入弱项；旧弱项接口保持兼容。

**Non-Goals:**

- 不给 `practice_records` 加班级字段，不做历史练习的班级归属回填。
- 不做报告快照、导出、推送、排名。
- 不改考试作答接口、判分规则、复习级别规则。
- 不新增页面级权限矩阵；沿用三条规则。

## Decisions

### 决策 1：掌握度按知识点等权，不按作答汇总

`mastery = mean(1 - wrong_i / answered_i) * 100`，只对 `answered_i >= 2` 的知识点求平均；知识点之间等权，全对的知识点也参与。

备选是按总答对数除以总作答数（池化）。不选池化的原因：掌握度要回答“这张知识地图上这个学生占住了多少块”，答过 30 题的知识点不应压过只答过 2 题的知识点；池化会让一个大量练习的强项主导整张图。池化的语义更像“总正确率”，不是“掌握度”。

代价是 2 次作答的知识点与 30 次的知识点同权。设计已经用“作答数不少于 2”接受这个前提；掌握度在 `设计/03` §七 也明确只是相对指数，不是精确测量。

**实现方式**：把 `reporting.py` 拆成两步——`knowledge_stats(session, student_id)` 返回每个知识点的 `answered_count / wrong_count`，再由 `weak_items(stats)` 和 `mastery_value(stats)` 分别消费。这样弱项和掌握度不会各写一遍分组逻辑，也不会出现一边算考试一边算练习。

### 决策 2：掌握度的无数据标记独立于报告的 `has_data`

`has_data` 的含义保持现状：存在任一作答事实（已判分考试逐题或练习）。掌握度另带自己的 `has_data`，含义是“至少有一个知识点作答数 >= 2”。

三种状态：

| 状态 | 报告 `has_data` | 掌握度 | 页面 |
|---|:--:|---|---|
| 从没作答 | false | `value=0, has_data=false` | 「还没有学习记录」 |
| 有作答，但没有知识点达标 | true | `value=0, has_data=false` | 弱项「暂无可统计的弱项」，掌握度「暂无可统计」 |
| 有达标知识点 | true | `value=..., has_data=true` | 正常显示 |

不把第二种压成「掌握度 0」：0 是“答了但全错”，和“还没资格算”是两件事，和设计 §4.6 对 0 分的处理同源。

### 决策 3：弱项只收错误率大于 0 的知识点

现状 `weak_report` 把达到样本门槛的知识点全部排序取前三，若只有一两个达标且全对，0% 错误率会作为“弱项”返回。设计 §4.5 说“数据够、但没错……只是不会成为弱项”，所以在候选阶段增加 `wrong_count > 0` 条件。

这会改变现有行为，需要同步改测试：原来只测了“另外三个知识点错误率都高于 0”的场景，新增“唯一达标知识点全对 → 弱项为空、掌握度 100”的场景。

### 决策 4：学生报告新增汇总接口，旧弱项接口不动

新增 `GET /api/reports/me`，只允许学生本人；返回：

```json
{
  "has_data": true,
  "items": [...],                  // 弱项前三，与 /reports/weak 同结构
  "mastery": {"value": 59.4, "has_data": true},
  "recent_scores": [{"paper_id": 1, "paper_title": "周测", "score": 91.7, "graded_at": "..."}],
  "review_due_count": 3
}
```

`GET /api/reports/weak` 保持现有学生/管理员行为，避免破坏第 07/09 章已验收的接口与测试；前端报告页切到 `/reports/me`。两边的弱项计算共用 `reporting.py` 的同一组函数。

**最近五次分数**：`status == 'graded'` 且 `graded_at` 非空，按 `graded_at DESC, id DESC` 取 5 条，再反转成正序。`submitted` 且分数为空的不算。判分时间相同的用记录 ID 稳定排序。

**待复习数**：在 `review.py` 抽一个 `due_task_count(session, student_id)`，条件与到期列表完全一致（级别 0–4、`due_on <= 业务今天`），报告和复习列表共用，避免两处口径漂移。

### 决策 5：班级报告只算考试，不算练习

`practice_records` 没有班级快照。若按学生当前 `users.class_id` 归集练习，转班后历史练习会跟着人跑，和考试“按发布时班级”的口径自相矛盾；若现在给练习加 `class_id`，历史数据只能按当前班级回填，等于制造一批假快照。

所以班级报告只统计 `answer_records` 及其 `answer_items`，练习只进学生个人报告。页面上明确写“考试数据”，不写“全部学习数据”。将来若要含练习，先加 `practice_records.class_id` 快照并接受历史数据不可精确回填，那是另一次变更。

### 决策 6：班级报告的数据形状与查询

新增两条接口：

- `GET /api/reports/classes/{class_id}`：班级总览——考试列表、按知识点分布、学生表。
- `GET /api/reports/classes/{class_id}/exams/{paper_id}`：单次考试——提交情况、逐题正确率、未交名单。

总览查询：

1. **考试列表**：从 `answer_records` 按 `class_id` 过滤，`DISTINCT paper_id`，join `papers`；发布时间取该班该卷 `MIN(created_at)`；名单人数 `COUNT(*)`；题数取 `paper_questions` 计数。按发布时间倒序。
2. **按知识点分布**：构造班级版事实子查询——`answer_items` join `answer_records`，条件 `class_id = ? AND status = 'graded' AND is_correct IS NOT NULL`；按题目关联的知识点分组，分子分母合并。不能先按学生算错误率再平均。
3. **学生表**：以该班快照里的 `student_id` 为集合，left join 每人的最近一次已判分考试（`graded_at` 最大）取分数；错题数按题去重（`COUNT(DISTINCT question_id)`，只算该班已判分且 `is_correct = false`）。没有作答记录的学生显示「未作答」。

单次考试查询：

1. **提交情况**：按 `status` 分组计数；`已交卷 = submitted + graded`、`作答中 = in_progress`、`还没开始 = pending`。名单人数取 `COUNT(*)`，三类之和必须等于它。
2. **逐题正确率**：`answer_items` join `answer_records`，过滤 `class_id = ? AND paper_id = ? AND status = 'graded' AND is_correct IS NOT NULL`，按 `paper_questions.position` 分组；分母是该题已判分条数，不是名单人数。分母为 0 返回 `null`，前端显示「—」。
3. **未交名单**：`answer_records` 中 `status IN ('pending','in_progress')`，join `users` 取姓名，按状态和姓名排序。

所有查询都带 `class_id` 条件，`paper_id` 只作为二级过滤；不先查卷子再信任前端传入的班级。

### 决策 7：权限卡在归属判断层，查询层再兜一次

班级报告走三层：

```
get_current_user
  -> require_own_class(class_id, user, session)     // Class.teacher_id == user.id
  -> 每条查询 WHERE answer_records.class_id = class_id
```

`require_own_class` 已实现但未使用，本次是第一次接线。管理员在函数内直接放行；学生调用会落到 `user.role != 'teacher'` 分支，返回 403。查询层的 `class_id` 条件不是重复劳动：它挡住“归属判断过了、但查询忘了加过滤”的列表泄漏。

**老师下钻学生报告**用 `GET /api/reports/students/{student_id}`：

- 学生调用只能 `student_id == 自己`；否则 403。
- 老师调用：先取目标学生；不存在 404；再要求 `target.class_id` 不为空且 `require_own_class(target.class_id, user, session)`；否则 403。
- 管理员调用：直接放行。
- 判定用学生**当前**班级。学生转出原班后，原班报告仍显示其历史考试行，但该行不渲染报告链接；后端即便收到请求也会因当前班级不属于原老师而 403。这样不会把学生在新班的考试、练习数据泄露给原老师。

### 决策 8：前端两个页面、共用组件

- `Report.jsx`：顶部掌握度卡片 + 待复习数；弱项表；最近五次分数的 Recharts 折线图；三种空态（还没有学习记录 / 暂无可统计的弱项 / 掌握度暂无可统计）。数据源改为 `GET /api/reports/me`。
- `TeacherClassReport.jsx`：顶部班级选择（复用 `GET /api/classes`，老师只拿到自己带的班）+ 考试选择；按考试视图给提交情况、逐题正确率、未交名单；按知识点视图给分布和学生表。学生行可点进报告；转出学生不给链接。
- 两页都做加载中、空、正常、出错四态；空态文案按设计 §4.3 给下一步。
- 前端不承担权限判断：班级 ID 和学生 ID 都来自 URL，服务端重新判定。

### 决策 9：不新增迁移

只读现有表，不需要 Alembic 迁移。`answer_records` 没有 `class_id` 索引，班级报告会扫一次该表；一个学校几千到几万条作答在 SQLite 上是毫秒级，先不加索引，等有实测压力再补。

## Risks / Trade-offs

- [掌握度等权让小样本知识点权重偏高] → 保留“作答数 >= 2”门槛；在页面说明这是相对指数，不写“掌握了 X%”。
- [班级报告不含练习，老师可能预期“全部学习数据”] → 页面标题写明“考试数据”；将“练习入班”列为后续独立变更。
- [弱项排除 0% 会改变已有接口输出] → 更新第 07 章相关测试；现有场景“另外三个知识点错误率高于 0”不变。
- [转出学生原班行没有报告入口] → 学生表加“已转出”标记，避免老师以为链接坏了。
- [老师下钻用当前班级，可能和“原班历史数字仍可见”看起来不一致] → 这是有意的：考试数字属于当时班级，学生个人报告属于当前管辖班级；在页面上分别呈现。
- [班级报告多次聚合，查询较多] → 总览与单次考试拆成两条接口，按页面交互懒加载；不做一次性大响应。
- [旧 `/reports/weak` 与新 `/reports/me` 并行] → 弱项与掌握度共用 `reporting.py` 的统计函数，测试同时覆盖两边，避免口径分叉。

## Migration Plan

1. 后端先发布：新增报告查询、接口与权限接线；旧接口行为保持不变。
2. 前端切换报告页数据源，新增班级报告页与路由。
3. 报告均为请求时现算，无数据迁移、无回滚脚本；回滚只需回退代码，数据库不受影响。
4. 若上线后发现班级报告查询慢，再单独加 `answer_records(class_id, paper_id)` 索引迁移，不阻塞本次变更。
