# AutoFTBQ 游戏桥架构

## 当前基线

首个可运行适配目标：

- Minecraft 1.20.1
- Forge 47.2.19
- FTB Quests 2001.4.22
- Java 17
- 桥接协议 v1（AutoFTBQ Agent Mod 最低 0.1.0-alpha.10；游戏网络协议 v3）

alpha.9 的生产请求由 `LiveProjectAgentTask` 调用共用的 `ProjectAgent.run`。游戏端轮询期间可执行后端批次，持续上传上下文与变化后的快照；后端等待事务回执和匹配快照，再复用同一计划继续验收未完成目标。

`game-mod` 只包含嵌入 FTBQ 原生 `QuestScreen` 的游戏前端、服务端事务入口和版本适配代码。模型密钥、Agent 计划、索引、工具安全策略与会话恢复仍由 AutoFTBQ Studio 管理；独立 Agent 窗口不再是交互入口。

## 安全边界

- Studio 只监听 `127.0.0.1`，不会开放到局域网或互联网。
- 每次 Studio 启动生成新的随机 Bearer Token。
- Mod 从用户目录的 `.autoftbq/bridge.json` 发现端口与令牌。
- Studio 退出时只删除属于当前令牌的发现文件，避免误删另一个实例。
- 请求体上限为 2 MiB，选中任务上限为 256 个。
- 所有消息携带协议版本；上下文使用单调递增的 revision，拒绝旧状态覆盖新状态。
- 发现文件中的令牌不得写入日志、任务书或 Git。
- 后续写入操作必须由 Minecraft 服务端重新检查 FTBQ 编辑权限、对象 revision 和工具白名单。

## v1 已实现协议

游戏内入口仅在 `ClientQuestFile.canEdit()` 为真时出现。`G` 负责展开或折叠同一个内嵌面板；面板展开时，`Alt + 左键`可将任务或章节加入独立的 Agent 上下文，再次点击取消。明确选区会随请求同步，并在 Studio 准备事务时作为不可越过的写入边界。

### `GET /v1/health`

无需令牌，仅返回服务是否存在和协议版本，不包含项目或玩家信息。

### `POST /v1/handshake`

提交 Minecraft、加载器、FTBQ、Mod 版本和能力列表。Studio 返回短期会话 ID 和后端能力。

### `POST /v1/context`

提交当前章节、显式选中的章节与任务、任务书摘要和真实游戏注册表数量。选中章节同时携带其任务 ID 清单，Studio 再从共享任务书快照补充详细内容。当前版本不发送整个整合包注册表，也不发送服务器地址。

### `GET /v1/context?session_id=...`

供 Studio 内部诊断与测试读取最近一次游戏上下文。

### `POST /v1/requests`

游戏先同步上下文，再提交自然语言请求及对应的 `context_revision`。Studio 只会接受最新 revision，防止 Agent 分析已经过期的选区。

alpha.5 起，游戏会在提交请求前等待客户端与服务器任务书 revision 一致。明确的编辑要求直接视为授权；若模型完成查询后没有生成事务，Studio 会自动续跑同一请求，不要求玩家再发送“确认”或“do it now”。alpha.6 起，编辑结果以游戏服务器的事务回执为准：生成提案仅显示“尚未修改”，只有收到 `applied` 才显示“修改已生效”；没有事务、冲突、失败或未知回执都不会再被表述为修改成功。alpha.7 改用 FTB Quests 实际网络同步载荷计算两端版本指纹，避免内容一致时被 SNBT 运行时差异误判为未同步。alpha.8 会把整章上下文压缩为任务、奖励和图标摘要，并在模型查询后保留权威结果，单独续跑事务生成；若仍耗尽模型输出预算，会明确报告任务书未修改。

### `GET /v1/requests/{request_id}`

游戏轮询 `queued`、`running`、`completed`、`failed` 或 `cancelled` 状态，同时读取当前阶段、简短进度和最终回答。

### `POST /v1/requests/{request_id}/cancel`

取消排队或执行中的请求。若模型服务的网络调用已经发出，底层连接可能稍后才结束，但其结果会被丢弃，不会覆盖取消状态。

### `GET /v1/game-queries/next?session_id=...`

Studio 的只读 Agent 请求游戏执行一个白名单查询。当前只允许读取选中任务详情、单项或最多 64 项批量搜索实时物品/方块/实体注册表、批量校验精确 ID，以及按精确物品 ID 查询当前世界加载的输入或输出配方。单个 Agent 请求最多进行 12 次游戏查询，相同查询直接复用结果。

### `POST /v1/game-queries/{query_id}/result`

