# Design

## Context

第 08 章结束后，系统已有两层知识点、弱项前三（`backend/app/reporting.py`）和复习线（`backend/app/review.py`）。判分规则集中在 `backend/app/answers.py` 的 `judge_answer`，考试、复习共用；练习必须沿用同一份。

现有约束：

- 题目审核状态 `approved` 是终态，学生只能接触已通过题。
- `reporting.weak_report` 目前只读已判分考试的 `answer_items`，并明确把练习记录排除在外；本次要把它扩成"考试 + 练习"的统一作答事实。
- SQLite 外键已开启（`backend/app/db.py`），新表引用题目后，删题流程必须显式处理。
- 所有接口走 `{success, data, error}` 信封；业务错误用中文 `fail(...)`，权限错误由 `AccessDeniedError` 统一转 403。
- 测试用临时库 + Alembic 迁移建结构，时间通过 `app.clock` 注入。

## Goals / Non-Goals

**Goals:**

- 练习记录只追加、可追溯每次作答时给出的难度。
- 出题按弱项前三顺序、排除最近 20 条、按难度阶梯放宽，空态可解释。
- 难度只由作答序列决定，刷新、换设备后一致。
- 练习作答并入弱项统计，且不污染考试、复习数据。
- 练习页覆盖加载、正常、反馈、无弱项、暂无题、出错六态。

**Non-Goals:**

- 不做对话页"去练"带来的临时题单；那属于 Agent 章节。
- 不做练习历史页、错题本来源扩展、班级报告。
- 不做练习题的自定义组卷、按知识点手动选题。
- 不改复习级别、间隔和入队规则。

## Decisions

### 1. `practice_records` 只追加，不存难度计数器

新增表：

```
practice_records
  id            PK
  student_id    FK users.id        NOT NULL
  question_id   FK questions.id    NOT NULL
  difficulty    Integer            NOT NULL   -- 出题时实际给的档位 1–3
  is_correct    Boolean            NOT NULL
  created_at    DateTime(tz)       NOT NULL   -- 判分时刻，UTC
```

索引：`(student_id, id)` 用于取最近窗口和重放；`(question_id)` 用于删题检查与统计连接。没有唯一约束，同一道题可以反复练习。

**为什么不在学生表上存 `current_difficulty` / `streak`**：设计 03 §4.3 明确要求"从练习记录里数，不放在内存里"。存一个可变计数器会引入第二个事实源，出现并发写或迁移后漂移；重放记录是确定性的，刷新、换设备、重登都得到同一结果。代价是每次出题要扫一遍该学生的记录，见风险一节。

**记录 `difficulty` 是"实际给的档位"，不是学生当前目标档位**：候选为空时可能放宽到别的难度出题。两者分开记，事后才能还原"当时为什么出了这道题"。

### 2. 当前难度用重放推导，放宽出的题不改变难度

按 `id` 升序重放该学生的全部练习记录：

```
level = 2
streak = 0
for record in records:
    if record.is_correct:
        streak += 1
        if streak % 2 == 0:
            level = min(3, level + 1)
    else:
        streak = 0
        level = max(1, level - 1)
```

要点：

- 初始 2 档；1 档兜底、3 档封顶。
- 每连续答对两题升一档；答错一题降一档并重置连续数。
- 重放只看 `is_correct`，**不看** `record.difficulty`。因此放宽难度出的题不会把学生的目标档位带偏。
- 从 1 档连对四题：1 → 1 → 2 → 2 → 3，符合"每两题升一档"。

**备选方案**：用最后一条记录的 `difficulty` 加减一档。被否掉，因为放宽出的题会污染目标档位；用 `floor(streak/2)` 加档还会重复计算已经体现过的升档。重放最直白，也和规格场景一一对应。

### 3. 出题算法：弱项顺序 + 固定放宽阶梯

`GET /api/practice/next` 的流程：

