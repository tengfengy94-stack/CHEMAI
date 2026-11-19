# Proposal

## Why

第 02 章的接口全部匿名：`created_by` 写死为占位符"演示老师"（`app/config.py` 的 `PLACEHOLDER_CREATOR`），任何人都能读全量题库、以这个占位身份建题。设计/01 把"数据与权限"定为系统的地基——后面每一章（组卷、作答、报告、Agent）的每一条查询都要从"我是谁"推出"我能看到什么"。这一层不在第 03 章落地，越往后补代价越大：每个已写好的接口都要回炉。

## What Changes

- 新增两张表和一条 Alembic 迁移：`users`（一张身份表，role 区分 teacher / student / admin，学生挂班、老师不挂）和 `classes`（名称 + 班主任）。账号只能管理员造，人不删，只改归属。
- 新增登录、刷新两个接口：短期凭证 + 长期凭证（PyJWT），密码用 Argon2（pwdlib）校验。
- 新增 `get_current_user` 请求依赖，作为三层权限的第一层（登录校验）。
- 三条权限规则落到现有接口：
  - 只能改自己建的：建题时 `created_by` 写当前用户（占位符退场）；
  - 只能看自己的 + 只能看自己带的班：`GET /api/questions` 按角色分叉——老师只看到自己建的题（含草稿、待复核），学生只看到已通过的题，管理员全量。
  - **BREAKING**：`GET /api/questions`、`POST /api/questions` 匿名访问从 200 变 401。
- 种子数据补演示账号：管理员、带两个班的老师、两个班的学生若干；种子题归属改为演示老师。
- 六条越权用例进测试：老师改别人的题、学生读别人的数据、学生改别人的答案、老师看别班、无凭证访问、伪造凭证。
- 前端：登录页（一次做好，之后不再改）、api.js 统一带凭证与 401 跳转、题库页按登录身份取数。

## Capabilities

### New Capabilities

- `identity`：谁是谁——账号与班级的存储、登录与凭证刷新、当前用户解析。此后所有模块从这里取"我是谁"。
- `access-control`：三条权限规则（只能改自己建的 / 只能看自己的 / 只能看自己带的班）与三层落地（登录校验、归属判断、查询过滤），规定每个接口按身份限定数据范围。

### Modified Capabilities

（无。`openspec/specs/` 目前为空，这是本项目第一个建规格的变更；题库接口的角色分叉作为 `access-control` 的场景写进新规格，不为它单独立 capability。）

## Impact

- **后端**：`app/models.py`（User、Class）、新迁移 `0002`、`app/routes.py`（auth 两个接口 + questions 挂权限）、`app/schemas.py`（登录请求/响应）、`app/seed.py`（演示账号）、`app/config.py`（`PLACEHOLDER_CREATOR` 退场）、新增 `app/auth.py`（哈希、JWT、`get_current_user`）。
- **前端**：新增登录页路由，`src/api.js` 带凭证与刷新，题库页接登录身份。
- **依赖**：`backend/requirements.txt` 新增 `pyjwt`、`pwdlib[argon2]`。
- **兼容性**：现有前端不登录直接用题库页会 401；迁移后 `questions.created_by` 存用户名（演示老师），旧数据可用。
