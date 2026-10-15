"""Native compact input and multiline drafts. Never execute annotation content."""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import api, compact
from .core import MAX_NOTE_LENGTH, MarkError
from .ux import active_mark, message

DRAFT_KEY = "agent_marks_note_draft_v1"


def find_draft(marker_id):
    for text in bpy.data.texts:
        if DRAFT_KEY in text:
            try:
                if json.loads(text[DRAFT_KEY])["id"] == marker_id:
                    return text
            except (ValueError, KeyError, TypeError):
                continue
    return None


def create_draft(mark, note=None, revision=None, action="EDIT"):
    text = bpy.data.texts.new(f"注释草稿 M{mark.number:04d}")
    text.use_fake_user = True
    text.use_module = False
    text[DRAFT_KEY] = json.dumps(
        {
            "id": mark.marker_id,
            "revision": mark.revision if revision is None else revision,
            "label": f"M{mark.number:04d}",
            "action": action,
        }
    )
    text.write(mark.note if note is None else note)
    return text


def open_draft(context, text, *, expanded=False):
    from .floating import open_window

    try:
        if not expanded:
            return bpy.ops.asm.note_dialog("INVOKE_DEFAULT", text_name=text.name)
        return open_window(context, text)
    except (RuntimeError, OSError) as exc:
        raise MarkError("EDITOR_WINDOW_FAILED", str(exc)) from exc


def open_pending(context, token, *, expanded=False):
    from .ui import _pending

    pending = _pending[token]
    text = bpy.data.texts.new("新建表面注释")
    text.use_fake_user = True
    text.use_module = False
    # Creation drafts survive Undo/file reload without relying on Python caches.
    text["asm_pending_scene"] = pending["scene"]
    text["asm_pending_target"] = pending["target"]
    text["asm_pending_mesh"] = pending["mesh"]
    text[DRAFT_KEY] = json.dumps(
        {
            "action": "CREATE",
            "token": token,
            "label": "新建注释",
            "surface": {key: pending[key] for key in ("index", "point", "fingerprint", "vertices")},
        }
    )
    open_draft(context, text, expanded=expanded)


def draft_info(context):
    if context.area and context.area.type == "TEXT_EDITOR":
        text = context.space_data.text
        if text and DRAFT_KEY in text:
            try:
                return text, json.loads(text[DRAFT_KEY])
            except (ValueError, TypeError):
                pass
    return None, None


def target(info):
    matches = [
        (scene, mark)
        for scene in bpy.data.scenes
        for mark in api.marks(scene)
        if mark.marker_id == info["id"]
    ]
    if len(matches) > 1:
        raise MarkError("AMBIGUOUS_DOCUMENT", "Multiple annotations share the draft target ID")
    if matches:
        return matches[0]
    raise MarkError("NOT_FOUND", "Draft target no longer exists")


def finish(context, text):
    from .floating import close_window

    close_window(context.window)
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "TEXT_EDITOR" and space.text == text:
                    space.text = None
    bpy.data.texts.remove(text)
    api.redraw()


def apply_draft(context, text):
    info = json.loads(text[DRAFT_KEY])
    action = info.get("action", "EDIT")
    if action == "CREATE":
        from .ui import _pending, commit_pending

        if info["token"] not in _pending and "surface" in info:
            _pending[info["token"]] = {
                **info["surface"],
                "scene": text.get("asm_pending_scene"),
                "target": text.get("asm_pending_target"),
                "mesh": text.get("asm_pending_mesh"),
            }
        commit_pending(context.scene, info["token"], text.as_string())
    else:
        scene, mark = target(info)
        if action == "REJECT":
            from .review import decide

            decide(scene, mark.marker_id, info["revision"], "REJECT", text.as_string())
        else:
            api.update(scene, mark.marker_id, info["revision"], note=text.as_string())
    finish(context, text)


def cancel_draft(context, text):
    info = json.loads(text[DRAFT_KEY])
    if info.get("action") == "CREATE":
        from .ui import _pending

        _pending.pop(info.get("token"), None)
    finish(context, text)


