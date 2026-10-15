import datetime
import math
import time
import uuid

import blf
import bpy
import gpu
from bpy.props import EnumProperty, IntProperty, StringProperty
from gpu_extras.batch import batch_for_shader

from . import api, connection, editor, review, runtime, shortcuts, ux, viewport
from .core import MAX_NOTE_LENGTH, STATUS_BADGES, STATUSES, MarkError

_handle = None
_keymaps = []
_shader = None
_pending = {}
_active_placements = {}
_last_click = None


def prepare_add(scene, obj, index, point, signature):
    token = str(uuid.uuid4())
    _pending[token] = {
        "scene": scene,
        "target": obj,
        "mesh": obj.data,
        "index": index,
        "point": tuple(point),
        "fingerprint": signature,
        "vertices": [
            list(obj.data.vertices[i].co) for i in obj.data.loop_triangles[index].vertices
        ],
    }
    return token


def commit_pending(scene, token, note):
    pending = _pending.get(token)
    if not pending:
        raise MarkError("NOT_FOUND", "放点已过期，请重新放点；当前草稿可保留文字")
    if not note.strip():
        raise MarkError("INVALID_NOTE", "请填写注释后再确认")
    try:
        target, index = pending["target"], pending["index"]
        mesh, signature = api.geometry(target)
        if mesh != pending["mesh"] or signature != pending["fingerprint"]:
            raise MarkError("STALE_TOPOLOGY", "Surface changed while writing the note")
        current = [list(mesh.vertices[i].co) for i in mesh.loop_triangles[index].vertices]
        if current != pending["vertices"]:
            raise MarkError("STALE_TOPOLOGY", "Surface moved while writing the note")
        if not pending["scene"] or pending["scene"] != scene:
            raise MarkError("SCENE_NOT_FOUND", "添加期间场景已切换，请重新放点")
        record = api.create(scene, target.name, index, pending["point"], note)
    except ReferenceError as exc:
        raise MarkError("NOT_FOUND", "Surface no longer exists") from exc
    _pending.pop(token, None)
    return record


def disc(shader, x, y, radius, color, inner_radius=0):
    vertices = []
    for i in range(24):
        a, b = i * math.tau / 24, (i + 1) * math.tau / 24
        inner_a = (x + inner_radius * math.cos(a), y + inner_radius * math.sin(a))
        inner_b = (x + inner_radius * math.cos(b), y + inner_radius * math.sin(b))
        outer_a = (x + radius * math.cos(a), y + radius * math.sin(a))
        outer_b = (x + radius * math.cos(b), y + radius * math.sin(b))
        vertices.extend([inner_a, outer_a, outer_b])
        if inner_radius:
            vertices.extend([inner_a, outer_b, inner_b])
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(shader, "TRIS", {"pos": vertices}).draw(shader)


def rectangle(shader, x, y, width, height, color):
    shader.bind()
    shader.uniform_float("color", color)
    batch_for_shader(
        shader,
        "TRIS",
        {
            "pos": [
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y),
                (x + width, y + height),
                (x, y + height),
            ]
        },
    ).draw(shader)


def text(x, y, value, color=(1, 1, 1, 1), size=13):
    blf.size(0, size)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, value)


def faded(color, opacity):
    return (*color[:3], color[3] * opacity)


def context_view(context):
    region = next(r for r in context.area.regions if r.type == "WINDOW")
    return viewport.ViewportContext(
        context.window, context.area, region, context.area.spaces.active
    )


def drawn_marks(context):
    if not context.window_manager.asm_show_overlay or not context.space_data.overlay.show_overlays:
        return
    viewport.begin_query_batch(ux.GEOMETRY_CACHE)
    view = context_view(context)
    for mark in api.marks(context.scene):
        if mark.status == "ARCHIVED" or not ux.matches(mark, context.window_manager):
            continue
        try:
            data = api.serialize(context.scene, mark, view, ux.GEOMETRY_CACHE)
        except (ValueError, TypeError, KeyError, ReferenceError):
            continue
        if data["viewport"]["overlay_drawn"]:
            yield mark, data


