"""Native text input with a viewport-local drag handle and shared placement."""

import json
import math
import os
from pathlib import Path

import bpy

SESSION = None


def position_path():
    return Path(bpy.utils.user_resource("CONFIG", create=True)) / "agent_marks_ui.json"


def read_position():
    try:
        value = json.loads(position_path().read_text(encoding="utf-8"))["note_position"]
        if len(value) == 2 and all(
            type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in value
        ):
            return tuple(value)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return (0.5, 0.3)


def save_position(region, anchor):
    value = [
        max(0.0, min(1.0, (anchor[0] - region.x) / max(1, region.width))),
        max(0.0, min(1.0, (anchor[1] - region.y) / max(1, region.height))),
    ]
    path = position_path()
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"note_position": value}), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Session:
    def __init__(self, context, owner):
        self.window = context.window
        self.area = context.area
        self.region = next(r for r in context.area.regions if r.type == "WINDOW")
        self.owner = owner
        self.unit = 20 * context.preferences.system.ui_scale
        position = read_position()
        self.anchor = (
            int(self.region.x + self.region.width * position[0]),
            int(self.region.y + self.region.height * position[1]),
        )
        self.popup_region = None
        self.bounds = None
        self.drag_start = None
        self.composing = False

    def show(self):
        self.window.cursor_warp(*self.anchor)

        def open_popup():
            if SESSION is not self or not bpy.context.window_manager.asm_note_draft:
                return None
            with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
                bpy.context.window_manager.invoke_props_dialog(
                    self.owner,
                    width=min(480, max(160, int(self.region.width / (self.unit / 20) - 40))),
                    confirm_text="保存",
                    title="编辑注释 · 拖动标题移动",
                )
                bpy.ops.asm.note_events("INVOKE_DEFAULT")
            return None

        bpy.app.timers.register(open_popup, first_interval=0.05)

    def end_text_edit(self, context):
        value = context.window_manager.asm_note_input
        # Blender exposes no blur operation. End the native edit, then restore its
        # live RNA value before forwarding the same title/confirm event.
        with context.temp_override(area=None, region=self.popup_region):
            if bpy.ops.ui.copy_data_path_button.poll():
                bpy.ops.ui.button_string_clear()
        context.window_manager.asm_note_input = value

    def observe(self, context, event):
        if event.type == "IME_COMPOSITION_START":
            self.composing = True
        elif event.type == "IME_COMPOSITION_END":
            self.composing = False
        if self.composing:
            return
        if not self.popup_region:
            return
        region = self.popup_region
        self.bounds = (region.x, region.y, region.width, region.height)
        x, y, width, height = self.bounds
        title = (
            x + self.unit < event.mouse_x < x + width - self.unit
            and y + height - 2 * self.unit < event.mouse_y < y + height - 0.6 * self.unit
        )
        if event.type in {"RET", "NUMPAD_ENTER", "ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.end_text_edit(context)
        if event.type == "LEFTMOUSE" and event.value == "PRESS" and title:
            self.end_text_edit(context)
            self.drag_start = (region.x, region.y, self.anchor)
        elif event.type == "LEFTMOUSE" and event.value == "RELEASE" and self.drag_start:
            left, bottom, anchor = self.drag_start
            self.anchor = (anchor[0] + region.x - left, anchor[1] + region.y - bottom)
            try:
                save_position(self.region, self.anchor)
            except OSError:
                self.owner.report({"WARNING"}, "注释框已移动，但无法保存位置到 Blender 配置目录")
            self.drag_start = None


def close():
    global SESSION
    SESSION = None


def unregister():
    close()


class ASM_OT_note_events(bpy.types.Operator):
    bl_idname = "asm.note_events"
    bl_label = "注释输入事件"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        self.session = SESSION
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if SESSION is not self.session:
            return {"CANCELLED", "PASS_THROUGH"}
        self.session.observe(context, event)
        return {"PASS_THROUGH"}