```
弱项 = reporting.weak_report(student)        # 已按错误率、作答数、ID 排序
当前档 = replay(练习记录)
最近20 = 该学生最近 20 条练习记录的 question_id（按 id DESC）

if 弱项.items 非空:
    for 点 in 弱项.items:                     # 第一弱项优先
        候选池 = 该点下 approved 的题
        for (难度, 窗口) in [
            (当前档, 20), (任意, 20), (任意, 10), (任意, 5), (任意, 0)
        ]:
            候选 = 候选池 - 最近(窗口)        # 窗口是"最近 N 条记录"的前缀
            if 候选非空: 随机取一道，返回
    return 空态(reason="no_question_in_point", message="该知识点暂无题")

else:
    候选池 = 全部 approved 的题
    for (难度, 窗口) in 同一阶梯:
        候选 = 候选池 - 最近(窗口)
        if 候选非空: 随机取一道，返回
    return 空态(reason="no_approved_question", message="题库里还没有可练习的题")
```

几个明确的口径：

- **排除在难度筛选之前**：先算候选池减去窗口，再按难度过滤；反了会反复出同一道题。
- **窗口是记录条数，不是不同题数**：重复作答占名额；排除集合按 `question_id` 去重。20、10、5、0 是同一条倒序记录列表的前缀，只需查一次 20 条。
- **弱项按返回顺序逐个尝试**，第一个点整条阶梯都无候选才顺延；三个都无候选才返回空态，不跨出弱项抓题。
- **无弱项分支也用同一阶梯**：先试当前档，没题再放宽难度，再缩窗口；不会因为"题库里没有 2 档题"直接空态。
- **随机只在候选集合内做**，用 `random.choice`；测试用单候选池或替换 `practice._pick` 保证确定性。
- **知识点只查直接关联**：与弱项统计同口径，不做父节点上卷。

### 4. API 契约

`GET /api/practice/next`：

```json
{
  "status": "question",
  "reason": null,
  "message": null,
  "current_difficulty": 2,
  "served_difficulty": 2,
  "question": {"id": 12, "stem": "...", "type": "single", "options": ["...", "..."]},
  "knowledge_point": {"id": 3, "name": "氧化还原"}
}
```

空态：

```json
{
  "status": "empty",
  "reason": "no_question_in_point",
  "message": "该知识点暂无题",
  "current_difficulty": 2,
  "served_difficulty": null,
  "question": null,
  "knowledge_point": null
}
```

无弱项时仍返回题目，额外带 `has_weak_data=false` 和 `reason`（`no_data` 或 `no_weak_point`），前端据此显示不同提示；`knowledge_point` 为 null。

`POST /api/practice/answers`：

```json
{"question_id": 12, "answer": "A", "difficulty": 2}
```

- `difficulty` 是出题响应里的 `served_difficulty`，由客户端带回。服务端只校验 1–3。
- 为什么不由服务端重新推：服务端不知道这道题当时是"目标档"还是"放宽档"出的；重新推会把放宽记录写错。客户端篡改只能污染自己的练习记录和弱项统计，不构成越权，接受这个信任边界。
- 响应：`question_id`、`record_id`、`is_correct`、`student_answer`、`answer`、`explanation`、`served_difficulty`、`next_difficulty`。
- 判分复用 `answers.judge_answer`；答案长度上限 500，与考试、复习一致。
- 写记录与判分在同一事务；提交后 `next_difficulty` 按包含新记录的重放结果返回。

### 5. 弱项统计扩成统一作答事实

把 `reporting` 的查询改成两路 `UNION ALL`：

```
exam_facts:      answer_items JOIN answer_records
                 WHERE student_id=? AND status='graded' AND is_correct IS NOT NULL
practice_facts:  practice_records
                 WHERE student_id=?
facts = exam_facts UNION ALL practice_facts   -- 列：question_id, is_correct
```

然后 `facts JOIN question_knowledge_points JOIN knowledge_points`，按知识点 `count(*)` 作答数、`sum(is_correct=false)` 错题数。`has_data` 也改为 `facts` 是否为空。

这样：

- 同一道题考三次、练两次，五次各算一次；一题多知识点仍然在每个点各算一次。
- 练习记录没有"未判分"状态，天然全部可用；考试仍只取已判分记录。
- 复习作答仍不进入 `facts`。
- 合并知识点后，练习记录通过题目关联自动重算，无需回填。

**备选方案**：在 Python 里分别查两路再合并。被否掉，因为门槛、排序、分页口径都在 SQL 聚合里，拆到 Python 会多一套排序逻辑，和"报告每次现算、只有一处口径"冲突。

