# Tasks

## 1. 数据模型与迁移

- [x] 1.1 在 `backend/app/models.py` 新增 `ReviewTask`、`KnowledgePoint`、`KnowledgePointAlias`、`QuestionKnowledgePoint`，字段、唯一约束与索引按设计 §2；验证：`cd backend && ../.venv/Scripts/python.exe -c "from app.models import ReviewTask, KnowledgePoint; from app.models import Base; print(sorted(Base.metadata.tables))"` 输出含四张新表。
- [x] 1.2 新建 `backend/alembic/versions/0004_review_knowledge.py`：建四张表、唯一约束和索引，并回填历史复习任务（每个学生每题取判分时间最晚的一条错误作答，第 0 级，到期日为判分业务日 + 1，`last_wrong_attempt_id` 指向该作答记录）；验证：在临时库 `alembic upgrade head` 成功，回填任务数与去重后的「学生 + 题」错题对数一致。
- [x] 1.3 新增迁移测试：用 Alembic 升到 `0003_exam`，直接插入一条已判分且答错的逐题作答，再升到 head，断言恰好一条第 0 级任务且到期日、`last_wrong_attempt_id` 正确；验证：`pytest tests/test_migration_0004.py -q` 通过。
- [x] 1.4 验证 `alembic downgrade 0003_exam` 只删除四张新表，原有 `questions / papers / answer_records / answer_items` 行数不变；验证：测试或迁移命令执行后查询行数一致。

## 2. 业务日期与判分事件

- [x] 2.1 新增 `backend/app/clock.py`：固定 UTC+8 的 `business_today()` 与 `business_date_of(dt)`，并提供可注入 `now` 的入口供测试使用；验证：单测覆盖 UTC 15:59 仍属当天、16:00 进入次日，以及月末、年末跨日。
- [x] 2.2 新增 `backend/app/events.py`：进程内 `subscribe(event, handler)` / `publish(event, **kwargs)`；验证：单测断言订阅者收到参数、未订阅事件不报错、`import app.events` 不产生循环导入。
- [x] 2.3 修改 `backend/app/routes.py` 的 `grade_record()`：在 `session.commit()` 之前发布 `attempt_graded`；新增 `backend/app/review.py`，在导入时订阅并把任务写入同一事务；验证：现有判分、交卷、重试判分用例全绿，且新增集成用例「交卷后立即请求复习任务能看到该错题」通过。
- [x] 2.4 在 `backend/app/review.py` 实现入队 upsert：无任务则建第 0 级；有任务且不是同一次判分则重置第 0 级并按本次判分重排；第 5 级同样重置；同一 `last_wrong_attempt_id` 重复通知跳过；未作答的空答案按错入队；验证：`pytest tests/test_review_tasks.py -q` 覆盖以上分支。
- [x] 2.5 验证入队异常回滚：monkeypatch 入队函数抛错，交卷后记录停在 `submitted + 空分`、没有任务；恢复后重试判分成功，任务出现；验证：新增回归用例通过，且现有重试用例不回退。

## 3. 复习任务接口

- [x] 3.1 在 `backend/app/schemas.py` 增加复习作答、知识点增改合并、题目关联的入参模型与 `FIELD_LABELS` 中文提示；验证：缺字段或类型错误的请求返回 422 且提示中文。
- [x] 3.2 实现 `GET /api/review/tasks?scope=due|all`：`due` 只返回级别 0–4 且到期日不晚于今天、按到期日与 ID 升序；`all` 含第 5 级；学生只读自己，管理员读全部并带学生 ID/姓名，老师 403；验证：`pytest tests/test_review_tasks.py -q` 对应用例通过。
- [x] 3.3 实现到期条目序列化：题干、题型、选项、级别、到期日、上次答案、复习次数，不带标准答案与解析；验证：测试断言响应字段集合。
- [x] 3.4 实现 `POST /api/review/tasks/{id}/answer`：调用 `judge_answer()` 判分，答对升一级并按新级别间隔重排（0→1 加 3 天、1→2 加 7 天、2→3 加 14 天、3→4 加 30 天、4→5 出队），答错回第 0 级、次日到期；返回学生答案、标准答案、解析、本次对错、上次答案、新级别与下次到期日/出队标记；验证：测试覆盖单选、多选、填空、升级、归零与出队。
- [x] 3.5 补作答边界：同一天顺序两次都成功并连续升级；第 5 级返回 400；他人任务、老师、管理员返回 403；任务不存在返回 404；超长答案拒绝；复习作答不改变考试分数、逐题对错与错题清单；验证：`pytest tests/test_review_tasks.py -q` 全绿。
- [x] 3.6 用 `review_count` 做条件更新实现并发保护：两个同时提交只有一个成功、另一个 400，级别只变一次；验证：`ThreadPoolExecutor` 并发用例通过。
- [x] 3.7 验证逾期读取无副作用：连续两次请求到期列表，级别与到期日完全一致，逾期任务排最前；验证：新增用例通过。

## 4. 知识点接口

