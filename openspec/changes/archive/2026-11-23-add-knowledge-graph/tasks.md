# Tasks

## 1. 正式词表与迁移

- [x] 1.1 新增 `backend/app/knowledge_seed.py`：定义正式两层词表（氧化还原、电化学、化学平衡、物质结构、元素周期律；氧化还原下氧化剂、还原剂）与临时标签映射（电解质 → 电化学、化学式与化合价 → 物质结构），映射表按名称/别名解析；验证：`pytest tests/test_knowledge_migration.py -q` 的词表结构与映射用例通过。
- [x] 1.2 把 `backend/app/knowledge.py` 的 `merge_points` 拆成不提交的 `_merge_points(session, source, target)` 与保持原签名的公开函数，公开函数仍在末尾提交；验证：`pytest tests/test_knowledge_points.py -q` 全绿，合并接口响应与错误码不变。
- [x] 1.3 为正式节点提供不提交的创建路径（内部函数或直接构造 `KnowledgePoint`），`created_by` 写 `"system"`；验证：现有建节点用例全绿，且新增用例断言正式节点可由迁移创建。
- [x] 1.4 新增 `backend/app/knowledge_migrate.py` 的只读计划阶段：解析正式节点、把节点分成命中/未命中/冲突三类、计算要移动的别名与题目关联、预检全局唯一词冲突；`dry_run=True` 时不写库；验证：dry-run 用例断言报告四类清单且整库数据不变。
- [x] 1.5 实现迁移执行阶段：在单个事务里补建正式节点、按合并语义归并命中节点并删除源、保留未命中节点；任一步异常整体回滚；验证：用例覆盖别名与题目关联转移、同一题重复关联去重、未命中保留、重复执行幂等、异常回滚。
- [x] 1.6 增加命令行入口 `python -m app.knowledge_migrate`，支持 `--dry-run` 与 `--apply`，打印中文报告（新建、合并、保留、移动数、冲突、是否写入）；验证：对临时库跑 dry-run 报告与库不变，跑 apply 后树符合设计映射，再跑 dry-run 计划为空。
- [x] 1.7 写迁移测试 `backend/tests/test_knowledge_migration.py`：用迁移建库并构造第 07 章样式的临时树，覆盖命中合并、别名冲突中止、未命中保留、幂等与回滚；验证：`pytest tests/test_knowledge_migration.py -q` 全绿。

## 2. 老师端知识点管理页

- [x] 2.1 在 `frontend/src/api.js` 增加知识点树、建节点、改节点、合并节点四个封装，沿用现有信封与 401 刷新；验证：`cd frontend && npm run lint` 通过。
- [x] 2.2 新增 `frontend/src/pages/teacher/Knowledge.jsx` 的树表格与四态：名称、别名、直接题目数、操作列；加载、空树、正常、出错四态，空态给「新建第一个知识点」，出错态只给固定文案和重试；验证：`npm run lint && npm run build` 通过，手工确认空态与出错态文案。
- [x] 2.3 在管理页实现建根节点、建子节点、改名称/别名：建节点弹窗校验必填与第三层，编辑时别名整体替换；验证：手工建两层节点并改别名后刷新仍在，接口 400 时页面显示中文原因。
- [x] 2.4 实现合并弹窗：按后端规则禁用源自己、源的子节点、以及源有子节点时的子节点目标；确认框写明别名、题目关联、子节点会移到目标；验证：手工合并成功一次，再试非法目标并确认树不变。
- [x] 2.5 在 `App.jsx` 增加 `/teacher/knowledge` 路由（老师与管理员），并在题库页、考试页页头加入口；验证：老师与管理员直接访问正常，学生访问被守卫送回落地页，三个老师页可互跳。
- [x] 2.6 手工走查管理页四态与合并规则，记录结果；验证：空树、建根/子节点、改别名、成功合并、非法合并、加载失败重试逐条通过，页面行为与 `specs/knowledge-map` 场景一致。

## 3. 开发库迁移与集成验收

- [x] 3.1 备份 `chemai.db`，先跑 `python -m app.knowledge_migrate --dry-run` 核对报告，再跑 `--apply`；验证：`GET /api/knowledge-points` 返回氧化还原（氧化剂、还原剂）、电化学、化学平衡、物质结构、元素周期律，电解质与化学式与化合价不再出现。
- [x] 3.2 对比迁移前后每道题的关联概念数与弱项报告；验证：同一道题关联的概念数不变、无重复行，原计入的题目仍出现在弱项统计里（知识点名字按正式节点显示）。
- [x] 3.3 跑后端全量与章节检查：`cd backend && ../.venv/Scripts/python.exe -m pytest -q`、`bash scripts/check.sh 08`、`bash scripts/doctor.sh`；验证：全部通过，无既有用例回退。
- [x] 3.4 跑前端检查：`cd frontend && npm run lint && npm run build`；验证：通过且无新增告警。
- [x] 3.5 在 `docs/进度.md` 补第 08 章记录（做了什么、卡在哪）；验证：记录包含管理页、正式词表、迁移结果与 check 08 状态。

## Workflow follow-up

- 代码评审与 `doctor.sh` 全绿后归档 `add-knowledge-graph`，并把 `knowledge-map` 的 delta 同步进主规范。
- 归档后确认 `openspec/specs/knowledge-map/spec.md` 含管理页、正式词表、临时标签归并三组新要求。