**性能**：`facts` 先按学生过滤再连接，两次查询都走 `student_id` 索引；学校规模下足够。后续记录量大了可以加物化视图，不在本次范围。

### 6. 删题前置检查

`delete_question` 在卷子占用检查之后，再查 `practice_records` 是否有该题：

- 有记录：`fail("这道题已被学生练习过，不能删除", 409)`，不删关联、不删题。
- 无记录：沿用现有流程，先删知识点关联再删题。

**为什么不做级联删除**：练习历史是弱项统计的事实来源，跟着题目一起删会悄悄改变学生和班级的数字，和设计 03"报告没有自己的数据、口径不能悄悄变"的原则冲突。宁可让老师换一道题，也不改写历史。

### 7. 前端练习页

- 路由 `/student/practice`，`RequireAuth roles={['student']}`；`StudentHeader` 加"练习"按钮。
- 页面状态：`loading`、`question`、`feedback`、`empty`、`error`、`submitting`。
- 顶部三格难度：用 1–3 三个标记，高亮当前 `current_difficulty`；提交后若响应带 `next_difficulty`，先更新三格，再让用户点"下一题"。
- 作答控件沿用复习页的三种题型写法（单选 Radio、多选 Checkbox、填空 Input），本章不抽公共组件，避免改动已验收的复习页。
- 提交后显示对错、标准答案、解析和"下一题"；提交中禁用按钮，失败保留已填答案。
- 无弱项：题目上方一条提示；暂无题：`Empty` + 重试；加载失败：固定文案 + 重试，不显示原始报错。
- 不在页面显示标准答案、解析，直到提交成功。

### 8. 迁移与测试策略

- 迁移 `0005_practice`，`down_revision = "0004_review_knowledge"`，只建表和索引，不回填。
- 新增 `tests/test_migration_0005.py` 验证表与索引存在、`downgrade` 可回到 0004。
- 新增 `tests/test_practice.py` 覆盖难度重放、选点顺序、排除窗口、放宽阶梯、空态、判分、权限、副作用边界。
- 扩展 `tests/test_weak_report.py`：练习计入、考试+练习合并、`has_data`、复习不计。
- 扩展 `tests/test_question_management.py`：练过的题删除被拒、未练过的题仍可删。

## Risks / Trade-offs

- **[每次出题重放全部练习记录，O(n)]** → 先用 `(student_id, id)` 索引扫一遍；学校规模下 n 很小。若将来单学生记录过万，可在学生表加检查点，但必须保证检查点与记录一致，本次不做。
- **[客户端回传 difficulty 可被篡改]** → 只影响该学生自己的练习记录和弱项统计，不涉及越权或他人数据；服务端仍校验 1–3。若将来要做防作弊，可改成一次性出题令牌。
- **[练习记录稀释错误率]** → 学生大量练习会改变弱项排名，这是设计 03 §4.5 的既定口径；练习本身按难度出题，正确率不会无限高。接受。
- **[缩到窗口 0 会重复出题]** → 设计明确"宁可重复，不要死锁"；重复作答会继续写记录，统计按真实作答计。
- **[删题被练习记录挡住]** → 老师可能删不掉一道已练过的坏题。替代方案是级联删记录，但那会悄悄改统计；本次选择保历史。
- **[随机选题让测试不稳定]** → 候选只有一个时确定；多候选用 `practice._pick` 注入固定选择，不测试随机分布。
- **[并发提交可能都写成功]** → 练习是追加事实，两次提交就是两次练习，不引入乐观锁；页面提交中禁用按钮降低误触。

## Migration Plan

1. 合入迁移 `0005_practice`，按既有方式 `upgrade_to_head`；无数据回填，旧库直接加表。
2. 部署后练习页与接口生效；弱项报告立即开始把新产生的练习记录计入，历史考试数据不变。
3. 回滚：`alembic downgrade 0004_review_knowledge` 删除 `practice_records`。练习历史随之丢失，但考试、复习、知识点数据不受影响。
4. 前端与后端同一版本发布；旧前端不调用练习接口，不受影响。

## Open Questions

- 学生账号删除时练习记录如何处理：当前系统没有删账号功能，留到有账号生命周期时再定。
- 练习页是否显示当前正在练哪个弱项：设计 05 只要求顶部三格难度，本次不额外展示知识点名；空态文案仍按"该知识点暂无题"。
