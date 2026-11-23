# Tasks

## 1. 依赖与配置

- [x] 1.1 在 `.venv` 安装 `langchain-openai`，把精确版本写进 `backend/requirements.txt`；验证 `pip install -r backend/requirements.txt` 成功、`python -c "import langchain_openai"` 成功，且现有 pytest 全绿。
- [x] 1.2 在 `backend/app/config.py` 增加模型配置读取：假模型开关、密钥、地址、模型名，以及“显式假模型 / 无密钥自动假模型 / 配置齐全用真模型 / 有密钥但缺地址或模型名报配置错误”四分支选择；新增单元测试覆盖四分支并通过。

## 2. 模型客户端

- [x] 2.1 新建 Agent 模块与模型工厂：默认工厂按配置返回真/假模型，工厂挂在 `app.state` 上以便测试注入；测试断言路由能取到注入的工厂。
- [x] 2.2 实现假模型异步流：固定中文回答分多段输出、不发起网络请求、段间延迟可配置；测试断言分段数大于一、拼接结果固定、无网络调用。
- [x] 2.3 实现真模型适配：用配置构造 `ChatOpenAI`，把 `astream` 的增量转成纯文本片段；用 LangChain 的假聊天模型验证增量顺序，不访问真实网络。
- [x] 2.4 实现最小系统提示：每次请求固定 `system` + 当前 `user` 两条消息，不拼接历史；测试断言消息结构与内容固定。

## 3. 流式接口

- [x] 3.1 新增 `POST /api/chat/stream` 路由与请求模型：`message` 去除首尾空白后不能为空；鉴权走现有 `get_current_user`；未登录 401、缺字段或空消息 422，均为 JSON 信封且不建立事件流；跑接口测试验证。
- [x] 3.2 实现 SSE 编码与响应头：`text` / `end` 事件、JSON `data`、`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`、无 `Content-Length`；测试断言响应头、事件顺序、`end` 唯一。
- [x] 3.3 实现心跳：模型 15 秒无增量时发 `: ping` 注释，心跳不产生 `text` / `end`；心跳间隔做成可调常量，测试用缩短的间隔和延迟假模型断言至少一次心跳。
- [x] 3.4 实现流中断处理：生成器内部捕获模型异常，记录日志、关闭流、不发 `end`；用注入的失败模型断言已收到部分 `text` 且没有 `end`。
- [x] 3.5 验证每轮独立：用记录型假模型捕获每次请求的消息，断言每次只有 `system` + 当前 `user`；连续两轮互不引用；确认没有对话表、迁移或历史接口。
- [x] 3.6 验证流式生命周期：在返回 `StreamingResponse` 前把用户信息取成普通值，生成器不碰 ORM；测试完整流结束后不出现会话已关闭相关异常。

## 4. 前端流客户端

- [x] 4.1 在 `api.js` 增加 `streamChat(message, { signal, onEvent })`：携带 `Authorization`、401 时复用一次刷新再重试、非 2xx 解析 JSON 信封、2xx 读取 `response.body`；`npm run build` 通过。
- [x] 4.2 实现 SSE 帧解析：按 `\n\n` 切帧、跨包半帧缓冲、忽略 `: ping` 注释、处理 `text` / `end`；在浏览器里用假模型确认多段正文正确拼接、心跳不显示为内容。

## 5. 对话页与入口

- [x] 5.1 新增 `Chat.jsx`：消息列表、输入框、发送/重试按钮、自动滚动、纯文本显示；覆盖空对话、发送中、流式回答、出错四态；`npm run build` 通过，并在浏览器逐态走查。
- [x] 5.2 在 `App.jsx` 注册 `/student/chat`，放行学生、老师与管理员；未登录跳登录并在登录后回到该页；浏览器验证三种角色与未登录回跳。
- [x] 5.3 学生页头与每个老师页头增加“对话”入口；逐个点击验证到达 `/student/chat`。
- [x] 5.4 验证不存历史：消息只存在 React state，不写 localStorage/sessionStorage；刷新页面后消息清空。
- [x] 5.5 验证发送中禁用输入框与按钮、收到 `end` 后恢复、断流时保留已收到的正文并显示重试；在浏览器中用假模型逐项走查。

## 6. 集成验收

- [x] 6.1 全量 pytest 全绿，`npm run build` 通过，`bash scripts/check.sh 11` 与 `bash scripts/doctor.sh` 全绿。
- [x] 6.2 假模型端到端走查：空态 → 发送 → 逐字追加 → `end` 恢复输入 → 中途断流 → 保留正文并重试，记录走查结果。
- [x] 6.3 在 `docs/进度.md` 补第 11 章条目（做了什么、卡在哪），确认文档包含本章内容。

## Workflow follow-up

- 评审通过后归档 `add-agent-chat`。
- 按项目惯例提交并打 `ch11-ok`。