游戏主线程完成查询后回传有界 JSON 结果。查询协议不能执行命令，也没有创建、编辑、删除或保存 FTBQ 对象的入口。

### `GET /v1/proposals/{proposal_id}`

读取 Agent 生成的结构化原子事务。游戏端在模型完成后自动提交，不再显示批准/拒绝按钮；服务器仍会检查权限、任务书 revision、字段、真实注册表 ID 和事务大小，失败时完整回滚。

### 共享项目接口

- `GET /v1/events`：按游标读取 Studio 与游戏共享的聊天、工作进度、事务、应用和撤回事件。
- `POST/GET /v1/project/snapshot`：上传或读取实时任务书的原始 SNBT 镜像。
- `POST /v1/studio-book/sync`：将 Studio 工作台相对实时镜像的无损差异排入服务器事务队列。
- `GET /v1/studio-transactions/next`：游戏端取得待应用的工作台事务；未回报前会幂等重试。

共享状态持久化在用户目录 `.autoftbq/studio-bridge.sqlite3`。稳定项目身份由持久化客户端 ID 与世界身份共同解析，不依赖一次性会话 ID。

### 自动应用与撤回

应用前，Mod 会重新同步上下文，并分别计算客户端与服务端的整本任务书内容指纹。内容发生变化、两端未同步或服务器没有授予玩家 FTBQ 编辑权限时，事务会被拒绝。

Mod 将已校验的有界操作发送到服务器。服务器再次检查 TeamData 编辑权限、服务端指纹、字段、对象类型和物品 ID，然后在服务器主线程执行一个批次。成功后保存并同步所有客户端；任何阶段异常都会从内存快照恢复、重新落盘并广播恢复状态。

全量同步触发 FTBQ 自身的 `QuestScreen.PersistedData` 路径，恢复章节、缩放、滚动位置和仍然存在的多选对象；AutoFTBQ 另行保持面板展开状态。提案等待审核时，适配层在原生任务按钮上绘制绿色描边，但不修改任务对象。

### `POST /v1/proposals/{proposal_id}/reject`（旧客户端兼容）

仅供旧协议客户端兼容；alpha.5 游戏界面不再提供批准/拒绝按钮。对应请求被取消或失败时，尚未执行的事务仍会自动失效。

### `POST /v1/proposals/{proposal_id}/application`

Mod 将服务器最终的 `applied`、`failed`、`conflict` 或 `undone` 结果回传 Studio。成功写入会返回临时提案 ID 到真实 FTBQ ID 的映射。游戏内“撤销写入”只撤销该玩家最后一次 AutoFTBQ 事务，并要求任务书在写入后没有再次变化。服务器提交和撤销按提案 ID 幂等，迟到回包使用独立请求 ID 隔离；Studio 回报按顺序保留并在临时断线后自动重试，重复的相同结果会被接受，不同结果会被拒绝。

## 版本隔离

直接引用 FTBQ 内部类的代码必须放在：

```text
game-mod/src/main/java/dev/autoftbq/agent/compat/ftbq/<api-generation>/
```

Forge 生命周期与按键注册放在 `forge` 包，HTTP 协议放在 `bridge` 包。新增 Fabric 或高版本时，不得把版本判断散落到协议层。

## 当前事务 Agent 边界

- 游戏内输入请求、查看进度、滚动或复制回答，以及取消。
- Studio 使用面向实时游戏上下文的事务 Agent；模型本身不直接修改对象，而是生成服务器可验证并自动应用的事务。
- 任务文本和注册表名称被当作不可信数据，不能改变系统安全规则。
- 查询名称固定白名单；参数和结果均有大小限制，超时自动返回错误。
- Agent 可以生成有界结构化修改事务，生成、校验和服务端执行保持分层。
- 当前可执行创建或删除章节/任务，修改任务标题、正文、图标和位置，添加依赖、物品/勾选/经验条件及物品/经验奖励；也支持 Studio 原样同步，仍不会执行游戏命令。
- 事务与撤销快照最大 16 MiB，超出时拒绝执行，不降级为无回滚写入。

## 验收状态

- 已自动验证：245 项 Studio 测试、Java 17 干净构建、Forge 1.20.1 开发客户端主菜单启动；启动日志无 ERROR/FATAL。
- 仍需备份世界交互验证：Studio 握手、章节访问器、权限探针、实时查询、真实事务写入、故障回滚、revision 冲突、撤销和断线重连。
- 后续版本方向：在保持 `platform` 与 `compat/ftbq/<api-generation>` 边界的前提下增加 Fabric/NeoForge 和高版本适配；低版本随后评估。