def draw_card(context, shader, x, y, mark, scale, points):
    size = 13 * scale
    blf.size(0, size)
    right = context.region.width
    if context.space_data.show_region_ui:
        right = min(
            (
                r.x - context.region.x
                for r in context.area.regions
                if r.type == "UI" and r.width > 1
            ),
            default=right,
        )
    width = min(310 * scale, max(80 * scale, right - 24 * scale))
    lines = ux.wrap(
        mark.note or "（暂无注释）", width - 24 * scale, lambda s: blf.dimensions(0, s)[0]
    )
    if len(lines) > 5:
        lines = lines[:4] + ["… 在侧栏打开完整注释"]
    height = (len(lines) * 19 + 40) * scale
    left = min(max(8 * scale, x + 23 * scale), max(8 * scale, right - width - 8 * scale))
    bottom = y + 23 * scale
    if any(
        left - 18 * scale < px < left + width + 18 * scale
        and bottom - 18 * scale < py < bottom + height + 18 * scale
        for px, py in points
    ):
        bottom = max(py for px, py in points) + 24 * scale
    if bottom + height > context.region.height - 30 * scale:
        bottom = y - 23 * scale - height
    bottom = max(8 * scale, bottom)
    rectangle(shader, left, bottom, width, height, (0.025, 0.032, 0.042, 0.96))
    rectangle(shader, left, bottom, 3 * scale, height, mark.color)
    text(
        left + 12 * scale,
        bottom + height - 23 * scale,
        f"M{mark.number:04d}  ·  {ux.STATUS_LABELS[mark.status]}",
        mark.color,
        size,
    )
    for i, line in enumerate(lines):
        text(left + 12 * scale, bottom + height - (46 + 19 * i) * scale, line, size=size)


def draw():
    global _shader
    context = bpy.context
    selected = ux.active_mark(context.scene)
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    scale = context.preferences.system.ui_scale
    old_blend = gpu.state.blend_get()
    gpu.state.blend_set("ALPHA")
    card = None
    points = []
    try:
        for mark, data in drawn_marks(context):
            x, y = data["viewport"]["screen_px"]
            opacity = data["viewport"].get("display_opacity", 1.0)
            points.append((x, y))
            is_active = selected and selected.marker_id == mark.marker_id
            if is_active:
                disc(_shader, x, y, 18 * scale, faded((1, 1, 1, 0.95), opacity), 15 * scale)
                if (
                    not viewport.is_xray(context.space_data)
                    or context.window_manager.asm_expand_xray_note
                ):
                    card = x, y, mark
            # Non-overlapping ring geometry prevents stacked translucent discs
            # from making an occluded marker more opaque than requested.
            disc(_shader, x, y, 15 * scale, faded((0.02, 0.02, 0.02, 0.95), opacity), 12 * scale)
            disc(_shader, x, y, 12 * scale, faded(mark.color, opacity))
            label = str(mark.number)
            size = (12 if len(label) < 3 else 9) * scale
            blf.size(0, size)
            text(
                x - blf.dimensions(0, label)[0] / 2,
                y - 4 * scale,
                label,
                (0.02, 0.02, 0.02, opacity),
                size,
            )
            badge = STATUS_BADGES.get(mark.status)
            if badge:
                # One draw path guarantees the badge shares its marker's
                # visibility, filtering, X-Ray behavior and screen position.
                disc(
                    _shader,
                    x + 12 * scale,
                    y + 12 * scale,
                    5.2 * scale,
                    (1, 1, 1, opacity),
                    4.2 * scale,
                )
                disc(
                    _shader,
                    x + 12 * scale,
                    y + 12 * scale,
                    4.2 * scale,
                    faded(badge["color"], opacity),
                )
        if card:
            draw_card(context, _shader, *card, scale, points)
    finally:
        gpu.state.blend_set(old_blend)


