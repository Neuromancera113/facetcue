# FacetCue for Blender 0.5.2

**Surface notes for agent edits and persistent review.**

Beta release · Blender 4.2+ · Python 3.10+ for MCP · GPL-3.0-or-later

FacetCue lets you place an annotated marker on a Blender model, describe the change in natural language, and give an agent both the request and its 3D surface context through MCP. The agent uses its connected Blender modeling tools to apply the changes and submits results for your review.

## Included in 0.5.2

- **Independent issues:** one note, number and distinct marker color per requested change.
- **3D surface anchors:** positions, normals, anchor validity and viewport visibility for supported meshes.
- **Direct batch access:** read confirmed annotations without selection, saving, screenshots or visible overlays; paginate larger sets and submit results by marker ID and revision.
- **Persistent review:** open, in-progress, awaiting-review, resolved, changes-requested and archived states; notes, latest completion summaries and review records saved in the `.blend` file.
- **Viewport workflow:** compact draggable note dialogs with remembered position, Enter to save, search, close-up navigation, editable notes, deletion and review withdrawal.
- **Clear visual feedback:** distinct marker colors remain intact; a blue dot with a narrow white border marks submitted work. X-Ray reveals occluded points at 60% transparency and collapses note cards by default.

The workflow is **mark → describe → agent edits → submit → user reviews**. FacetCue supplies annotation access and review records; actual model edits require separate Blender modeling tools connected to the agent. It does not execute arbitrary Python or modify geometry through its MCP endpoint.

## Choose your download

| Asset | Use |
| --- | --- |
| `facetcue-0.5.2.zip` | Installable Blender extension. Select it directly with Install from Disk; do not extract it. |
| `facetcue-0.5.2-py3-none-any.whl` | MCP companion for a separate Python 3.10+ environment. Install with pip. |
| `facetcue-0.5.2.tar.gz` | Source, documentation, build scripts and GitHub workflow for developers. |
| `SHA256SUMS` | SHA-256 hashes of the three archives above. |

GitHub's automatic **Source code** downloads are not the installable Blender extension. Use the named ZIP asset. The wheel does not bundle its dependencies; pip installs them from your package index. Do not install them into Blender's Python.

## Quick start

1. In Blender, open **Preferences → Add-ons → Install from Disk**, select `facetcue-0.5.2.zip` and enable **FacetCue for Blender**. Open its sidebar tab with **N** in the 3D View.
2. For agent access, install the wheel in a separate Python environment. Configure a stdio MCP server with that Python executable's absolute path and arguments `["-m", "agent_mcp.server"]`.
3. Keep Blender running. The client should discover `get_surface_annotations` and `submit_annotation_changes`. A single Blender instance is discovered automatically; multiple instances require selecting the intended session with `ASM_INSTANCE`.
4. In Object Mode / Solid shading, place a mark with **Ctrl+Alt+Shift+A**, write a request and press **Enter**. Ask your agent to read the marks and process the pending requests with its modeling tools.
5. Review the submitted changes in Blender, then save the `.blend` to preserve annotations and review history.

[English setup and shortcuts](https://github.com/Neuromancera113/facetcue/blob/main/README.md) · [中文安装与使用](https://github.com/Neuromancera113/facetcue/blob/main/README.zh-CN.md) · [完整使用说明](https://github.com/Neuromancera113/facetcue/blob/main/docs/guide.zh-CN.md)

## Compatibility and known limits

- Validated on **Windows / Blender 5.2.1 LTS**. The same packages target macOS and Linux; Blender runtime testing on those platforms remains outstanding. Python CI covers Windows, macOS and Linux with Python 3.10 and 3.12 and does not substitute for Blender runtime testing.
- Anchors require base meshes without enabled viewport modifiers or shape keys. Unsupported or changed topology preserves the note but invalidates its position; automatic reattachment is not available.
- Scene duplication does not copy annotations. High marker counts reduce color distinguishability; use the marker numbers as well.
- The local endpoint is authenticated and bound to `127.0.0.1`. FacetCue has no telemetry or cloud service. Sharing a saved `.blend` also shares its annotation metadata; agents handle the annotations they read under their own data policies.

## 中文介绍

**在模型表面写下修改要求，让 Agent 读取并执行，再回到 Blender 审核。**

每个标记独立关联一条自然语言要求，绑定三维网格表面并提供位置、法线与可见性。Agent 可通过 MCP 随时批量读取已确认注释，调用已连接的 Blender 建模工具逐项修改，再提交完成说明。用户通过蓝色状态点识别待审核项，快速跳转后通过或打回；保存 `.blend` 后，标记、目标关联与审核记录继续保留。

本版提供可拖动且记忆位置的紧凑注释框、Enter 保存、标记编辑与删除、状态筛选、近距离定位和审核撤回。X-Ray 中被遮挡标记以 60% 透明度显示。标记不产生可渲染或可导出的几何。

**下载选择：** 只使用 Blender 标记功能，安装 `facetcue-0.5.2.zip`；需要 Agent 读取与提交，再将 `.whl` 安装到独立 Python 3.10+ 环境并配置 MCP。实际建模需要另外连接 Blender 建模工具。请勿将 GitHub 自动生成的 Source code ZIP 当作插件安装。

这是 **Beta 版本**，已验证 Windows / Blender 5.2.1 LTS，macOS 与 Linux 尚需 Blender 实机验证。当前只支持无启用视口修改器、无形态键的基础网格，拓扑变化可能导致锚点失效。许可证为 **GPL-3.0-or-later（GPL 第 3 版或更高版本）**。
