# Design

## Context

后端只有三个接口（health、题目列表、建题），`created_by` 是占位字符串，无任何身份概念。表结构只由 Alembic 迁移建（`app/migrations.py` 供测试用，`alembic/versions/` 供开发库用，两处都要加）。接口统一走中文信封（`envelope.py` 的 `ok`/`fail`）。测试每个用例一份临时库，结构用迁移建。前端 `api.js` 统一拆信封。技术选型按设计/05：PyJWT + pwdlib（Argon2）。

## Goals / Non-Goals

**Goals:**

- 三件事能跑通：登录/刷新拿凭证；带凭证的请求能解析出身份；题目两个接口按角色分叉。
- 三条权限规则以可复用的判定函数存在，六条越权用例全部有测试（接口级或判定级）。
- 迁移对既有开发库无感：旧种子题归属更新为演示老师。

**Non-Goals:**

- 不做登出/凭证撤销、改密码、找回；凭证过期靠有效期，前端换不到就回登录页。
- 不做账号与班级的管理界面（设计/01 §3.1：这一版由管理员直接改数据）。
- 不做作答、报告、组卷等后续接口的权限接线——规则先立，接口到各自章节再挂。

## Decisions

**1. `created_by` 存 username，不改成外键。**
人不删（设计/01 §3.1）、username 唯一且稳定，字符串关联够用；换来的是 `questions` 表和既有迁移完全不动，只在新迁移里 `UPDATE` 旧占位值。改外键要多一次表重建（SQLite 改列要复制整表），收益只有引用完整性检查，不值。

**2. User / Class 互相引用，迁移分三步建。**
`users.class_id → classes.id` 与 `classes.teacher_id → users.id` 成环，SQLite 不能直接加约束。顺序：先建 `classes`（`teacher_id` 暂存整数、不带约束）→ 建 `users`（`class_id` 带外键）→ `batch_alter_table` 给 `classes.teacher_id` 补外键。`alembic/versions/` 与 `app/migrations.py` 同步加。

**3. 凭证：HS256 双 token，无撤销。**
- access token 15 分钟，payload `{sub: username, type: "access"}`，不带 role；
- refresh token 14 天，payload `{sub: username, type: "refresh"}`；
- 密钥从环境变量 `CHEMAI_JWT_SECRET` 取，缺省用 config 里的本地默认值（单机本地版，无多实例校验需求）；使用默认密钥启动时打一行警告日志，提醒部署者配置环境变量；
- 刷新接口只认 `type: "refresh"`，access token 来刷一律拒绝；
- 无撤销列表：本地单机、无登出需求，有效期即边界。备选的"密码版本号作废旧 token"需要加列和比较逻辑，先不做。

**4. 三层权限的载体。**
- 第一层：`get_current_user` 依赖（新文件 `app/auth.py`）——读 `Authorization: Bearer`，验签、查库得 User；失败返回 401 信封。公开接口清单只有三个：health、login、refresh。**角色与归属一律以查库结果为准**：token payload 不带 role，也不作为任何权限判断的依据——管理员改掉某用户的角色，其已签发的 token 立即失去旧角色，而不是等 15 分钟过期。前端展示用的身份信息由登录响应返回，不从 token 里解。
- 第二层：`app/auth.py` 里三个判定函数 `require_owner` / `require_self_data` / `require_own_class`，命中拒绝时抛内部 `AccessDeniedError`，由 `main.py` 统一转成 403 中文信封。本章只有一个真实调用点（建题=老师/管理员，归属即创建者），其余判定函数先立着，供后续章节接线。
- 第三层：查询过滤写在路由的 SELECT 里——老师 `created_by = 当前用户`，学生 `status = "approved"`，管理员不加条件。学生的"仅已通过"是可见性规则，不是权限判定，不进判定函数，留在查询处。序列化同样分叉：学生分支的题目条目去掉 `answer` 与 `explanation`（由学生版序列化函数输出，`question_to_dict` 全字段保留给教师与管理员）——答案与解析是作答语境才下发的（设计/02 §4.6），题库列表对学生不发，第 05 章的作答接口沿用这条。

**5. 六条越权用例的落法。**
第 03 章只有题目接口，六条里两条打接口、四条打判定函数：

| 用例 | 本章落点 |
|---|---|
| 无凭证访问 | 接口级：`GET /api/questions` 无凭证 → 401 |
| 伪造凭证 | 接口级：伪造签名 → 401 |
| 老师改别人的题 | 判定级：`require_owner` 用两位老师的数据断言拒绝 |
| 学生读别人的数据 | 判定级：`require_self_data` |
| 学生改别人的答案 | 判定级：`require_self_data`（同一判定，两用例分开写） |
| 老师看别班 | 判定级：`require_own_class` |

后续章节接口出现后，同六条升级为接口级，判定函数不动。

**6. 种子账号。**

| 用户名 | 角色 | 归属 | 演示密码 |
|---|---|---|---|
| admin | 管理员 | — | chem2026 |
| teacher01 | 老师（高一(1)班、高一(2)班班主任） | — | chem2026 |
| s0101 / s0102 | 学生 | 高一(1)班 | chem2026 |
| s0201 | 学生 | 高一(2)班 | chem2026 |

种子题 `created_by` 更新为 `teacher01`。密码哈希用 Argon2，种子在启动时现算（三条题 + 五个账号，开销可忽略）。

**7. 前端。**
- 登录页 `/login`：antd 表单，用户名 + 密码，成功后存 `localStorage`（access、refresh、用户信息）并回跳来源页；
- `api.js`：请求带 `Authorization`；收到 401 且有 refresh 时静默换一次并重放原请求；再失败清存储跳 `/login`；
- 路由守卫：未登录访问任何页跳 `/login?from=…`；学生误入老师页回自己的页（本章只有题库页，先立守卫的形）。

## Risks / Trade-offs

- [SQLite 环形外键迁移易错] → 迁移分三步并用 `batch_alter_table`；测试的 `upgrade_to_head` 与开发库 `alembic upgrade head` 走同一条代码路径，测试先红即知。
- [JWT 密钥有本地默认值，理论上可伪造] → 本地单机版可接受；环境变量覆盖留给部署时，不在本章做配置界面。
- [localStorage 存 token 有 XSS 面] → 本版无第三方脚本、本地运行，接受；设计/05 的范围外清单已排除线上部署。
- [判定函数级测试不等于接口级] → 每条用例注明对应接口出现于哪一章，验收清单里带"升级"标记，防止判定测试绿灯掩盖接线遗漏。

## Migration Plan

1. `alembic/versions/0002_*.py` 与 `app/migrations.py`：建 `classes`、`users`（三步建约束），`UPDATE questions SET created_by='teacher01' WHERE created_by='演示老师'`。
2. 开发库直接 `alembic upgrade head`（`dev.sh` 启动时本来就会跑）。
3. 回滚：drop `users`、`classes`；`questions.created_by` 不回写（占位值已无意义，旧代码也不再读它）。
