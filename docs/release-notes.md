# FacetCue for Blender 0.5.2

Beta release · GPL-3.0-or-later

**Surface notes for agent edits and persistent review.**

Place a marker on a Blender surface and describe a change in natural language. An agent can read a batch through MCP, use connected Blender modeling tools to apply each change, and submit the results for user review.

## Features

- Independent issue markers, each with its own natural-language request, number and color.
- Anchors on supported mesh triangles, exposing current 3D position and viewport visibility.
- Batch MCP reads and completion submissions, with each result tied to its marker ID.
- Per-marker states for pending work, progress, review, resolution and requested changes.
- Notes, target associations, latest change summaries and review records retained when saving and reopening `.blend` files.

Compact draggable dialogs support Enter to save and remember their position. Search, close-up navigation, deletion, review withdrawal and X-Ray display support the review workflow. Marks remain viewport overlays and add no renderable geometry.

## Downloads and installation

| File | Purpose |
| --- | --- |
| `facetcue-0.5.2.zip` | Install from Disk in Blender Preferences, then enable FacetCue for Blender |
| `facetcue-0.5.2-py3-none-any.whl` | Install with pip in a separate Python environment for the MCP companion |
| `facetcue-0.5.2.tar.gz` | Source, tests, documentation and GitHub workflow for development |
| `SHA256SUMS` | SHA-256 hashes of the three release archives |

Requires Blender 4.2+ and, for MCP, separate Python 3.10+. GitHub's automatic **Source code** archives cannot be installed directly as Blender extensions. The MCP wheel needs its Python dependencies; the Blender add-on itself uses Blender APIs and the standard library only.

Validated on Windows with Blender 5.2.1 LTS. macOS and Linux runtime testing remains outstanding. Anchors require base meshes without enabled viewport modifiers or shape keys; topology changes can invalidate positions. This companion reads notes and records completion; modeling uses the agent's existing Blender tools.

## 中文说明

**表面标注、Agent 修改与持久化审阅。** 用户为每个问题放置独立标记并写下自然语言要求；标记绑定真实网格表面，Agent 可通过 MCP 批量读取，调用已连接的建模工具逐项修改并提交。每条标记分别管理待处理、进行中、待审核、已完成和已打回等状态。保存 `.blend` 后，标记、目标关联、修改说明和审核记录继续保留，重新打开可接续审阅。

安装请使用名为 `facetcue-0.5.2.zip` 的 Release 附件，MCP wheel 安装到独立 Python 环境。GPL-3.0-or-later 表示 GPL 第 3 版或更高版本。当前实机验证范围为 Windows / Blender 5.2.1 LTS；macOS、Linux 尚未实机验证。详细操作见随包提供的中英文 README 和中文使用说明。
