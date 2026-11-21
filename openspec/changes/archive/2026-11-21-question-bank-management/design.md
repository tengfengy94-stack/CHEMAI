# Design

## Context

第 03 章结束时题库只有两个接口：`GET /api/questions` 按角色过滤后返回整个数组，`POST /api/questions` 建草稿。`require_owner` 已实现但没有任何路由调用（评审已确认）。`status` 字段与归属字段都在，本章不需要迁移。删除的“被卷子用过”判断依赖尚不存在的卷子表。

## Goals / Non-Goals

**Goals:**

- 题库管理四个动作闭环：改、审、删、筛（含分页），全部经接口与页面验证。
- `require_owner` 第一次接到真实路由，规则①从“函数存在”变成“动作存在”。
- 角色范围与筛选彻底分离：筛选只收窄，永不放大。

**Non-Goals:**

- 组卷、发布、题目进入卷子的使用关系（下一章）。
- 题目复制、“已通过另存为新题”、软删除、批量导入导出。
- 学生端浏览题库的界面（学生只通过考试与练习接触题）。
- 知识点归类、判分（后续章节）。

## Decisions

**1. 接口形状。**

| 动作 | 接口 | 请求体 / 参数 | 说明 |
|---|---|---|---|
| 编辑 | `PUT /api/questions/{id}` | 与建题相同的字段（题干、题型、选项、答案、解析、难度） | 全量替换，复用 `validate_new_question` 的校验与答案规范化；`status`、`created_by` 忽略 |
| 审核 | `POST /api/questions/{id}/status` | `{"status": "pending" \| "approved"}` | 只表达“标待复核 / 通过”两个动作 |
| 删除 | `DELETE /api/questions/{id}` | — | 成功返回 204 或信封成功 |
| 使用检查 | `GET /api/questions/{id}/usage` | — | 返回 `{"papers": n}`，给删除前预检用 |
| 列表 | `GET /api/questions` | `difficulty`、`status`、`q`、`page` | 固定每页 20 条 |

**2. 状态机用显式转移表，不写 if 级联。**
`ALLOWED_TRANSITIONS = {("draft","pending"), ("draft","approved"), ("pending","approved")}`。目标状态只接受 `pending`/`approved`——退回草稿不是一种动作，在请求模型层就以 422 拒绝；不在转移表里的组合一律 409。错误文案：从 `approved` 出发报“已通过的题不能再改状态”，其余非法组合报“不能这样改状态”。已通过与归属判定共用 `require_owner`，管理员豁免。

**3. 归属判定复用第 03 章的 `require_owner`。**
编辑、审核、删除三处都先按 `question.created_by` 调 `require_owner`；这不是新规则，是把规则①接到真实动作上。找不到题返回 404 中文提示，不泄露“存在但不是你的”与“不存在”的区别以外的东西——统一“题目不存在”。

**4. 列表查询集中在一个函数里，角色条件无条件追加。**
`build_question_query(user, difficulty, status, q)`：
- 角色条件先加：teacher → `created_by == me`；student → `status == "approved"`；admin → 无；**其他角色直接抛 `AccessDeniedError`**（修复评审发现的未知角色落全量）。
- 再叠加用户筛选：difficulty、status、`stem LIKE %q%`；条件之间 AND。
- 排序保持 `created_at DESC, id ASC`；`page` 从 1 开始，每页固定 20 条，响应 `{items, total, page, page_size}`。
学生条目的序列化仍走 `question_to_public_dict`，不加答案与解析。

**5. 删除保护先留接口位，组卷章节接线。**
`papers_using_question(session, question_id) -> int` 单独成函数；本章没有卷子表，恒返回 0。`GET /usage` 与 `DELETE` 共用它：DELETE 里 `count > 0` 时拒绝并提示“这道题已被 N 份卷子使用”。**组卷章节必须先替换这个函数再开放加题进卷**，否则会出现“先删题再加进卷”的口子——写进 tasks 的 follow-up。

**6. 前端交互照设计/05。**
- 顶部筛选条三样：难度 Select（全部/1/2/3）、审核状态 Select（全部/草稿/待复核/已通过）、关键词 Input（回车或按钮触发）；筛选变化回到第 1 页。
- 表格服务端分页，`total` 来自响应；筛选后为空显示“没有符合条件的题”（与“题库里还没有题”区分，设计/05 §4.1 的“筛选后为空”）。
- 行操作按状态显示：草稿 → 编辑、标待复核、通过、删除；待复核 → 编辑、通过、删除；已通过 → 只留删除。按钮消失而不是点了报错。
- 删除点击先调 `/usage`：份数大于 0 直接提示，不弹确认；为 0 弹确认（写明“删除后不能恢复”）再 DELETE。

**7. 响应结构变更一次做完。**
列表从数组改为分页对象是 **BREAKING**；前端 `listQuestions(params)` 与既有测试（`test_questions_api`、`test_auth_api`、`test_question_access` 里读 `data` 的断言）同步改成读 `data.items` / `data.total`。

## Risks / Trade-offs

- [列表结构变更波及既有测试与前端] → 同一个任务里改完接口、测试与前端，跑全量再进下一步；不做“先改接口后改页面”的中间态提交。
- [删除保护本章恒为 0] → 只影响“被卷子用过”的拦截，本章无卷子所以无实际风险；组卷章节第一件事是替换 `papers_using_question`，follow-up 里标死。
- [已通过的题不能改] → 老师要改只能新建（设计/02 §4.2 的取舍）；前端把编辑按钮藏掉，不给人点了才报错的体验。
- [固定 20 条/页] → 与设计/05 §五一致；题库规模是老师个人几百道题，够用，不做可调页大小。
- [编辑用 PUT 全量字段] → 前端本来就用同一个表单提交全部字段，避免“缺字段被当空值清掉”的半更新歧义。

## Migration Plan

无数据库迁移。接口结构变更随本章一次发布；回滚只需回退代码（数据未变）。