class ASM_OT_add_note(bpy.types.Operator):
    bl_idname = "asm.add_note"
    bl_label = "添加表面注释"
    bl_description = "输入修改要求并确认；取消不会留下空标记"
    bl_options = {"UNDO"}
    note: StringProperty(name="注释", maxlen=MAX_NOTE_LENGTH)
    token: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        try:
            editor.open_pending(context, self.token)
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}

    def execute(self, context):
        try:
            commit_pending(context.scene, self.token, self.note)
        except (MarkError, ReferenceError) as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_place(bpy.types.Operator):
    bl_idname = "asm.place"
    bl_label = "在表面添加注释"
    bl_description = "点击表面立即写注释；Enter 确认退出。Ctrl+Alt+Shift+A"

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        key = context.area.as_pointer()
        if key in _active_placements:
            self.report({"INFO"}, "已在添加模式：点击模型表面，或按 Esc 退出")
            return {"CANCELLED"}
        reason = viewport.support_reason(context.scene, context_view(context))
        if reason or context.mode != "OBJECT":
            exc = MarkError("UNSUPPORTED_VIEW", reason) if reason else MarkError("EDIT_MODE", "")
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        self._area = context.area
        self._scene = context.scene
        self._window = context.window
        self._cancelled = False
        self._last_error = None
        context.window_manager.asm_show_overlay = True
        _active_placements[key] = self
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("CROSSHAIR")
        context.area.header_text_set("点击模型表面添加注释 · 可以旋转视图 · Esc / 右键取消")
        return {"RUNNING_MODAL"}

    def cleanup(self, context):
        self._area.header_text_set(None)
        self._window.cursor_modal_restore()
        _active_placements.pop(self._area.as_pointer(), None)
        self._cancelled = True

    def modal(self, context, event):
        if self._cancelled:
            return {"CANCELLED"}
        if (
            event.type == "M"
            and event.value == "PRESS"
            and event.ctrl
            and event.alt
            and event.shift
        ):
            context.window_manager.asm_show_overlay = False
            self.cleanup(context)
            return {"CANCELLED"}
        if (
            event.type in {"ESC", "RIGHTMOUSE"}
            or context.scene != self._scene
            or self._area.type != "VIEW_3D"
        ):
            self.cleanup(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = next(r for r in self._area.regions if r.type == "WINDOW")
            view = viewport.ViewportContext(
                context.window, self._area, region, self._area.spaces.active
            )
            try:
                obj, index, point, signature = viewport.pick_surface(
                    context.scene, view, event.mouse_x - region.x, event.mouse_y - region.y
                )
            except MarkError as exc:
                label = ux.message(exc)
                error_key = exc.code, str(exc)
                if self._last_error != error_key:
                    self.report({"WARNING"}, label)
                self._last_error = error_key
                self._area.header_text_set(label + " · Esc 取消")
                if exc.code in {"UNSUPPORTED_VIEW", "EDIT_MODE"}:
                    self.cleanup(context)
                    return {"CANCELLED"}
                return {"RUNNING_MODAL"}
            self.cleanup(context)
            token = prepare_add(context.scene, obj, index, point, signature)
            try:
                editor.open_pending(context, token)
            except MarkError as exc:
                self.report({"WARNING"}, ux.message(exc))
                return {"CANCELLED"}
            return {"FINISHED"}
        return {"PASS_THROUGH"}


class ASM_OT_select(bpy.types.Operator):
    bl_idname = "asm.select"
    bl_label = "选择表面注释"
    bl_description = "单击编号查看，双击编辑词条；未点中时保留 Blender 的正常选择"

    @classmethod
    def poll(cls, context):
        return (
            context.area
            and context.area.type == "VIEW_3D"
            and context.region.type == "WINDOW"
            and context.mode == "OBJECT"
        )

    def invoke(self, context, event):
        global _last_click
        radius = 18 * context.preferences.system.ui_scale
        candidates = []
        for mark, data in drawn_marks(context):
            x, y = data["viewport"]["screen_px"]
            distance = math.hypot(x - event.mouse_region_x, y - event.mouse_region_y)
            scale = context.preferences.system.ui_scale
            badge_hit = (
                mark.status in STATUS_BADGES
                and math.hypot(
                    x + 12 * scale - event.mouse_region_x, y + 12 * scale - event.mouse_region_y
                )
                <= 5.2 * scale
            )
            if distance <= radius or badge_hit:
                candidates.append((distance, mark.marker_id))
        if not candidates:
            _last_click = None
            return {"PASS_THROUGH"}
        identifier = min(candidates)[1]
        now = time.monotonic()
        key = (context.window.as_pointer(), context.area.as_pointer(), identifier)
        xy = (event.mouse_region_x, event.mouse_region_y)
        # We consume PRESS to preserve object selection. Recognize the second
        # press ourselves as well as Blender's DOUBLE_CLICK keymap event.
        double = event.value == "DOUBLE_CLICK" or (
            _last_click is not None
            and _last_click[0] == key
            and now - _last_click[1] <= context.preferences.inputs.mouse_double_click_time / 1000
            and math.dist(xy, _last_click[2]) <= 6 * context.preferences.system.ui_scale
        )
        _last_click = None if double else (key, now, xy)
        store = api.document(context.scene)
        previously_active = ux.active_mark(context.scene)
        same_marker = previously_active and previously_active.marker_id == identifier
        store.asm_active_index = next(
            i for i, m in enumerate(store.asm_marks) if m.marker_id == identifier
        )
        if viewport.is_xray(context.space_data) and not double:
            manager = context.window_manager
            manager.asm_expand_xray_note = not manager.asm_expand_xray_note if same_marker else True
        api.redraw()
        if double:
            bpy.ops.asm.edit("INVOKE_DEFAULT", marker_id=identifier)
        return {"FINISHED"}


class ASM_OT_edit(bpy.types.Operator):
    bl_idname = "asm.edit"
    bl_label = "编辑词条"
    bl_description = "在紧凑弹窗中编辑注释；Enter 保存，可主动展开多行编辑"
    bl_options = {"REGISTER", "UNDO"}
    note: StringProperty(name="注释", maxlen=MAX_NOTE_LENGTH)
    status: EnumProperty(name="状态", items=[(s, ux.STATUS_LABELS[s], "") for s in STATUSES])
    marker_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    expected_revision: IntProperty(options={"HIDDEN", "SKIP_SAVE"}, min=1)
    scene_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        try:
            mark = (
                api.get_mark(context.scene, self.marker_id)
                if self.marker_id
                else ux.active_mark(context.scene)
            )
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        if not mark:
            return {"CANCELLED"}
        store = api.document(context.scene)
        store.asm_active_index = next(
            i for i, m in enumerate(store.asm_marks) if m.marker_id == mark.marker_id
        )
        # Every edit entry point resumes the same unconfirmed draft.
        return bpy.ops.asm.edit_multiline("EXEC_DEFAULT", marker_id=mark.marker_id, compact=True)

    def execute(self, context):
        try:
            scene = bpy.data.scenes.get(self.scene_name) if self.scene_name else context.scene
            if scene is None:
                raise MarkError("SCENE_NOT_FOUND", "原场景已不存在，请重新打开词条")
            api.update(scene, self.marker_id, self.expected_revision, self.note, self.status)
        except MarkError as exc:
            if exc.code == "REVISION_CONFLICT":
                draft = editor.create_draft(
                    api.get_mark(scene, self.marker_id), self.note, self.expected_revision
                )
                self.report(
                    {"WARNING"}, f"注释已更新；输入已保留为「{draft.name}」，请用多行编辑合并"
                )
                return {"CANCELLED"}
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_focus(bpy.types.Operator):
    bl_idname = "asm.focus"
    bl_label = "定位到表面"
    bl_description = "从表面法线方向查看此处，保留当前物体选择"
    marker_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        try:
            mark = (
                api.get_mark(context.scene, self.marker_id)
                if self.marker_id
                else ux.active_mark(context.scene)
            )
            if not mark:
                return {"CANCELLED"}
            viewport.focus_mark(context.scene, mark)
            select_mark(context, mark)
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


def select_mark(context, mark):
    store = api.document(context.scene)
    store.asm_active_index = next(
        i for i, candidate in enumerate(store.asm_marks) if candidate.marker_id == mark.marker_id
    )
    context.window_manager.asm_show_overlay = True
    context.window_manager.asm_expand_xray_note = False
    api.redraw()


def in_object_view(context):
    return context.area and context.area.type == "VIEW_3D" and context.mode == "OBJECT"


class ASM_OT_toggle_marks(bpy.types.Operator):
    bl_idname = "asm.toggle_marks"
    bl_label = "开关标记功能"
    bl_description = "开关标记显示与点击交互；agent 始终可读取。Ctrl+Alt+Shift+M"

    @classmethod
    def poll(cls, context):
        return in_object_view(context)

    def execute(self, context):
        manager = context.window_manager
        manager.asm_show_overlay = not manager.asm_show_overlay
        if not manager.asm_show_overlay:
            for placement in list(_active_placements.values()):
                placement.cleanup(context)
        return {"FINISHED"}


class ASM_OT_navigate(bpy.types.Operator):
    bl_idname = "asm.navigate"
    bl_label = "跳转注释位置"
    bl_description = "按编号循环跳转当前筛选中的标记，并围绕注释点近距离观察"
    direction: IntProperty(default=1, min=-1, max=1)

    @classmethod
    def poll(cls, context):
        return in_object_view(context)

    def execute(self, context):
        candidates = sorted(
            (
                mark
                for mark in api.marks(context.scene)
                if mark.status != "ARCHIVED" and ux.matches(mark, context.window_manager)
            ),
            key=lambda mark: mark.number,
        )
        if not candidates:
            self.report({"INFO"}, "当前筛选中没有可跳转的标记")
            return {"CANCELLED"}
        current = ux.active_mark(context.scene)
        index = next(
            (
                i
                for i, mark in enumerate(candidates)
                if current and mark.marker_id == current.marker_id
            ),
            None,
        )
        direction = -1 if self.direction < 0 else 1
        start = index if index is not None else (-1 if direction > 0 else 0)
        for step in range(1, len(candidates) + 1):
            mark = candidates[(start + direction * step) % len(candidates)]
            try:
                viewport.focus_mark(context.scene, mark)
                select_mark(context, mark)
                return {"FINISHED"}
            except MarkError:
                continue
        self.report({"WARNING"}, "当前标记位置不可定位；可在列表中编辑注释")
        return {"CANCELLED"}


class ASM_OT_review(bpy.types.Operator):
    bl_idname = "asm.review"
    bl_label = "审核标记"
    bl_description = "通过、打回并编辑、或撤回最近一次审核；不撤销模型修改"
    bl_options = {"UNDO"}
    action: EnumProperty(
        items=[("APPROVE", "通过", ""), ("REJECT", "打回并编辑", ""), ("WITHDRAW", "撤回审核", "")]
    )

    @classmethod
    def poll(cls, context):
        return in_object_view(context)

    def execute(self, context):
        try:
            if self.action == "WITHDRAW":
                record = review.withdraw(context.scene)
                select_mark(context, api.get_mark(context.scene, record["id"]))
                return {"FINISHED"}
            mark = ux.active_mark(context.scene)
            if not mark:
                return {"CANCELLED"}
            if self.action == "REJECT":
                return bpy.ops.asm.edit_multiline(
                    marker_id=mark.marker_id, action="REJECT", compact=True
                )
            review.decide(context.scene, mark.marker_id, mark.revision, "APPROVE")
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_status(bpy.types.Operator):
    bl_idname = "asm.set_status"
    bl_label = "更新注释状态"
    bl_description = "更新当前标记的待办状态；可撤销"
    bl_options = {"UNDO"}
    status: EnumProperty(items=[(s, ux.STATUS_LABELS[s], "") for s in STATUSES])

    def execute(self, context):
        mark = ux.active_mark(context.scene)
        if not mark:
            return {"CANCELLED"}
        try:
            api.update(context.scene, mark.marker_id, mark.revision, status=self.status)
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_delete(bpy.types.Operator):
    bl_idname = "asm.delete"
    bl_label = "删除当前标记"
    bl_description = "删除当前标记和注释；Ctrl+Z 可恢复。Ctrl+Alt+Shift+X"
    bl_options = {"UNDO"}
    marker_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    expected_revision: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})
    _target_scene = None

    @classmethod
    def poll(cls, context):
        if not in_object_view(context) or _active_placements:
            return False
        mark = ux.active_mark(context.scene)
        return mark is not None and ux.matches(mark, context.window_manager)

    def invoke(self, context, event):
        mark = ux.active_mark(context.scene)
        self.marker_id = mark.marker_id
        self.expected_revision = mark.revision
        self._target_scene = context.scene
        return context.window_manager.invoke_confirm(
            self,
            event,
            title=f"删除标记 M{mark.number:04d}？",
            message="删除此标记和注释；Ctrl+Z 可恢复。模型保持不变。",
            confirm_text="删除标记",
            icon="QUESTION",
        )

    def execute(self, context):
        try:
            if self._target_scene and self._target_scene != context.scene:
                raise MarkError("SCENE_CHANGED", "Scene changed while confirming deletion")
            if not self.marker_id:
                mark = ux.active_mark(context.scene)
                self.marker_id, self.expected_revision = mark.marker_id, mark.revision
            result = api.delete(context.scene, self.marker_id, self.expected_revision)
        except MarkError as exc:
            self.report({"WARNING"}, ux.message(exc))
            return {"CANCELLED"}
        context.window_manager.asm_expand_xray_note = False
        self.report({"INFO"}, f"已删除 {result['label']} · Ctrl+Z 可恢复")
        return {"FINISHED"}


