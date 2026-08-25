# AutoFTBQ v2

AutoFTBQ v2 是面向 FTB Quests 的离线编辑器与 AI Agent 工作台。它直接读取和尽量无损地写回任务书 SNBT，让用户能在进入 Minecraft 前查看、修改、检查并由 Agent 逐步完善任务书。

> 当前处于 Alpha 开发阶段。稳定版 1.x 仍在 [AutoFTBQ](https://github.com/Bluelgin/AutoFTBQ) 仓库维护；请先备份整合包和任务书后再测试 v2。

## 目前能力

- 后台扫描整合包，按需解析物品图标、配方、主题形状和安全可枚举的注册表 ID；普通方块模型会生成等距立体缩略图，多层物品贴图会自动合成。
- 离线查看与编辑章节、任务、全部官方任务条件和奖励、章节图片、任务跳转、章节组、奖励表、全局配置及原生多语言文件。
- 画布平移、缩放、框选、多选、复制、删除、跨章节移动与依赖连线；支持官方曲线控制点和隐藏连线设置。
- 保留软件不认识的附加模组字段和未来版本字段，保存前建立备份，并提供撤销、重做及全任务书结构检查。
- Agent 按需查询真实 ID、配方和统一 Schema，再执行小步修改；每轮修改自动校验，可在界面预览后整体保留或撤销。
- Agent 会先建立可检查的执行计划，再按章节、任务数量、任务类型、前置关系、分层布局和结构错误逐项验收；右侧实时显示当前阶段、实际操作和安全检查点，技术行动记录默认折叠。
- 每次有效修改都会先通过本地结构检查再形成安全检查点。参数或 Schema 错误只撤销当前工具；API 中断会保留此前成果，用户可继续执行、只撤销上一步或撤销本轮全部修改。
- 输入 `/` 可选择生成、改进、检查、补全、重排、连线、润色和解释模式；普通自然语言仍会自动识别意图。
- 按住 `Alt` 点击任务节点或章节可加入 Agent 上下文。选定范围后，软件会在工具层阻止 Agent 修改范围外的现有内容；再次点击可取消，输入区也可一键清除。
- 自动保存当前任务书草稿、Agent 对话与上下文、行动记录、当前选择、画布视图和未发送的输入，重启后继续上次工作区。
- 普通 v2 项目可导出为 FTB Quests SNBT；打开真实任务书时可直接安全写回原目录。

依赖游戏代码的动态材质和模组自定义渲染器无法在 Minecraft 外完整复现，此类图标会回退到代表贴图并在物品选择器中标明；对应模型和 SNBT 数据不会丢失。

自动恢复文件保存在软件目录的 `.autoftbq_workspace` 中，只用于恢复编辑器内尚未保存的内容，不会自动写入游戏。打开真实任务书后，仍需点击“保存”才会写回 FTB Quests 目录。

## 运行

需要 Python 3.11 或更高版本。建议先创建独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-v2.txt
python v2_main.py
```

也可双击 `start_v2.bat`。Agent 读取软件目录中的 `config.json`，API Key 不会写入任务书项目。

## 打包

双击 `build_v2_exe.bat`，或运行：

```powershell
pyinstaller --clean AutoFTBQ-v2.spec
```

v2 使用独立的打包配置，不会覆盖 v1 的源码或 `AutoFTBQ.spec`。

## 测试

```powershell
python -m unittest discover -s tests -p "test*.py"
```

每次推送和 Pull Request 都会在 GitHub Actions 中自动运行测试。测试不会调用真实付费 API。

## 项目结构

- `autoftbq_v2/agent_core`：Agent 计划、工具调用、范围控制、检查点和会话运行。
- `autoftbq_v2/editor`：任务画布、属性编辑、连接控制和物品选择器。
- `autoftbq_v2/ftb`：FTB Quests 数据模型、校验、读取和写回。
- `autoftbq_v2/infrastructure`：整合包扫描、AI 配置、日志和工作区恢复。
- 根目录兼容模块：复用自 v1 的扫描、SNBT 与 AI 客户端能力，后续会逐步收进 v2 包内。

## 安全说明

API Key 只保存在本机配置中，不应提交到 Git。保存真实任务书前软件会创建备份，但 Alpha 期间仍建议保留整合包的独立备份。

## 参与开发

欢迎提交 Issue 和 Pull Request。修复编辑器行为时，请尽量补充对应测试，并先运行完整测试集。