def discard_compact_draft(context):
    manager = context.window_manager
    text = manager.asm_note_draft
    manager.asm_note_draft = None
    compact.close()
    if text and DRAFT_KEY in text:
        cancel_draft(context, text)


class ASM_OT_note_dialog(bpy.types.Operator):
    bl_idname = "asm.note_dialog"
    bl_label = "保存注释"
    bl_description = "Enter 保存注释并关闭紧凑弹窗"
    bl_options = {"UNDO"}

    text_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    note: StringProperty(maxlen=MAX_NOTE_LENGTH, options={"SKIP_SAVE"})
    use_input: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        text = bpy.data.texts.get(self.text_name)
        if text is None or DRAFT_KEY not in text:
            return {"CANCELLED"}
        manager = context.window_manager
        previous = manager.asm_note_draft
        manager.asm_note_draft = None
        if previous and previous != text and DRAFT_KEY in previous:
            cancel_draft(context, previous)
        manager.asm_note_input = text.as_string()
        manager.asm_note_draft = text
        compact.SESSION = compact.Session(context, self)
        self.session = compact.SESSION
        self.use_input = "\n" not in text.as_string()
        self.note = text.as_string()
        self.session.show()
        return {"RUNNING_MODAL"}

    def draw(self, context):
        ASM_PT_compact_note.draw(self, context)

    def cancel(self, context):
        text = getattr(context.window_manager, "asm_note_draft", None)
        if text and text.name == self.text_name:
            discard_compact_draft(context)

    def execute(self, context):
        text = bpy.data.texts.get(self.text_name)
        if text is None or DRAFT_KEY not in text:
            return {"CANCELLED"}
        if self.use_input:
            self.note = context.window_manager.asm_note_input
        context.window_manager.asm_note_draft = None
        compact.close()
        text.clear()
        text.write(self.note)
        try:
            apply_draft(context, text)
        except MarkError as exc:
            self.report({"WARNING"}, message(exc) + "；草稿已保留")
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_expand_draft(bpy.types.Operator):
    bl_idname = "asm.expand_draft"
    bl_label = "展开多行编辑"
    bl_description = "在独立的 Blender 文本窗口中编辑完整注释"
    text_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        text = bpy.data.texts.get(self.text_name)
        if text is None or DRAFT_KEY not in text:
            return {"CANCELLED"}
        context.window_manager.asm_note_draft = None
        compact.close()
        try:
            open_draft(context, text, expanded=True)
        except MarkError as exc:
            self.report({"WARNING"}, message(exc) + "；草稿已保留")
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_PT_compact_note(bpy.types.Panel):
    bl_label = "编辑表面注释"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_ui_units_x = 24

    def draw(self, context):
        manager = context.window_manager
        text = manager.asm_note_draft
        if text is None or DRAFT_KEY not in text:
            return
        if compact.SESSION and context.region_popup:
            compact.SESSION.popup_region = context.region_popup
            r = context.region_popup
            compact.SESSION.bounds = (r.x, r.y, r.width, r.height)
        layout = self.layout
        layout.operator_context = "EXEC_DEFAULT"
        layout.label(text=json.loads(text[DRAFT_KEY])["label"])
        if "\n" in text.as_string():
            for line in text.as_string().splitlines()[:3]:
                layout.label(text=line[:65] or " ")
            layout.label(text="已有多行内容；展开后可编辑全文")
            layout.operator("asm.expand_draft", icon="WINDOW").text_name = text.name
        else:
            row = layout.row()
            row.activate_init = True
            row.prop(manager, "asm_note_input", text="")
            layout.label(text="Enter 保存 · Esc 取消")
            layout.label(text="长文：保存后在侧栏选择「多行编辑」")


