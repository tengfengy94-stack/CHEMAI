# Spec Delta

## Purpose

让登录用户与化学助教完成一轮流式对话：请求只带当前一句话，回答以事件流逐字返回，模型后端可在真模型与假模型之间切换；本章不调用工具，也不保存任何历史。

## ADDED Requirements

### Requirement: 对话接口要求登录

对话接口 MUST 要求有效凭证。凭证缺失、伪造或过期时 MUST 返回 401 JSON 信封，且 MUST NOT 建立事件流。任何持有有效凭证的用户 MUST 能发起对话；本章不按角色裁剪回答内容。

#### Scenario: 未登录不能发起对话
- **WHEN** 请求没有携带 Authorization 凭证
- **THEN** 返回 401，响应体是 `{success:false,data:null,error:<中文>}`，不是事件流

#### Scenario: 学生可以发起对话
- **WHEN** 学生携带有效凭证发送一句话
- **THEN** 返回 200，`Content-Type` 为 `text/event-stream`

#### Scenario: 老师可以发起对话
- **WHEN** 老师携带有效凭证发送一句话
- **THEN** 返回 200，`Content-Type` 为 `text/event-stream`

### Requirement: 每轮对话相互独立

服务端 MUST 把每次请求当作独立的一轮：只使用本次请求里的当前一句话，MUST NOT 接收、读取或保存任何历史消息，MUST NOT 建立对话存档。同一页面里先后两轮之间 MUST NOT 共享上下文；刷新或重新打开对话页后，之前显示的消息 MUST NOT 被恢复。

#### Scenario: 第二轮不引用第一轮
- **WHEN** 同一用户先后发送两条互不相关的话
- **THEN** 第二轮的回答只依据第二轮的那句话，不出现第一轮的内容

#### Scenario: 刷新后消息清空
- **WHEN** 用户刷新对话页
- **THEN** 消息列表为空，没有历史消息被恢复

#### Scenario: 不提供历史接口
- **WHEN** 客户端请求任何对话历史
- **THEN** 系统没有该接口，不返回历史数据

### Requirement: 流里只有正文与结束两类事件

事件流 MUST 只包含 `text` 与 `end` 两类事件。每个 `text` MUST 携带模型生成的正文片段；`end` MUST 是本轮最后一条事件，且一轮 MUST 只发一次。本章 MUST NOT 产生工具事件，也 MUST NOT 把工具参数、模型内部字段或调试信息放进 `text`。

#### Scenario: 正文分多段输出
- **WHEN** 模型生成一段多句回答
- **THEN** 客户端收到多个 `text` 事件，按顺序拼接后等于完整回答

#### Scenario: 结束事件在最后
- **WHEN** 一轮回答正常完成
- **THEN** 所有 `text` 事件之后恰好有一个 `end` 事件，之后没有其他事件

#### Scenario: 不产生工具事件
- **WHEN** 用户发送任意一句话
- **THEN** 事件流里不出现 `tool` 事件

### Requirement: 流式响应必须防缓冲

流式响应 MUST 声明 `Content-Type: text/event-stream`，并 MUST 带 `Cache-Control: no-cache, no-transform` 与 `X-Accel-Buffering: no`，MUST NOT 带 `Content-Length`。响应 MUST 以分块方式持续输出，MUST NOT 等整段回答生成完再一次性发出。

#### Scenario: 响应头禁缓存禁缓冲
- **WHEN** 客户端发起流式对话
- **THEN** 响应带 `Cache-Control: no-cache, no-transform` 与 `X-Accel-Buffering: no`，且没有 `Content-Length`

#### Scenario: 首段正文先于整段完成到达
- **WHEN** 模型还在生成后续内容
- **THEN** 客户端已经能读到前面的 `text` 事件

### Requirement: 心跳每 15 秒一次

流在等待模型输出期间 MUST 每 15 秒发送一次 SSE 注释心跳；心跳 MUST NOT 被当作 `text` 或 `end` 事件，客户端 MUST 忽略它。

#### Scenario: 长时间无正文仍有心跳
- **WHEN** 模型超过 15 秒没有产出正文
- **THEN** 客户端收到一次心跳，且消息列表不因此增加内容

