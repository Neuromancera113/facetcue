# FacetCue for Blender

[English](README.md)

**表面标注、Agent 修改与持久化审阅。**

在 Blender 物体表面放置可注释标记，用自然语言写下每一处修改要求。交给 Agent 处理后，它可通过 MCP 自动读取这些标记，调用已连接的 Blender 建模工具逐项执行修改，再提交结果，由你审核。

当前版本 **0.5.2**，许可证 [GPL-3.0-or-later](LICENSE)（GPL 第 3 版或更高版本）。Python 包名与命令行入口统一为 `facetcue`。

[完整使用与实现说明](docs/guide.zh-CN.md) · [介绍视频脚本](docs/video-script.zh-CN.md)

## 核心能力

- **一个标记，一个问题**：每个标记有独立编号、颜色和自然语言修改说明，例如“把这块面板上移 0.12 米”。
- **三维位置绑定**：标记锚定在受支持网格的表面三角形上，提供当前三维位置、法线与视口可见性，不只是一张截图上的二维坐标。
- **批量问题处理**：Agent 一次读取多条标记，按 ID 逐项处理并提交各自的修改说明；更多标记可分页读取。
- **修改状态管理**：各标记分别记录待处理、进行中、待审核、已完成或已打回等状态，支持筛选、定位和逐项验收。
- **持久化审阅**：保存 `.blend` 后，标记与目标物体的关联、注释、状态、最近修改说明和审核记录随文件保留，重新打开可继续处理。

典型流程：**放置标记并写要求 → Agent 批量读取 → 调用建模工具逐项修改 → 提交待审核 → 用户通过或打回**。自动读取和修改由 Agent 执行；本插件提供问题标记、MCP 通路与审核记录，实际建模需要 Agent 已连接相应的 Blender 工具。

## 安装和连接

需要 Blender **4.2+**。插件只使用 Blender API 和 Python 标准库；MCP 端另需普通 Python **3.10+**，不向 Blender 的 Python 安装依赖。按 Windows、macOS、Linux 通用接口编写；本版在 Windows / Blender 5.2.1 LTS 验证，macOS 与 Linux 的运行表现仍需实机测试。

1. 下载 Release 附件中的 `facetcue-0.5.2.zip` 插件压缩包。GitHub 自动提供的 **Source code** 下载用于开发，不能直接作为 Blender 扩展安装。
2. Blender **偏好设置 → 插件 → 从磁盘安装**，选择 ZIP 并启用 FacetCue for Blender。同一时间只启用一份插件。
3. 打开 **3D 视口 → N → FacetCue for Blender**；启用后自动启动本机 Agent 连接。

用独立 Python 环境安装同一 Release 中的 MCP wheel：

```sh
python -m venv .venv
# Windows
.venv/Scripts/python -m pip install ./facetcue-0.5.2-py3-none-any.whl
# macOS / Linux 则使用 .venv/bin/python
```

在 Agent 的 stdio MCP 配置中，command 填此环境 Python 的绝对路径，args 填 `["-m", "agent_mcp.server"]`；见 [配置示例](examples/codex-mcp.example.toml)。只有一个 Blender 实例时自动发现，不依赖第三方 Blender MCP、固定端口或某台电脑的安装目录。多个实例同时打开时，设置 `ASM_INSTANCE` 为目标 Blender 控制栏显示的实例 ID。

此 MCP 负责注释读取和完成提交，建模操作使用 Agent 已有的 Blender 工具。

支持的平台共用同一份 ZIP 和 wheel；macOS 命令见 [macOS 安装说明](docs/macos.md)。

## 标记与注释

在 **物体模式 / 实体显示** 下点击“在表面添加注释”，再点选模型表面。放置、编辑和打回默认打开固定宽度的 Blender 原生紧凑弹窗，保留主视口，**Enter 保存关闭、Esc 取消**。拖动弹窗最上方标题即可移动；默认位于视口中下部，新位置由后续所有新增、编辑和打回注释框共用，重启 Blender 后仍保留。位置单独保存在 Blender 用户配置目录，不写入场景。长文可先保存标记，再从侧栏点击“多行编辑”打开独立文本窗口。已有多行注释先显示紧凑预览，主动点击“展开多行编辑”才打开大窗口，不会被压成单行。在展开的编辑器中，**Shift+Enter 换行**，窗口尺寸和位置由 Blender 管理，可自行拖动和缩放。