class ASM_OT_edit_multiline(bpy.types.Operator):
    bl_idname = "asm.edit_multiline"
    bl_label = "多行编辑"
    bl_description = "自动进入注释输入：Enter 保存退出，Shift+Enter 换行，Esc 取消"
    marker_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    compact: BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})
    action: EnumProperty(
        items=[("EDIT", "编辑", ""), ("REJECT", "打回", "")], default="EDIT", options={"SKIP_SAVE"}
    )

    def execute(self, context):
        discard_compact_draft(context)
        try:
            mark = (
                api.get_mark(context.scene, self.marker_id)
                if self.marker_id
                else active_mark(context.scene)
            )
        except MarkError as exc:
            self.report({"WARNING"}, message(exc))
            return {"CANCELLED"}
        if not mark:
            return {"CANCELLED"}
        if self.action == "REJECT" and mark.status != "MODIFIED":
            self.report({"WARNING"}, message(MarkError("INVALID_REVIEW_STATE", "")))
            return {"CANCELLED"}
        if not context.area:
            self.report({"WARNING"}, "请从 Blender 编辑区域打开词条")
            return {"CANCELLED"}
        text = find_draft(mark.marker_id)
        if text is None:
            text = create_draft(mark, action=self.action)
        elif (
            self.action == "REJECT"
            and json.loads(text[DRAFT_KEY]).get("action", "EDIT") != "REJECT"
        ):
            self.report({"WARNING"}, "此标记有未完成的编辑草稿，请先保存或放弃草稿，再打回")
            return {"CANCELLED"}
        try:
            open_draft(context, text, expanded=not self.compact)
        except MarkError as exc:
            self.report({"WARNING"}, message(exc) + "；草稿已保留")
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_apply_draft(bpy.types.Operator):
    bl_idname = "asm.apply_draft"
    bl_label = "保存注释并返回"
    bl_description = "Enter 确认注释并返回模型；Shift+Enter 换行"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return draft_info(context)[0] is not None

    def execute(self, context):
        text, _ = draft_info(context)
        try:
            apply_draft(context, text)
        except MarkError as exc:
            self.report({"WARNING"}, message(exc) + "；当前草稿已保留")
            return {"CANCELLED"}
        return {"FINISHED"}


class ASM_OT_cancel_draft(bpy.types.Operator):
    bl_idname = "asm.cancel_draft"
    bl_label = "放弃草稿并返回"
    bl_description = "放弃尚未保存的草稿修改，保留标记原文；可撤销"
    bl_options = {"UNDO"}

    @classmethod
    def poll(cls, context):
        return draft_info(context)[0] is not None

    def execute(self, context):
        text, _ = draft_info(context)
        cancel_draft(context, text)
        return {"FINISHED"}


class ASM_OT_draft_newline(bpy.types.Operator):
    bl_idname = "asm.draft_newline"
    bl_label = "注释换行"

    @classmethod
    def poll(cls, context):
        return draft_info(context)[0] is not None

    def execute(self, context):
        return bpy.ops.text.line_break()


class ASM_PT_draft(bpy.types.Panel):
    bl_label = "编辑表面注释"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "FacetCue for Blender"

    @classmethod
    def poll(cls, context):
        return draft_info(context)[0] is not None

    def draw(self, context):
        text, info = draft_info(context)
        layout = self.layout
        layout.label(text=info["label"])
        layout.label(text=f"{len(text.as_string())} / {MAX_NOTE_LENGTH} 字符")
        layout.label(text="保存后 Agent", icon="INFO")
        layout.label(text="才会读取新内容")
        layout.operator("asm.apply_draft", text="保存并返回", icon="CHECKMARK")
        layout.label(text="Enter 保存 · Shift+Enter 换行")
        if info.get("action") == "REJECT":
            layout.label(text="保存时打回；取消保留待审核状态", icon="INFO")
        layout.operator("asm.cancel_draft", text="放弃并返回", icon="LOOP_BACK")


def draw_header(self, context):
    _, info = draft_info(context)
    if info:
        row = self.layout.row(align=True)
        row.label(text=info["label"])
        row.label(text="Enter 确认 · Shift+Enter 换行 · Esc 取消")
        row.operator("asm.apply_draft", text="保存注释", icon="CHECKMARK")
        row.operator("asm.cancel_draft", text="放弃草稿", icon="LOOP_BACK")


CLASSES = (
    compact.ASM_OT_note_events,
    ASM_OT_note_dialog,
    ASM_OT_expand_draft,
    ASM_PT_compact_note,
    ASM_OT_edit_multiline,
    ASM_OT_apply_draft,
    ASM_OT_cancel_draft,
    ASM_OT_draft_newline,
    ASM_PT_draft,
)
