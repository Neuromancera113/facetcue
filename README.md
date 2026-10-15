# FacetCue for Blender

[简体中文](README.zh-CN.md) · [Downloads](https://github.com/Neuromancera113/facetcue/releases) · [User guide](docs/guide.zh-CN.md) · [Release notes](docs/release-notes.md)

**Put a note on the surface. Let your agent work from it. Review the result in Blender.**

FacetCue turns changes you want into independent, annotated markers on a Blender model. Each marker tells an agent **what to change and where**: a natural-language request, a surface anchor, current 3D coordinates and viewport visibility. Through MCP, the agent can read the requests in a batch, apply edits using its connected Blender modeling tools, and submit each result for your review.

**0.5.2 · Beta · Blender 4.2+ · Python 3.10+ for MCP · [GPL-3.0-or-later](LICENSE)**

## What you can do

| Capability | How it works |
| --- | --- |
| One marker, one issue | Give each requested change its own note, number and distinct color. |
| Surface-bound context | Anchor to a supported mesh triangle; expose current position, normal and anchor validity. |
| Immediate agent access | Read confirmed notes without selecting objects, saving the file, taking screenshots or showing overlays. |
| Batch processing | Read multiple issues, follow pagination for larger sets, and submit completion summaries by marker ID. |
| Review in Blender | Track open, in-progress, awaiting-review, resolved, changes-requested and archived states; locate and review each issue. |
| Continue later | Save the `.blend` to retain notes, object associations, states, latest change summaries and review history. |

Markers are viewport overlays and scene metadata. They add no renderable or exportable geometry. You control their display; agents can still read confirmed notes while markers or objects are hidden.

## From a note to a reviewed change

1. **Mark:** in Object Mode with Solid shading, place a marker on a supported mesh surface.
2. **Describe:** enter a request, such as “move this panel up by 0.12 Blender units; preserve its shape and size.” Press **Enter** to save.
3. **Delegate:** ask your agent to read the FacetCue marks and process the requested changes.
4. **Inspect:** completed submissions gain a **blue dot with a narrow white border**. The original marker color stays unchanged.
5. **Review:** jump to the point for a close view, then approve or reject and revise the request. Save your `.blend` to keep the review record.

FacetCue supplies the annotation and review connection. **Model edits require an agent with separate Blender modeling tools.** Installing FacetCue alone does not start an autonomous editing session or provide arbitrary Python execution.

## Install

### 1. Blender extension

Download **`facetcue-0.5.2.zip`** from [Releases](https://github.com/Neuromancera113/facetcue/releases). In Blender, use **Preferences → Add-ons → Install from Disk**, select the ZIP without extracting it, and enable **FacetCue for Blender**. Open **3D View → N → FacetCue for Blender**. Enable only one installation of the add-on.

The ZIP is enough for local annotation and review. GitHub's automatic **Source code** archives are for development and cannot be installed directly as Blender extensions.

### 2. MCP companion

For agent access, download **`facetcue-0.5.2-py3-none-any.whl`** from the same release. Run these commands in its download directory with a separate Python 3.10+ installation.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\facetcue-0.5.2-py3-none-any.whl
```

macOS / Linux:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install ./facetcue-0.5.2-py3-none-any.whl
```

The wheel's dependencies are installed by pip; they are not bundled. The Blender add-on uses Blender APIs and the standard library only. Do not install MCP dependencies into Blender's Python.

### 3. Agent connection

Add a **stdio MCP server** to your agent client. Set `command` to the absolute path of the Python executable above and `args` to `["-m", "agent_mcp.server"]`. See the [TOML configuration example](examples/codex-mcp.example.toml).

Keep Blender running with the add-on enabled, then reload your client's MCP configuration. One Blender instance is discovered automatically. With several instances, set `ASM_INSTANCE` to the session ID shown in the target Blender panel; update it after restarting that connection. No fixed port or third-party Blender MCP bridge is needed for annotation access.

The client should discover two tools:

| Tool | Purpose |
| --- | --- |
| `get_surface_annotations()` | Read notes, stable IDs, revisions, positions and visibility. Start without arguments; follow `next_offset` while `has_more` is true. |
| `submit_annotation_changes()` | After successful edits, submit marker IDs, the revisions read before editing and a summary of actual work. This marks the results for user review. |

Example request to your agent:

> Read my FacetCue surface annotations. Process the pending requests with the connected Blender modeling tools, preserve the stated constraints, and submit a completion summary for each successful change. Leave approval to me.

Display toggles, object selection and sidebar filters do not restrict agent reads. Unconfirmed drafts are excluded. Connection failures return errors, not empty results. See the [API guide](docs/api.zh-CN.md) for revision handling and data semantics.

## Editing and navigation

Notes open in a compact, draggable Blender dialog near the lower center of the viewport. **Enter saves; Esc cancels.** Drag its title to move it; later note dialogs reuse that position, including after restarting Blender. Click a marker to select it or double-click its number to edit. Longer notes have an explicit **Multiline edit** entry in the sidebar; existing line breaks are preserved. Search, status filters and close-up navigation help you work through a batch.

| Shortcut in Object Mode / 3D View | Action |
| --- | --- |
| Ctrl+Alt+Shift+M | Toggle marker display and point selection |
| Ctrl+Alt+Shift+A | Place a marker |
| Ctrl+Alt+Shift+Left / Right | Previous / next matching marker |
| Ctrl+Alt+Shift+Enter | Approve the selected modified marker |
| Ctrl+Alt+Shift+Backspace | Reject and edit its request |
| Ctrl+Alt+Shift+Z | Withdraw the most recent review decision |
| Ctrl+Alt+Shift+X | Confirm deletion of the selected marker |

Annotation UI edits and deletion support Blender **Ctrl+Z / Ctrl+Shift+Z**. Review withdrawal restores the previous note and review state without undoing geometry. Detected keymap conflicts are skipped and reported in the panel; change bindings in Blender's Keymap preferences as needed.

Both FacetCue display and Blender **Show Overlays** must be enabled to see markers. Normal mode hides occluded points. **Alt+Z (X-Ray)** reveals them at **60% transparency / 40% opacity**, with note cards collapsed by default. Review badges follow the same visibility and transparency as their markers.

## Compatibility and limits

- Requires **Blender 4.2+**. Windows with **Blender 5.2.1 LTS** has been validated. The same packages target macOS and Linux, but Blender runtime behavior on those platforms still needs testing. Cross-platform Python CI does not establish Blender runtime compatibility.
- Anchors support **base mesh objects without enabled viewport modifiers or shape keys**. Unsupported or changed topology preserves the note but returns an explicitly invalid position; automatic reattachment is not provided.
- Scene duplication does not duplicate annotations. As marker counts grow, use numbers alongside colors to distinguish issues.
- Confirmed edits are immediately available to agents. Save the `.blend` to preserve them across sessions; sharing that file also shares its stored annotation metadata.

## Privacy and development

The add-on serves authenticated requests on **127.0.0.1 only**, using a temporary per-user discovery file. It accepts annotation reads and completion submissions, not geometry commands or arbitrary Python. FacetCue has no cloud service or telemetry; annotations read by your agent are subject to that agent's data policy. See [SECURITY](SECURITY.md).

```sh
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python scripts/export_mcp_catalog.py --check
python scripts/package_addon.py
python -m build
python scripts/check_release.py --blender /path/to/blender
```

Builds produce the extension ZIP, MCP wheel, source archive and `SHA256SUMS` in `dist/`. CI checks style, MCP contracts and package contents; the optional Blender check validates installation in an isolated process. Packaging never publishes. See [CONTRIBUTING](CONTRIBUTING.md) for module boundaries and development guidance.
