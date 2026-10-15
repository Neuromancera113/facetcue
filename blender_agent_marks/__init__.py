"""Agent-readable surface annotations. Importing this package does not modify Blender."""

bl_info = {
    "name": "FacetCue for Blender",
    "author": "FacetCue contributors",
    "version": (0, 5, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > FacetCue for Blender",
    "description": "Annotate mesh surfaces for agent edits and persistent review via MCP",
    "category": "3D View",
}


def register():
    from . import connection, runtime, ui

    runtime.register()
    ui.register()
    connection.start()


def unregister():
    from . import connection, runtime, ui

    connection.stop()
    ui.unregister()
    runtime.unregister()
