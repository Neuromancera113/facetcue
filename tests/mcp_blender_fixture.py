"""Disposable Blender fixture using the actual annotation connection."""

import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import blender_agent_marks
from blender_agent_marks import api, connection

out = Path(sys.argv[sys.argv.index("--") + 1])
blender_agent_marks.register()
scene = bpy.context.scene
obj = bpy.data.objects["Cube"]
obj.data.calc_loop_triangles()
tri = obj.data.loop_triangles[0]
point = list(sum((obj.data.vertices[i].co for i in tri.vertices), Vector()) / 3)
first = api.create(scene, obj.name, 0, point, "未保存的注释：修改此处圆角")
broken = api.create(scene, obj.name, 0, point, "坏锚点的注释仍然必须能读")
api.get_mark(scene, broken["id"]).anchor_json = "{corrupt"
obj.hide_set(True)
bpy.context.window_manager.asm_show_overlay = False
other = bpy.data.scenes.new("Other scene")
copy = obj.copy()
other.collection.objects.link(copy)
third = api.create(other, copy.name, 0, point, "其他场景的已归档注释")
api.update(other, third["id"], 1, status="ARCHIVED")

(out / "ready.json").write_text(
    json.dumps(
        {
            "first_id": first["id"],
            "broken_id": broken["id"],
            "archived_id": third["id"],
            "instance_id": connection._server.instance_id,
        }
    ),
    encoding="utf-8",
)
deadline = time.monotonic() + 60
while time.monotonic() < deadline and not (out / "stop").exists():
    if (out / "update").exists():
        mark = api.get_mark(scene, first["id"])
        if mark.revision == 1:
            api.update(scene, mark.marker_id, 1, note="实时修改后的注释")
        (out / "updated").touch()
    connection._server.poll()
    time.sleep(0.01)
blender_agent_marks.unregister()