- [x] 4.1 新增 `backend/app/knowledge.py` 与接口：`GET /api/knowledge-points` 返回两层树（名称、别名、上级、题目数），`POST /api/knowledge-points` 建节点；校验上级必须是根、第三层 400、上级不存在 404、名称去空白且全局唯一；验证：`pytest tests/test_knowledge_points.py -q` 对应用例通过。
- [x] 4.2 实现 `PUT /api/knowledge-points/{id}`：整体替换别名、点内去重、名称/别名全局唯一、改名时旧名称自动成为别名；验证：测试覆盖别名保存、改名保留旧名、改名撞词 400。
- [x] 4.3 实现 `PUT /api/questions/{id}/knowledge-points`：整体替换题目关联、列表去重、空列表清空；只有题目创建者或管理员可改，他人题 403，学生 403，题目或知识点不存在 404；验证：测试覆盖一道题挂两个点、整体替换、去重、清空与权限。
- [x] 4.4 实现 `POST /api/knowledge-points/{id}/merge`：把源名称与别名并入目标、题目关联去重后移动、子节点改挂目标、删除源；拒绝合并到自己、合并到自己的下级、以及源有子节点且目标是子节点（会产生第三层）；源或目标不存在 404；验证：测试覆盖成功合并、去重、三种 400 与两种 404。
- [x] 4.5 验证合并后的读取结果：源节点从树里消失，目标别名包含源名称，目标下题目关联无重复，子节点挂在目标下；验证：合并后再次 `GET /api/knowledge-points` 的断言通过。

## 5. 弱项统计接口

- [x] 5.1 新增 `backend/app/reporting.py` 与 `GET /api/reports/weak`：按知识点分组统计已判分考试的逐题作答，过滤作答数 < 2，按错误率降序、作答数降序、知识点 ID 升序取前三，错误率用 `Decimal(ROUND_HALF_UP)` 转成一位小数百分比；同时返回 `has_data`；验证：`pytest tests/test_weak_report.py -q` 覆盖 2/3→66.7、1/1 不进、样本够但全对不占前三、并列排序、最多三个。
- [x] 5.2 补统计口径边界：一题挂多知识点在各分母各算一次、未挂知识点的题不计、未判分记录不计、复习作答不计、白卷空答案按错计入；验证：`pytest tests/test_weak_report.py -q` 全绿。
- [x] 5.3 补无数据状态：新学生 `has_data=false`；有已判分作答但没有知识点 `has_data=true` 且列表为空；样本不足 `has_data=true` 且列表为空；验证：对应用例通过。
- [x] 5.4 补权限：学生只看自己；老师 403；管理员必须带 `student_id`，不带返回 400，学生不存在返回 404；验证：对应用例通过。
- [x] 5.5 验证合并后重算：两个知识点各有作答，合并后再次请求弱项，作答数与错题数汇总到目标，源知识点不再出现；验证：新增用例通过。

## 6. 前端

- [x] 6.1 在 `frontend/src/api.js` 增加 `listReviewTasks(scope)`、`answerReviewTask(id, answer)`、`getWeakReport()`；在 `frontend/src/constants.js` 增加到期日文案与错误率格式化；验证：`cd frontend && npm run lint` 通过。
- [x] 6.2 新增 `frontend/src/pages/student/Review.jsx`：两个页签，"今日到期"用 `scope=due`，"全部错题"用 `/api/wrong-questions` 与 `scope=all` 按 `question_id` 合并出队列状态；在队列里的条目可进入答题态，已出队或无任务条目只读；答题结果展示对错、学生答案、标准答案、解析、上次答案、新级别与下次到期日；覆盖加载、空、正常、出错四态，空态文案为"今天没有要复习的"；验证：`npm run lint && npm run build` 通过，并手工走查答题与结果。
- [x] 6.3 新增 `frontend/src/pages/student/Report.jsx`：只做弱项前三区块，表格显示知识点、作答数、错题数、错误率（一位小数）；`has_data=false` 显示"还没有学习记录"并给去考试的按钮，`has_data=true` 且列表为空显示"暂无可统计的弱项"；覆盖四态；验证：`npm run lint && npm run build` 通过，并手工走查两种空态。
- [x] 6.4 在 `frontend/src/App.jsx` 增加 `/student/review` 与 `/student/report` 路由，并在学生页头增加"复习""学习报告""考试"入口；验证：学生直接访问两个 URL 正常渲染，错误角色被守卫送回落地页，三个页面可互跳。
- [x] 6.5 手工走查前端：无到期时显示"今天没有要复习的"；答对后到期日按新级别显示；答错后回第 0 级并显示"明天"；已出队不出现在到期列表；"全部错题"的队列筛选正确；报告空态不显示 0；验证：逐条记录结果，与 `specs/review`、`specs/reporting` 的场景一致。

## 7. 集成验收

- [x] 7.1 用演示账号走全链路：老师建两层知识点并给题挂上 → 组卷发布 → 学生答错 → 复习队列出现第 0 级任务 → 答对升第 1 级 → 学生报告出现该知识点弱项；验证：页面行为与规格场景一致。
- [x] 7.2 验证同一题再考错：同一道题在第二份卷子再答错，任务仍只有一条且级别归零、到期日重排；复习到第 5 级出队后再次考错，任务重新入队；验证：API 结果与页面一致。
- [x] 7.3 跑后端全量与章节检查：`cd backend && ../.venv/Scripts/python.exe -m pytest -q`、`bash scripts/check.sh 07`、`bash scripts/doctor.sh`；验证：全部通过，无既有用例回退。
- [x] 7.4 跑前端检查：`cd frontend && npm run lint && npm run build`；验证：通过且无新增告警。
- [x] 7.5 在开发库执行迁移并走查旧功能：确认历史错题回填为第 0 级任务，考试列表、结果页、错题清单与权限行为不变；验证：迁移后页面与接口均正常。

## Workflow follow-up

- 评审通过后运行 `openspec archive add-review-weakness-stats` 归档变更。
- 检查归档后的 `openspec/specs/review/`、`knowledge-map/`、`reporting/` 与 `access-control/` 增量，确认合并结果无重复或丢失。