#### Scenario: 心跳不改变事件顺序
- **WHEN** 一轮回答中途出现心跳
- **THEN** 心跳之后仍按顺序收到 `text` 与最终的 `end`

### Requirement: 模型客户端支持真模型与假模型

模型客户端 MUST 支持两种后端：真模型 MUST 使用配置的 OpenAI 兼容地址、模型名与密钥；假模型 MUST 不发起网络请求，按固定中文回答分多段输出。显式开启假模型开关时 MUST 使用假模型；没有配置真模型密钥时 MUST 自动使用假模型，保证无密钥环境也能跑通整套流程。

#### Scenario: 假模型开关开启
- **WHEN** 假模型开关开启
- **THEN** 不发起任何网络请求，客户端收到固定的中文回答，且分多个 `text` 事件

#### Scenario: 没有密钥自动用假模型
- **WHEN** 没有配置真模型密钥，也没有显式开启假模型
- **THEN** 系统自动使用假模型并正常完成一轮对话，不返回配置错误

#### Scenario: 真模型使用配置的地址与模型名
- **WHEN** 配置了地址、模型名与密钥，且假模型开关关闭
- **THEN** 请求发往配置的地址与模型名，回答按真实模型输出流式返回

### Requirement: 流开始前的失败返回 JSON 信封

鉴权、参数校验、模型配置等发生在第一条事件之前的失败 MUST 返回非 200 的 JSON 信封 `{success:false,data:null,error:<中文>}`，MUST NOT 返回半截事件流。

#### Scenario: 空消息被拒绝
- **WHEN** 请求的 `message` 为空字符串或全空白
- **THEN** 返回 422 JSON 信封，错误说明不可为空，不建立事件流

#### Scenario: 缺字段被拒绝
- **WHEN** 请求体里没有 `message`
- **THEN** 返回 422 JSON 信封，错误说明缺少什么，不建立事件流

### Requirement: 流中断不发结束事件

模型上游在流中途失败时，服务端 MUST 关闭流且 MUST NOT 发送 `end` 事件。客户端 MUST 保留已经收到的正文，并进入可重试的出错状态。

#### Scenario: 中途失败没有结束事件
- **WHEN** 模型在输出若干段正文后失败
- **THEN** 连接关闭，已收到的 `text` 保留，没有 `end` 事件

#### Scenario: 出错后可以重试
- **WHEN** 客户端处于流中断的出错状态
- **THEN** 页面保留已有正文，并提供重试操作

### Requirement: 对话页的入口与访问

前端 MUST 提供 `/student/chat` 页面，同时对学生与老师开放。学生页头与每一个老师页头 MUST 提供“对话”入口。未登录访问该页 MUST 跳转登录页，登录后回到对话页。

#### Scenario: 学生从页头进入
- **WHEN** 学生点击页头的“对话”
- **THEN** 打开 `/student/chat`

#### Scenario: 老师从页头进入
- **WHEN** 老师在任一老师页面点击“对话”
- **THEN** 打开同一个 `/student/chat` 页面

#### Scenario: 未登录被送回登录页
- **WHEN** 未登录用户直接打开 `/student/chat`
- **THEN** 跳转登录页，登录成功后回到 `/student/chat`

### Requirement: 对话页四种状态

对话页 MUST 覆盖空对话、发送中、流式回答、出错四种状态：空态给一句引导；发送中禁用输入框与发送按钮；正文逐字追加到当前气泡；收到 `end` 后恢复输入；出错时保留已收到的正文并提供重试。

#### Scenario: 空对话有引导
- **WHEN** 用户第一次打开对话页
- **THEN** 消息列表为空，页面显示一句可以问什么的引导

#### Scenario: 发送中不能连发
- **WHEN** 一轮回答还在流式输出
- **THEN** 输入框与发送按钮处于禁用状态

#### Scenario: 正文逐字追加
- **WHEN** 客户端连续收到多个 `text` 事件
- **THEN** 当前回答气泡持续追加文字，而不是每段新建一个气泡

#### Scenario: 结束后恢复输入
- **WHEN** 客户端收到 `end`
- **THEN** 输入框与发送按钮恢复可用
