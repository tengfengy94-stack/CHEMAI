# Tasks

## 1. 依赖与数据模型

- [x] 1.1 `backend/requirements.txt` 新增 `pyjwt`、`pwdlib[argon2]` 并装进 `.venv`；验证：`python -c "import jwt, pwdlib"` 成功，`bash scripts/doctor.sh` 依赖项仍全绿
- [x] 1.2 `app/models.py` 加 `User`（username 唯一、name、role、class_id 可空外键、password_hash）与 `Class`（name、teacher_id 外键）；验证：模块可导入，`pytest -q` 既有测试不红
- [x] 1.3 写迁移 `alembic/versions/0002_*.py` 并同步 `app/migrations.py`：建 `classes`（teacher_id 先不带约束）→ 建 `users` → `batch_alter_table` 给 `classes.teacher_id` 补外键，并 `UPDATE questions SET created_by='teacher01' WHERE created_by='演示老师'`；验证：对开发库副本执行 `alembic upgrade head` 后两张表结构与外键存在、题目归属已更新，`pytest -q` 临时库建表不红

## 2. 登录与凭证

- [x] 2.1 新建 `app/auth.py`：Argon2 哈希与校验、JWT 签发与验签（access 15 分钟 / refresh 14 天，payload 只带 sub 与 type、不带 role，密钥取 `CHEMAI_JWT_SECRET` 缺省用本地默认并在使用默认值时打警告日志）；验证：`tests/test_auth.py` 里 token 往返、过期拒绝、refresh 冒充 access 被拒三条单测全绿
- [x] 2.2 `app/schemas.py` 加登录请求与凭证响应模型，`app/routes.py` 加 `POST /api/auth/login`、`POST /api/auth/refresh`（登录失败统一提示"用户名或密码不对"；用户名不存在时对预置哑哈希也跑一次校验再返回，避免响应时序泄露账号存在性）；验证：登录成功、密码错、用户名不存在（提示与密码错相同）、刷新成功、过期 refresh 拒绝、access 冒充 refresh 被拒六条接口测试全绿
- [x] 2.3 `app/auth.py` 加 `get_current_user` 依赖（读 Bearer 凭证，解析失败返回 401 中文信封），并挂到 `GET /api/questions` 上；验证：无凭证 401、带有效凭证 200 两条测试全绿

## 3. 三层权限与题目接口

- [x] 3.1 `GET /api/questions` 按角色分叉（老师只看自己建的、学生只看已通过、管理员全量），学生分支的条目去掉标准答案与解析字段（新增学生版序列化，`question_to_dict` 全字段保留给教师与管理员）；`POST /api/questions` 限老师与管理员、`created_by` 写当前用户，`PLACEHOLDER_CREATOR` 从 `config.py` 删除；验证：角色分叉三场景、学生条目不含答案与解析、学生建题 403、伪造凭证 401 的接口测试全绿
- [x] 3.2 `app/auth.py` 加三个归属判定 `require_owner` / `require_self_data` / `require_own_class` 与 `AccessDeniedError`，`main.py` 统一转 403 中文信封；验证：六条越权用例中四条判定级测试全绿（改别人的题、读别人的数据、改别人的答案、看别班）

## 4. 种子账号

- [x] 4.1 `app/seed.py` 加两个班与五个演示账号（admin、teacher01 带两班、s0101 / s0102、s0201，密码 chem2026），种子题归属 `teacher01`，仍只在空库时插入；验证：空临时库启动后 teacher01 与 s0101 均可登录，teacher01 列表能看到三条种子题，已有数据的库不重复插入

## 5. 前端

- [x] 5.1 `src/api.js`：token 存取 `localStorage`、请求带 `Authorization`、401 时用 refresh 静默换一次并重放原请求（POST 先缓存原始 body 再重放）；刷新单飞——并发 401 共享同一次刷新调用；刷新失败先清刷新标志再清存储跳 `/login`，不循环重试；验证：`npm run build` 通过，手动走查凭证过期后的静默续签与跳转
- [x] 5.2 登录页 `/login`（antd 表单、中文错误提示、成功后回跳 `from` 参数）与路由守卫（未登录跳登录）；验证：手动走查——未登录打开题库页被送到登录页，登录后回到题库页
- [x] 5.3 登录后按角色跳转：老师与管理员进题库页，学生进占位页（"考试列表将在后续章节开放"）；学生访问 `/teacher/questions` 被守卫拦回占位页；验证：三种身份各登录一次的手动走查 + `npm run build` 通过

## 6. 集成验收

- [x] 6.1 `bash scripts/check.sh 03` 全绿（全量 pytest）
- [x] 6.2 `bash scripts/doctor.sh` 全绿
- [x] 6.3 `bash scripts/dev.sh` 起服务后按清单手动验收：未登录访问题库跳登录；teacher01 登录看到三条种子题；s0101 登录只看到已通过一条；admin 登录看到全部；退出后凭证清理生效

## Workflow follow-up

- 按章节流程收尾：提交、打 tag `ch03-ok`、在 `docs/进度.md` 记第 03 章"做了什么 / 卡在哪"。
- 六条越权用例中四条判定级测试，在作答（第 05 章）、班级报告（第 07 章）接口出现后升级为接口级，判定函数不动。
- 实现完成并验收通过后归档本变更（`openspec archive`），归档前经用户确认。
