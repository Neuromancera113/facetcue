# Repository conventions

Read CONTRIBUTING.md before editing. Keep the implementation small and fork-friendly.

- Preserve stored asm_* fields, public operator IDs, response fields and enum ordinals.
- Separate geometry, Blender data, presentation and transport. All bpy access stays on the main thread.
- Prefer Blender APIs and the standard library. No OS-specific window APIs or dependencies on another Blender MCP installation.
- Reads work without saving, selection or visible overlays. Errors never become successful empty results.
- Keep only comments explaining non-obvious invariants. Never log notes or connection tokens.
- Run style, MCP catalog and release checks. Validate Blender behavior in isolated scenes; never use a user's scene as a fixture.
- Keep generated artifacts and personal configuration out of Git and packages.
- Packaging is separate from publishing. Only publish with explicit user authorization.