class ASM_UL_marks(bpy.types.UIList):
    def filter_items(self, context, data, propname):
        return (
            [
                self.bitflag_filter_item if ux.matches(m, context.window_manager) else 0
                for m in getattr(data, propname)
            ],
            [],
        )

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"M{item.number:04d}", icon=ux.STATUS_ICONS[item.status])
        row.label(text=item.note.replace("\n", " ")[:45] or "（暂无注释）")
        row.operator_context = "INVOKE_DEFAULT"
        row.operator(
            "asm.edit", text="", icon="GREASEPENCIL", emboss=False
        ).marker_id = item.marker_id
        row.operator("asm.focus", text="", icon="VIEWZOOM", emboss=False).marker_id = item.marker_id


class ASM_PT_panel(bpy.types.Panel):
    bl_label = "表面注释"
    bl_idname = "ASM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "FacetCue for Blender"

    def draw(self, context):
        layout, scene, wm = self.layout, context.scene, context.window_manager
        row = layout.row()
        row.scale_y = 1.35
        row.operator("asm.place", icon="ADD")
        layout.prop(wm, "asm_show_overlay")
        layout.label(text="Ctrl+Alt+Shift+M 开关 · +A 放点")
        if viewport.is_xray(context.space_data):
            layout.prop(wm, "asm_expand_xray_note")
        store = api.document(scene)
        marks = list(api.marks(scene))
        pending = sum(m.status in {"OPEN", "IN_PROGRESS", "CHANGES_REQUESTED"} for m in marks)
        awaiting = sum(m.status == "MODIFIED" for m in marks)
        layout.label(text=f"{pending} 项待处理 · {awaiting} 项待审核")
        row = layout.row(align=True)
        row.operator("asm.navigate", text="上一个", icon="TRIA_LEFT").direction = -1
        row.operator("asm.navigate", text="下一个", icon="TRIA_RIGHT").direction = 1
        layout.label(text="Ctrl+Alt+Shift+← / → 跳转")
        layout.prop(wm, "asm_search", text="", icon="VIEWZOOM")
        layout.prop(wm, "asm_filter", text="")
        if store:
            layout.template_list(
                "ASM_UL_marks", "", store, "asm_marks", store, "asm_active_index", rows=4
            )
        mark = ux.active_mark(scene)
        if mark and ux.matches(mark, wm):
            box = layout.box()
            box.label(
                text=f"M{mark.number:04d} · {ux.STATUS_LABELS[mark.status]}",
                icon=ux.STATUS_ICONS[mark.status],
            )
            box.label(text=mark.target.name if mark.target else "物体已不存在", icon="OBJECT_DATA")
            chars = max(10, int(context.region.width / (13 * context.preferences.system.ui_scale)))
            lines = ux.wrap(mark.note or "（暂无注释）", chars)
            for line in lines[:6]:
                box.label(text=line)
            if len(lines) > 6:
                box.label(text="… 多行编辑可查看全文")
            row = box.row()
            row.scale_y = 1.25
            row.operator_context = "INVOKE_DEFAULT"
            row.operator("asm.edit", icon="GREASEPENCIL").marker_id = mark.marker_id
            box.operator("asm.edit_multiline", icon="WINDOW").marker_id = mark.marker_id
            row = box.row(align=True)
            row.operator("asm.focus", text="定位", icon="VIEWZOOM")
            if mark.change_summary:
                box.label(text="Agent 修改说明", icon="INFO")
                for line in ux.wrap(mark.change_summary, chars)[:5]:
                    box.label(text=line)
            row = box.row(align=True)
            if mark.status == "MODIFIED":
                row.operator("asm.review", text="通过", icon="CHECKMARK").action = "APPROVE"
                row.operator("asm.review", text="打回并编辑", icon="LOOP_BACK").action = "REJECT"
                box.label(text="Ctrl+Alt+Shift+Enter 通过")
                box.label(text="Ctrl+Alt+Shift+Backspace 打回")
            elif mark.status in {"RESOLVED", "ARCHIVED"}:
                row.operator("asm.set_status", text="重新打开", icon="LOOP_BACK").status = "OPEN"
            else:
                row.operator("asm.set_status", text="完成", icon="CHECKMARK").status = "RESOLVED"
                if mark.status == "OPEN":
                    row.operator(
                        "asm.set_status", text="进行中", icon="TIME"
                    ).status = "IN_PROGRESS"
            if mark.status != "ARCHIVED":
                row.operator("asm.set_status", text="归档", icon="PACKAGE").status = "ARCHIVED"
            row = box.row()
            row.operator_context = "INVOKE_DEFAULT"
            row.operator("asm.delete", icon="TRASH")
            box.label(text="Ctrl+Alt+Shift+X 删除 · Ctrl+Z 恢复")
            try:
                api.resolve(scene, mark, ux.GEOMETRY_CACHE)
            except (MarkError, ValueError, KeyError, TypeError) as exc:
                box.label(text="位置需要检查", icon="ERROR")
                for line in ux.wrap(ux.message(exc), chars):
                    box.label(text=line)
        elif marks:
            layout.label(text="从列表中选择匹配的标记", icon="INFO")
        else:
            layout.label(text="点击模型表面，写下修改要求", icon="INFO")
        if marks:
            layout.label(text="双击编号，或点列表铅笔编辑", icon="INFO")
            layout.operator(
                "asm.review", text="撤回最近审核（Ctrl+Alt+Shift+Z）", icon="LOOP_BACK"
            ).action = "WITHDRAW"
        if context.mode != "OBJECT":
            layout.label(text="添加标记前请切换到物体模式", icon="INFO")
        elif context.space_data.shading.type != "SOLID":
            layout.label(text="添加标记需实体显示（支持 Alt+Z）", icon="INFO")
        elif not context.space_data.overlay.show_overlays:
            layout.label(text="Blender 叠加层已关闭", icon="INFO")
        box = layout.box()
        box.label(text="Agent 可读取全部注释", icon="INFO")
        box.label(text="不受显示开关和筛选影响")
        if connection._server:
            box.label(text="Agent 连接已就绪", icon="CHECKMARK")
            box.label(text="实例：" + connection._server.instance_id)
        elif connection.LAST_ERROR:
            box.label(text="Agent 连接未启动", icon="ERROR")
            for line in ux.wrap(connection.LAST_ERROR, 28):
                box.label(text=line)
        receipt = runtime.LAST_AGENT_READ
        if receipt:
            when = (
                datetime.datetime.fromisoformat(receipt["generated_at"])
                .astimezone()
                .strftime("%H:%M:%S")
            )
            box.label(text=f"最近 MCP 查询：{when}")
            box.label(text=f"本页 {receipt['returned']} / 全部 {receipt['total']} 条")
        else:
            box.label(text="本次会话尚无 MCP 查询记录")
        for conflict in shortcuts.CONFLICTS:
            layout.label(text="快捷键冲突，已跳过：", icon="ERROR")
            for line in ux.wrap(conflict, 28):
                layout.label(text=line)


