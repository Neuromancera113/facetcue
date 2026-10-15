# FacetCue for Blender

[简体中文](README.zh-CN.md)

**Surface notes for agent edits and persistent review.**

Place annotatable markers on Blender objects and describe each requested change in natural language. When you ask an agent to process the marks, it can automatically read them through MCP, use its connected Blender modeling tools to make the changes, and submit the results for your review.

## Core capabilities

- **One marker per issue:** each marker has its own number, color and natural-language request, such as “move this panel up by 0.12 meters.”
- **Positions bound to 3D surfaces:** markers anchor to triangles on supported meshes and expose their current 3D position, normal and viewport visibility, beyond a screenshot's 2D coordinates.
- **Batch issue processing:** agents read multiple markers in one call, address them by ID and submit a separate completion summary for each. Larger sets use pagination.
- **Per-marker state:** track open, in-progress, modified/awaiting-review, resolved or rejected work; filter, navigate and review each issue independently.
- **Persistent review:** saving the `.blend` file preserves target associations, notes, states, latest change summaries and review records so work can continue after reopening it.

The workflow is **mark and describe → agent reads the batch → modeling tools apply edits → submit for review → approve or request changes**. The agent performs the automatic read-and-edit workflow; this add-on supplies annotations, MCP access and review records. Actual model changes require connected Blender modeling tools.

## Requirements

- Blender 4.2 or newer. The add-on uses Blender APIs and Python's standard library only.
- For MCP: a separate Python 3.10+ environment. No Python packages need to be installed into Blender.
- Designed for Windows, macOS and Linux. This release is validated on Windows with Blender 5.2.1 LTS; macOS and Linux runtime behavior still needs testing.

Version: **0.5.2**. License: [GPL-3.0-or-later](LICENSE). The Python distribution and command-line entry point are named `facetcue`.

Chinese documentation: [User and implementation guide](docs/guide.zh-CN.md).

## Install

1. Use `facetcue-0.5.2.zip` from the release assets. GitHub's automatic **Source code** downloads are for development and cannot be installed as Blender extensions directly.
2. In Blender, open **Preferences → Add-ons → Install from Disk**, select the ZIP and enable **FacetCue for Blender**. Enable only one installation of the add-on.
3. Open **3D View → N → FacetCue for Blender**. The local agent connection starts with the add-on.

Install the MCP companion from the release wheel, using your regular Python:

```sh
python -m venv .venv
# Windows: .venv/Scripts/python; macOS/Linux: .venv/bin/python
.venv/Scripts/python -m pip install ./facetcue-0.5.2-py3-none-any.whl
```

Configure your agent's stdio MCP client with the absolute path to that Python executable and these arguments:

```text
-m agent_mcp.server
```

A [TOML example](examples/codex-mcp.example.toml) is included. A single running Blender instance is discovered automatically; no third-party Blender MCP bridge, fixed port or personal installation path is required. With several Blender instances, set `ASM_INSTANCE` to the desired ID shown in the FacetCue for Blender panel. This companion handles annotations; use your modeling tools alongside it.

The same ZIP and wheel work across supported platforms; see [macOS installation](docs/macos.md) for platform-specific commands.

## Use

In **Object Mode / Solid shading**, place a point on a mesh and enter its note in a compact, fixed-width Blender dialog. **Enter** saves and closes; **Esc** cancels. Drag the dialog title to move it. It starts near the lower center of the viewport and remembers the last position for all subsequent note dialogs, including after restarting Blender. Position is stored in Blender’s user configuration, separately from the scene. Creating, editing and rejecting marks all use this dialog by default and preserve the viewport. For longer notes, save the point first, then choose **Multiline edit** in the sidebar to open a separate Text Editor. Existing multiline notes open as a compact preview with an explicit **Expand multiline editor** button, preserving every line break. In that expanded editor, **Shift+Enter** inserts a line break. Its size and position are managed by Blender; closing its window keeps the unconfirmed draft.

Click a marker to select it, or double-click its number to edit. The panel supports search, status filters and close-up navigation around the annotation point. Notes live in the `.blend` file as metadata and create no renderable or exportable geometry. Committed edits are readable immediately, even before saving the file; drafts are not returned to agents.

| Shortcut in Object Mode / 3D View | Action |
| --- | --- |
| Ctrl+Alt+Shift+M | Toggle marker display and point selection |
| Ctrl+Alt+Shift+A | Place a marker |
| Ctrl+Alt+Shift+Left / Right | Previous / next matching marker |
| Ctrl+Alt+Shift+Enter | Approve the selected modified marker |
| Ctrl+Alt+Shift+Backspace | Reject and edit its request |
| Ctrl+Alt+Shift+Z | Withdraw the most recent review decision |
| Ctrl+Alt+Shift+X | Confirm deletion of the selected marker |

**Ctrl+Z / Ctrl+Shift+Z** undo/redo annotation UI edits and deletion. The dedicated review-withdraw shortcut restores the previous note and review state without undoing geometry. Registration skips detected conflicting shortcuts and reports them in the panel; keys can be changed in Blender's Keymap preferences.

Marker display requires both the add-on's display switch and Blender's **Show Overlays** switch. Normal mode hides occluded markers. **Alt+Z (X-Ray)** reveals them at **40% opacity**, with note cards collapsed by default. Marker colors remain distinct; **a blue dot with a thin white border** indicates work awaiting review.

Agents call `get_surface_annotations()` before modeling, follow `next_offset` while `has_more` is true, then call `submit_annotation_changes()` with IDs, revisions and summaries of completed edits. Only the user approves or rejects work. Display toggles, object selection, hidden objects and filters never prevent agent reads. Connection failures return errors, not empty results.

## Limits and privacy

Anchors currently require base mesh objects without enabled modifiers or shape keys. Unsupported or changed topology returns an explicit invalid position while preserving the note; automatic reattachment is not provided. Scene duplication does not duplicate annotations. Exact colors become harder to distinguish as the number of markers grows.

The add-on opens an authenticated **127.0.0.1-only** endpoint and writes a temporary per-user discovery file. It accepts only annotation reads and completion submissions, never arbitrary Python or geometry commands. No cloud service or telemetry is used. The agent receives the requested annotations; review its own data policy. See [security details](SECURITY.md).

## Develop and build

```sh
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python scripts/export_mcp_catalog.py --check
python scripts/package_addon.py
python -m build
python scripts/check_release.py --blender /path/to/blender
```

CI validates code style, MCP contracts and release packages.

Build outputs are written to `dist/`. The extension ZIP, Python wheel and source archive are separate artifacts, accompanied by `SHA256SUMS`. The extension includes its linked documentation and configuration example. Packaging and checks never publish anything. See [release notes](docs/release-notes.md), [CONTRIBUTING](CONTRIBUTING.md) for module boundaries and [API](docs/api.zh-CN.md) for data semantics.