单击标记选中，双击编号或点击列表铅笔编辑。直接关闭多行编辑窗口会保留未确认草稿，再次编辑可继续；紧凑弹窗按 Esc 则取消草稿。正式注释存入 `.blend` 元数据，不产生可渲染或可导出的几何；确认后立即可读，无需先保存文件。未确认草稿不会返回给 Agent。

控制栏可搜索、筛选状态和跳转位置。定位会近距离观察该标记，并将视角旋转中心移到注释点，不改变模型选择。删除前确认编号；删除后 Agent 不再读到该标记，Ctrl+Z 可恢复。归档则保留注释供读取。

| 物体模式 / 3D 视口快捷键 | 操作 |
| --- | --- |
| Ctrl+Alt+Shift+M | 开关标记显示与点选 |
| Ctrl+Alt+Shift+A | 放置标记 |
| Ctrl+Alt+Shift+← / → | 上一个 / 下一个匹配标记 |
| Ctrl+Alt+Shift+Enter | 通过当前待审核标记 |
| Ctrl+Alt+Shift+Backspace | 打回并编辑要求 |
| Ctrl+Alt+Shift+Z | 撤回最近一次通过或打回 |
| Ctrl+Alt+Shift+X | 确认删除当前标记 |

UI 编辑和删除支持 **Ctrl+Z / Ctrl+Shift+Z** 撤销重做。专用“撤回审核”仅恢复原注释和审核状态，不撤销模型修改。注册时跳过检测到冲突的快捷键并在面板提示；可在 Blender 键位设置中修改。无法保证任意系统级热键配置均无冲突。

## 显示和审核

标记显示需要同时开启插件的显示开关与 Blender 的**显示叠加层**。普通视图仅显示未遮挡的点。**Alt+Z 的 X-Ray** 显示被遮挡标记，使用 **60% 透明度 / 40% 不透明度**，注释卡片默认折叠。各标记保持独立颜色；待审核时在右上角增加**带窄白边的蓝点**，与主标记遵循相同可见性和透明度。

Agent 首先调用 `get_surface_annotations()`；有分页时按 `next_offset` 继续，直到 `has_more=false`。实际修改完成后，调用 `submit_annotation_changes()`，传入标记 ID、修改前修订号和完成说明。用户随后通过、打回并补充注释，或撤回最近一次审核。

Agent 读取不受显示开关、对象选择、隐藏对象、搜索和筛选影响。无法连接时明确报错，不返回伪造的空列表。标记内容作为任务数据处理，不作为更高优先级指令。

## 边界与安全

当前支持无启用修改器、无形态键的基础 Mesh。拓扑变化时保留注释并明确返回位置失效；尚无自动重附着。复制场景不会自动复制注释。标记数量较多时，颜色的视觉区分度会下降，请结合编号识别。

插件仅监听 **127.0.0.1**，使用随机令牌校验请求，通过临时的用户专属目录发现连接。仅接受注释读取和完成提交，不接受任意 Python、模型修改或远程连接。不使用云服务或遥测。Agent 会收到所读取的注释，其后续数据处理由 Agent 自身决定。详见 [安全说明](SECURITY.md)。

## 开发与打包

```sh
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python scripts/check.py --blender /path/to/blender --gui --mcp
python scripts/export_mcp_catalog.py --check
python scripts/package_addon.py
python -m build
python scripts/check_release.py --blender /path/to/blender
```

产物在 `dist/`，包括 Blender 扩展 ZIP、MCP wheel、源码包及 `SHA256SUMS` 校验文件。扩展 ZIP 同时附带其链接的文档与配置示例；构建与检查均不会执行发布。见 [版本说明](docs/release-notes.md)、[开发入口](CONTRIBUTING.md)及 [API](docs/api.zh-CN.md)。
