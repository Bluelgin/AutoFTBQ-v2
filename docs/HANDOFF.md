# AutoFTBQ v2 开发交接

更新日期：2026-08-25

## 项目定位

AutoFTBQ v2 是独立于稳定版 1.x 的 FTB Quests 离线编辑器与 AI Agent 工作台。目标不是继续堆叠一次性提示词，而是让 Agent 通过软件提供的受控工具查询整合包、编辑任务书、建立依赖、检查结果并形成可撤销的修改检查点。

- v2 仓库：https://github.com/Bluelgin/AutoFTBQ-v2
- 本地目录：`E:\AutoFTBQ-v2`
- v1 仓库：https://github.com/Bluelgin/AutoFTBQ
- 旧开发目录：`E:\MCFTPSMER`
- 默认分支：`main`
- 当前基线标签：`v2.0.0-alpha.1`
- 当前阶段：Alpha，尚未发布 EXE Release

v1 与 v2 已拆分为两个仓库。后续 v2 开发应在 `E:\AutoFTBQ-v2` 进行，不要再把 v2 功能提交到旧仓库的 `v2` 分支。

## 当前验证状态

迁移到独立仓库后已完成以下验证：

- `python -m unittest discover -s tests -p "test*.py"`：191 项测试通过。
- Qt 无界面启动：`MainWindow` 能正常创建并退出。
- PyInstaller 模块收集：能够发现 51 个 `autoftbq_v2` 子模块。
- GitHub Actions：Windows + Python 3.11 自动测试通过。
- 仓库未提交 `config.json`、API Key、日志、自动恢复目录、生成任务书或测试截图。

开始修改前先查看 `git status`。完成修改后至少运行与改动相关的测试；跨模块修改应运行完整测试集。

## 代码结构

主要入口：

- `v2_main.py`：桌面程序入口。
- `autoftbq_v2/ui.py`：主窗口编排和界面状态连接，仍然偏大，后续可继续小步拆分。
- `autoftbq_v2/agent.py`：`ProjectAgent` 稳定公共入口。
- `autoftbq_v2/ftb_store.py`：`FTBQuestStore` 稳定公共入口。

内部模块：

- `autoftbq_v2/agent_core/`：Agent 计划、消息、模型调用、工具注册、作用域、安全事务、检查点和会话运行。
- `autoftbq_v2/editor/`：任务画布、节点渲染、属性编辑器、物品选择器、连接控制和编辑命令。
- `autoftbq_v2/ftb/`：FTB Quests Schema、读取、写回、验证、章节、任务、条件、奖励和画布对象。
- `autoftbq_v2/infrastructure/`：AI 配置、日志、整合包扫描、资源索引、后台线程和工作区恢复。
- `autoftbq_v2/skills/`：Agent 可选择的任务书规划与修复技能。
- `tests/`：v2 与 AI 客户端测试。

根目录中的 `ai_module.py`、`mod_scanner.py`、`snbt_parser.py`、`quest_*.py` 等文件是从 v1 复用的兼容层。它们目前是 v2 的真实运行依赖，不要直接删除。后续可以逐个迁入包内，但每次只迁移一个职责并保持公共接口兼容。

## 已有能力

- 后台扫描整合包，建立物品、配方、注册表与图标索引。
- 读取真实 FTB Quests SNBT，并尽量保留未知字段后安全写回。
- 编辑章节、任务、条件、奖励、章节组、奖励表和部分高级字段。
- 画布缩放、平移、节点移动、多选、复制、删除和任务依赖连接。
- 支持物品、击杀实体、维度/位置及进度类任务条件的统一编辑入口。
- Agent 使用真实工具查询 ID、创建或修改章节与任务、连接前置关系并运行结构检查。
- Agent 具备修改范围限制、执行计划、工具循环、检查点、局部撤销和整轮撤销。
- 支持 `/生成`、`/改进`、`/检查`、`/补全`、`/重排`、`/连线`、`/润色`、`/解释`，普通自然语言也会识别意图。
- `Alt + 点击` 可把任务或章节加入 Agent 上下文。
- 自动恢复未保存任务书、对话、Agent 上下文、画布视图和输入草稿。
- 支持 OpenAI 兼容 API、供应商预设和 Ollama；网络中断最多自动重试 5 次。

具体用户能力以 `README.md` 和当前测试为准。遇到界面反馈时应先复现，不要只根据旧对话描述直接修改。

## 开发原则

- 优先调用现有编辑命令、Store 和 Agent 工具，不要绕过服务直接修改项目数据。
- 用户操作不合法时应在执行前阻止并给出可理解提示，不能依赖异常或崩溃兜底。
- Agent 和用户应走同一套编辑、校验和撤销路径，避免出现两套行为。
- 读取并写回真实 SNBT 时必须保留软件不认识的字段。
- 不进行一次性大重构。按职责小步迁移，每一步补测试并验证启动。
- 不把 API Key、整合包、日志、缓存、生成结果或截图提交到仓库。
- 不发布 EXE 或 GitHub Release，除非用户明确要求并完成打包实测。

## 建议的下一阶段

以下是建议方向，不代表已经确认的 Bug：

1. 进行一轮真实整合包端到端测试：扫描、打开任务书、Agent 修改、人工编辑、检查、保存、进入游戏验证。
2. 建立 Alpha 发布门槛：高风险保存场景测试、崩溃恢复测试、不同 MC/FTB Quests 版本样本和打包后启动测试。
3. 继续缩小 `ui.py`，优先抽离窗口布局构建和各编辑页协调逻辑，不改变现有交互。
4. 逐步收拢根目录兼容层，先从依赖较少的 SNBT/实例路径模块开始，避免再次形成 God Object。
5. 完善 FTB Quests 功能覆盖矩阵，明确“完整支持、原样保留、只读展示、尚不支持”四种状态。
6. 在真实用户测试稳定后，再打包并发布 `v2.0.0-alpha.1` 或后续 Alpha EXE。

## 常用命令

```powershell
cd E:\AutoFTBQ-v2
python -m pip install -r requirements-v2.txt
python -m unittest discover -s tests -p "test*.py"
python v2_main.py
python -m PyInstaller --clean AutoFTBQ-v2.spec
```

## 新对话开场建议

可以直接发送：

> 我们继续开发 AutoFTBQ v2。项目在 `E:\AutoFTBQ-v2`，请先阅读 `docs/HANDOFF.md` 和 `README.md`，检查当前 Git 状态和最近提交，再根据我接下来的需求工作。不要修改旧仓库 `E:\MCFTPSMER`，不要在未经确认时发布 EXE。
