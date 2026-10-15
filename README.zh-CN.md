# FacetCue for Blender

[English](README.md) · [下载](https://github.com/Neuromancera113/facetcue/releases) · [完整使用说明](docs/guide.zh-CN.md) · [版本说明](docs/release-notes.md)

**在模型表面写下修改要求，让 Agent 读取并执行，再回到 Blender 审核。**

FacetCue 将每个修改问题变成 Blender 物体表面的独立注释标记。自然语言说明**改什么**，表面锚点与三维坐标说明**改哪里**。Agent 可通过 MCP 批量读取这些要求，调用已连接的 Blender 建模工具逐项修改，再提交结果，由你审核。

**0.5.2 · Beta · Blender 4.2+ · MCP 端需 Python 3.10+ · [GPL-3.0-or-later](LICENSE)**

## 核心能力

| 能力 | 实际作用 |
| --- | --- |
| 一个标记，一个问题 | 每条修改要求有独立注释、编号和区分颜色。 |
| 三维表面绑定 | 锚定受支持网格的三角形，提供当前位置、法线与锚点有效性。 |
| Agent 随时读取 | 已确认注释无需选中对象、保存文件、截图或开启标记显示即可读取。 |
| 批量问题处理 | 一次读取多条要求，较多时分页读取；每项完成说明对应自己的标记 ID。 |
| 在 Blender 中审核 | 支持待处理、进行中、待审核、已完成、已打回和归档状态，可逐点定位、通过或补充要求。 |
| 保存后继续审阅 | `.blend` 保留注释、目标关联、状态、最近修改说明和审核记录。 |

标记以视口叠加层和场景元数据存在，不产生可渲染或可导出的圆点、文字几何。用户可开关显示；即使隐藏标记或物体，Agent 仍可读取已确认注释。

## 从标记到审核

1. **定位问题：** 在物体模式、实体显示下，将标记放到受支持的网格表面。
2. **写下要求：** 例如“将这块面板沿 Z 轴上移 0.12 个 Blender 单位，保持形状和尺寸”。按 **Enter** 保存。
3. **交给 Agent：** 请它读取 FacetCue 标记，并使用已连接的建模工具处理要求。
4. **查看结果：** 完成提交后，标记右上角出现**带窄白边的蓝点**，原有标记颜色保留。
5. **逐项审核：** 跳转到标记附近观察，通过或打回并修改注释；保存 `.blend` 保留审核记录。

FacetCue 提供标记、MCP 连接和审核记录。**实际修改模型需要 Agent 另行连接 Blender 建模工具。** 仅安装本插件不会自行启动自动修改，也不提供任意 Python 执行接口。

## 安装

### 1. 安装 Blender 插件

从 [Releases](https://github.com/Neuromancera113/facetcue/releases) 下载 **`facetcue-0.5.2.zip`**。在 Blender **偏好设置 → 插件 → 从磁盘安装** 中直接选择 ZIP，启用 **FacetCue for Blender**，再打开 **3D 视口 → N → FacetCue for Blender**。同一时间只启用一份安装。

只在 Blender 中标记和审核，安装 ZIP 即可。GitHub 自动生成的 **Source code** 压缩包用于开发，不能直接作为 Blender 扩展安装。

### 2. 安装 MCP 配套服务

需要 Agent 访问时，从同一 Release 下载 **`facetcue-0.5.2-py3-none-any.whl`**，在其所在目录使用独立 Python 3.10+ 执行：

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\facetcue-0.5.2-py3-none-any.whl
```

macOS / Linux：

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install ./facetcue-0.5.2-py3-none-any.whl
```

wheel 未捆绑第三方依赖，pip 会从软件源安装。Blender 插件本体只使用 Blender API 与标准库，不需要向 Blender 内置 Python 安装 MCP 依赖。

### 3. 连接 Agent

在 Agent 客户端添加 **stdio MCP 服务**：`command` 填上述环境 Python 的绝对路径，`args` 填 `["-m", "agent_mcp.server"]`。见 [TOML 配置示例](examples/codex-mcp.example.toml)。

保持 Blender 与插件开启，重新加载客户端的 MCP 配置。单个 Blender 实例会自动发现；多个实例同时运行时，将 `ASM_INSTANCE` 设为目标控制栏显示的会话 ID，连接重启后需更新该值。注释访问无需固定端口或第三方 Blender MCP 桥接。

客户端应发现两个工具：

| 工具 | 用途 |
| --- | --- |
| `get_surface_annotations()` | 读取正式注释、稳定 ID、修订号、位置和可见性。首次无需参数；若 `has_more=true`，按 `next_offset` 继续。 |
| `submit_annotation_changes()` | 实际修改成功后，提交标记 ID、修改前读取的修订号和完成说明，将结果标为待审核。 |

可以这样向 Agent 下达任务：

> 读取我的 FacetCue 表面标记，使用已连接的 Blender 建模工具逐项处理待办要求，遵守每条注释中的保留条件。每项修改成功后提交完成说明，留给我审核。

显示开关、对象选择和侧栏筛选不会限制 Agent 读取。未确认草稿不会被读取；连接失败明确报错，不返回伪造空列表。修订冲突与数据语义详见 [API 说明](docs/api.zh-CN.md)。

## 编辑、定位与快捷键

注释默认使用视口中下部的紧凑可拖动弹窗，**Enter 保存、Esc 取消**。拖动标题后，后续注释框共用新位置，重启 Blender 后仍保留。单击标记选中，双击编号编辑；长文可主动使用侧栏“多行编辑”，已有换行会保留。控制栏支持搜索、状态筛选与近距离定位，跳转后视角围绕标记旋转。

| 物体模式 / 3D 视口快捷键 | 操作 |
| --- | --- |
| Ctrl+Alt+Shift+M | 开关标记显示与点选 |
| Ctrl+Alt+Shift+A | 放置标记 |
| Ctrl+Alt+Shift+← / → | 上一个 / 下一个匹配标记 |
| Ctrl+Alt+Shift+Enter | 通过当前待审核标记 |
| Ctrl+Alt+Shift+Backspace | 打回并编辑要求 |
| Ctrl+Alt+Shift+Z | 撤回最近一次通过或打回 |
| Ctrl+Alt+Shift+X | 确认删除当前标记 |

注释 UI 编辑和删除支持 Blender **Ctrl+Z / Ctrl+Shift+Z**。专用“撤回审核”恢复原注释和审核状态，不撤销模型修改。检测到冲突的快捷键会跳过注册并在面板提示，可在 Blender 键位设置中调整。

可视标记需要同时开启插件显示与 Blender **显示叠加层**。普通模式隐藏被遮挡点；**Alt+Z 的 X-Ray** 以 **60% 透明度 / 40% 不透明度** 显示被遮挡点，注释卡片默认折叠。状态蓝点与主标记遵循相同可见性和透明度。

## 兼容性与当前限制

- 需要 **Blender 4.2+**。已验证 Windows / **Blender 5.2.1 LTS**；同一安装包面向 macOS 和 Linux，但这些平台的 Blender 运行表现仍需实机验证。跨平台 Python CI 通过不等同于 Blender 实机验证。
- 当前锚点支持**无启用视口修改器、无形态键的基础网格**。不支持或拓扑发生变化时，保留注释并明确报告位置失效，尚无自动重附着。
- 复制场景不会自动复制注释；标记较多时，请结合编号区分颜色。
- 确认后的注释立即可读；跨次打开保留需保存 `.blend`。分享该文件也会包含其中保存的注释元数据。

## 隐私与开发

连接仅监听 **127.0.0.1**，通过临时用户目录发现实例并使用令牌校验请求，只接受注释读取与完成提交。FacetCue 不使用云服务或遥测；Agent 读取注释后的数据处理由其自身决定。详见 [安全说明](SECURITY.md)。

```sh
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python scripts/export_mcp_catalog.py --check
python scripts/package_addon.py
python -m build
python scripts/check_release.py --blender /path/to/blender
```

产物写入 `dist/`：插件 ZIP、MCP wheel、源码包和 `SHA256SUMS`。CI 检查代码风格、MCP 接口定义和包内内容；指定 Blender 的检查会在隔离进程中验证安装。打包不会执行发布。模块边界与开发约定见 [CONTRIBUTING](CONTRIBUTING.md)。
