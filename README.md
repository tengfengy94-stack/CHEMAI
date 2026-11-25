# ChemAI 教学助手

面向化学老师与学生的教学闭环系统：老师建题、组卷、发布；学生作答、判分、复习、练习；AI 助教在同一个对话页里查数据、讲错题、按弱项出练习。

当前版本 **v1.0.0**。

---

## 一、这个项目是什么

系统围绕一条主链工作：

```
建题 → 组卷 → 发布 → 作答 → 判分 → 错题 → 复习/练习 → 报告
                                         └→ AI 助教（查数据、讲题、出题）
```

**三个角色：**

| 角色 | 主要用途 |
|---|---|
| 老师 | 建题、审题、组卷、发布、看班级报告、问 AI |
| 学生 | 作答、看分、复习错题、自适应练习、看自己的报告、问 AI |
| 管理员 | 初始化数据、排障；无专属页面 |

**九页 + 登录页：**

| 页面 | 路由 | 角色 |
|---|---|---|
| 登录 | `/login` | 所有人 |
| 题库 | `/teacher/questions` | 老师 |
| 组卷 | `/teacher/exams` | 老师 |
| 知识点 | `/teacher/knowledge` | 老师 |
| 班级报告 | `/teacher/class` | 老师 |
| 考试 | `/student/exams` | 学生 |
| 复习 | `/student/review` | 学生 |
| 练习 | `/student/practice` | 学生 |
| 报告 | `/student/report`、`/teacher/students/:id/report` | 学生 / 老师 |
| 对话 | `/student/chat` | 学生 / 老师 |

**技术栈：**

| 层 | 选型 |
|---|---|
| 前端 | React 19 + Vite 8 + antd 6 + Recharts + react-router |
| 后端 | FastAPI + Pydantic + SQLAlchemy + Alembic |
| 数据库 | SQLite（单文件，零安装） |
| 认证 | PyJWT 双凭证 + pwdlib / Argon2 |
| Agent | LangChain + LangGraph，单智能体 + 工具循环 |
| 测试 | pytest（后端）、oxlint + vite build（前端） |

---

## 二、怎么跑起来

### 环境要求

- Node.js **≥ 20.19**
- Python **3.12**
- Git
- Windows 下用 Git Bash 跑脚本；macOS / Linux 可直接用 bash

### 第一次安装

在项目根目录执行：

