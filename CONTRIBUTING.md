# Contributing

Install Python 3.10+ and run `python -m pip install -e ".[dev]"` from the repository. Use `BLENDER_BIN` or `--blender` to select Blender. Do not install MCP dependencies into Blender.

## Code boundaries

- `core.py`: pure math, validation, colors and status definitions.
- `runtime.py`, `api.py`: persistent RNA metadata and main-thread data operations.
- `viewport.py`: projection, picking, occlusion and view navigation.
- `ui.py`, `editor.py`, `compact.py`, `floating.py`, `ux.py`, `shortcuts.py`: display, native editing and input.
- `review.py`: submission, review history and revision-protected withdrawal.
- `connection.py`: bounded, authenticated loopback endpoint, polled on Blender's main thread.
- `protocol.py`: dependency-free discovery constants shared with the companion.
- `agent_mcp/`: stdio MCP tools, discovery and transport; never imports `bpy`.

Use descriptive snake_case names and explicit coordinate spaces/units. Preserve persisted `asm_*` fields, operator IDs and response fields. Keep enum ordinals stable. Annotation reads must remain independent of selection, overlays and saving. Invalid positions return null with a reason. UI mutations own their Undo transaction; direct API mutations do not.

The product is FacetCue for Blender; the Python distribution, command and release archive prefix are `facetcue`. Keep the existing `blender_agent_marks` extension ID and module, `agent_mcp.server` entry module, `blender-marks://current` resource URI, stored data keys and local discovery paths stable so existing scenes, installations and client configurations remain compatible. The `facetcue` key in MCP configuration examples is a client-side label; existing labels remain valid.

All Blender data access runs on the main thread. Socket polling is nonblocking, bounded in size, duration and concurrent clients. Never log notes, tokens or request/response bodies. The connection accepts named annotation operations only.

## Development

```sh
blender --factory-startup --python scripts/dev_addon.py
python -m ruff check .
python -m ruff format --check .
python scripts/export_mcp_catalog.py --check
```

Validate Blender behavior with isolated processes, preferences, connection discovery and temporary files; never use an open user project. Regenerate and review `contracts/live_mcp_tools.json` when tool signatures change.

Solid-view queries use an object bounds hierarchy and Blender's evaluated mesh queries. Curves/text create a local BVH only when a ray reaches them. Real instances and unsupported evaluated types retain the conservative path. The hierarchy stores original object IDs and copied bounds/transforms, never evaluated instance RNA. It supports viewport-local filtering and reads display flags on each candidate query. Query the whole positive ray so in-front geometry behind a mark still takes priority.

`spatial.py` retains at most four dependency-graph indexes. Dependency-graph notifications refit transform changes, refresh membership when necessary and invalidate changed curve surfaces. Undo/Redo, loads and explicit invalidation drop the indexes. Each index retains at most 64 geometric ray-candidate lists, cleared on a refresh; visibility flags and surface hits are never cached across redraws. Unsupported instances use the conservative query directly. `begin_query_batch` clears ray results before each redraw; topology signatures, scene membership and edit-mode checks survive only until the next dependency-graph update. MCP reads use fresh annotation/geometry caches and current ray queries; never throttle them to stale viewport results. Validate spatial queries, visibility, mixed scenes and orbiting in an isolated Blender scene when changing this path.

`build_server(reader=..., submitter=...)` accepts transport substitutes for testing. `BridgeConfig(instance_id=..., timeout_seconds=...)` selects an instance without global configuration. `--log-level DEBUG` reports timing and sizes on stderr; stdout belongs to MCP.

## Release preparation

Keep the version in `pyproject.toml`, `bl_info` and `blender_manifest.toml` aligned. Run the source checks, then:

```sh
python scripts/package_addon.py
python -m build
python scripts/check_release.py --blender /path/to/blender
```

The release checker rejects unexpected files in all three archives, compares every packaged source/document/configuration file with the workspace, checks relative Markdown links, and validates metadata, the Blender manifest, extension installation and MCP tool discovery. Only known generated package metadata is exempt from byte comparison. CI performs source checks and package construction; runtime results require an actual Blender host. Do not claim untested platforms as verified.

For a [GitHub release](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), use the matching version tag and the current [release notes](docs/release-notes.md). Attach the extension ZIP, MCP wheel, source archive and `SHA256SUMS` from the same verified build. GitHub's automatic source downloads do not replace the installable extension ZIP.

Only current source, documentation, configuration and license belong in this repository. Exclude build environments, logs, `.blend` files, personal paths and runtime descriptors. No script pushes tags, creates a remote repository or publishes a release. GPL-3.0-or-later applies to project contributions; do not bundle incompatible code or dependencies.