CLASSES = (
    ASM_OT_add_note,
    ASM_OT_place,
    ASM_OT_select,
    ASM_OT_edit,
    ASM_OT_focus,
    ASM_OT_toggle_marks,
    ASM_OT_navigate,
    ASM_OT_review,
    ASM_OT_status,
    ASM_OT_delete,
    ASM_UL_marks,
    ASM_PT_panel,
    *editor.CLASSES,
)


def register():
    global _handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    ux.register()
    bpy.types.TEXT_HT_header.append(editor.draw_header)
    if not bpy.app.background:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
        config = bpy.context.window_manager.keyconfigs.addon
        if config:
            view_map = config.keymaps.new(name="3D View", space_type="VIEW_3D")
            _keymaps.append(
                (view_map, view_map.keymap_items.new("asm.select", "LEFTMOUSE", "PRESS", head=True))
            )
            _keymaps.append(
                (
                    view_map,
                    view_map.keymap_items.new("asm.select", "LEFTMOUSE", "DOUBLE_CLICK", head=True),
                )
            )
        shortcuts.register(_keymaps)
    api.redraw()


def unregister():
    global _handle, _shader, _last_click
    from . import floating

    floating.shutdown()
    _last_click = None
    for placement in list(_active_placements.values()):
        try:
            placement.cleanup(bpy.context)
        except ReferenceError:
            pass
    _active_placements.clear()
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _shader = None
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    bpy.types.TEXT_HT_header.remove(editor.draw_header)
    # Drafts are retained as Text datablocks on disable.
    _pending.clear()
    ux.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    api.redraw()