```bash
python -m venv .venv

# Windows（Git Bash）
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt

# macOS / Linux
.venv/bin/python -m pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

复制环境变量模板：

```bash
cp backend/.env.example backend/.env
# Windows CMD 可用：copy backend\.env.example backend\.env
```

`.env` 和开发环境自动生成的 `.jwt-secret` 都不会进版本库。

### 配置说明

默认配置是**假模型**，不联网、不需要密钥，也能跑通完整流程：

```dotenv
CHEMAI_ENV=dev
CHEMAI_FAKE_MODEL=1
```

切换到真模型时，在 `backend/.env` 里填写：

```dotenv
CHEMAI_FAKE_MODEL=0
CHEMAI_MODEL_BASE_URL=https://api.openai.com/v1
CHEMAI_MODEL_API_KEY=你的密钥
CHEMAI_MODEL_NAME=gpt-4o-mini
```

- 有密钥但缺地址或模型名：服务启动后第一次对话会返回明确的配置错误，不会静默降级。
- 没有密钥：自动回退到假模型。
- 生产环境（`CHEMAI_ENV=prod`）必须显式设置 `CHEMAI_JWT_SECRET`，且默认不插入演示账号。

### 启动

```bash
bash scripts/dev.sh
```

脚本会先执行 `alembic upgrade head`，再同时启动前后端：

- 后端：<http://127.0.0.1:8000>，健康检查 `GET /api/health`
- 前端：<http://localhost:5173>

停止：

```bash
bash scripts/stop-dev.sh
```

### 手动启动（可选）

```bash
# 终端 1：迁移 + 后端
cd backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 终端 2：前端
cd frontend
npm run dev
```

### 数据库

- 开发库默认是项目根目录的 `chemai.db`，可用 `CHEMAI_DATABASE_URL` 覆盖。
- 表结构只由 Alembic 迁移创建；应用启动时**不会** `create_all`。
- 开发环境首次启动、对应表为空时，会自动插入演示班级/账号和三条示例题。
- 需要重置演示数据时，停掉服务后删除 `chemai.db`，再跑一次 `bash scripts/dev.sh`。

---

## 三、演示账号

开发环境首次启动会自动创建以下账号，密码统一为 **`chem2026`**：

| 用户名 | 姓名 | 角色 | 班级 |
|---|---|---|---|
| `teacher01` | 演示老师 | 老师 | 负责高一(1)班、高一(2)班 |
| `s0101` | 陈小明 | 学生 | 高一(1)班 |
| `s0102` | 林晓华 | 学生 | 高一(1)班 |
| `s0201` | 王小雨 | 学生 | 高一(2)班 |
| `admin` | 管理员 | 管理员 | — |

- 生产环境默认不插入这些账号；确需演示数据时显式设置 `CHEMAI_SEED_DEMO=1`。
- 学生只能看到自己的考试、错题、练习和报告；老师只能看自己带的班。
- 未登录打开任意页会跳到登录页，登录后回到原页面。

---

## 四、怎么验证

### 1. 开工体检

```bash
bash scripts/doctor.sh
```

检查 Node / Python 版本、后端依赖、前端依赖、数据库文件、pytest 和 `/api/health`。

### 2. 后端全量测试

```bash
cd backend
../.venv/Scripts/python.exe -m pytest -q
```

v1.0.0 当前为 **482 条**。测试使用临时数据库，不会污染开发库。

### 3. 前端构建与 lint

```bash
cd frontend
npm run build
npx oxlint src
```

### 4. 章节验收

```bash
bash scripts/check.sh 15
```

第 15 章会检查：全量测试、30 条 Agent 评测、`v1.0.0` 标签。打标签的命令：

```bash
git tag v1.0.0
```

### 5. Agent 评测

```bash
bash scripts/eval.sh
# 只做假模型冒烟
bash scripts/eval.sh --smoke
```

- 30 条用例，工具选择 / 答案质量 / 安全三类各 10 条。
- 通过标准：总分 ≥ 24/30，且安全类 10/10。
- 正式验收使用真模型（在 `backend/.env` 配置）；假模型只用于离线冒烟。
- 评测脚本会启动独立的 uvicorn 和 `chemai-eval.db`，不会动开发库；报告写入 `eval-report.json`（已 gitignore）。

---

## 五、目录与文档

```text
backend/
  app/                  FastAPI 应用、权限、考试、复习、报告、Agent、护栏
  alembic/              数据库迁移
  tests/                后端 pytest
  evalkit/              Agent 评测用例、判定器、运行器
frontend/
  src/pages/            登录、老师端、学生端、共用报告页
  src/api.js            后端接口封装与 401 续签
scripts/
  dev.sh                迁移 + 启动前后端
  stop-dev.sh           停止本项目的前后端
  doctor.sh             环境体检
  check.sh              章节验收
  eval.sh / eval.py     Agent 评测
设计/                   五份设计文档（数据与权限、题库与考试、复习与报告、Agent、页面与选型）
openspec/               变更提案与归档
docs/进度.md            按章记录的实现进度与踩坑
```

**设计文档：**

- [设计总览](设计/00-设计总览.md)
- [数据与权限](设计/01-数据与权限.md)
- [题库与考试](设计/02-题库与考试.md)
- [复习与报告](设计/03-复习与报告.md)
- [Agent](设计/04-Agent.md)
- [页面与选型](设计/05-页面与选型.md)

**这一版明确不做：** 家长端、OCR 批改、通知推送、预警定时任务、多智能体、向量检索、线上部署。它们不在“出题 → 考试 → 判分 → 复习”的主链上，留作后续版本。
