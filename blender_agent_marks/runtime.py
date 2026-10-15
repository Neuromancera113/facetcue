import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .core import MAX_NOTE_LENGTH, STATUSES

LAST_AGENT_READ = None


def redraw_views(self=None, context=None):
    from .api import redraw

    redraw()


def record_agent_read(response):
    """Transient receipt: a successful MCP snapshot was generated, not user approval."""
    global LAST_AGENT_READ
    if response.get("ok"):
        LAST_AGENT_READ = {key: response[key] for key in ("generated_at", "returned", "total")}
        redraw_views()


class ASM_Mark(bpy.types.PropertyGroup):
    marker_id: StringProperty()
    number: IntProperty(min=1)
    target: PointerProperty(type=bpy.types.Object)
    mesh: PointerProperty(type=bpy.types.Mesh)
    target_name_at_creation: StringProperty()
    anchor_json: StringProperty()
    note: StringProperty(maxlen=MAX_NOTE_LENGTH)
    status: EnumProperty(items=[(s, s.replace("_", " ").title(), "") for s in STATUSES])
    color: FloatVectorProperty(size=4, subtype="COLOR", min=0, max=1)
    revision: IntProperty(default=1, min=1)
    created_at: StringProperty()
    updated_at: StringProperty()
    change_summary: StringProperty(maxlen=MAX_NOTE_LENGTH)


def register():
    bpy.utils.register_class(ASM_Mark)
    # Keep annotation payload off exportable Scene/Object/Mesh custom properties.
    # The Text owns the scene reference, so even glTF extras cannot walk from
    # exported scene properties into the notes.
    bpy.types.Text.asm_scene = PointerProperty(type=bpy.types.Scene)
    bpy.types.Text.asm_marks = CollectionProperty(type=ASM_Mark)
    bpy.types.Text.asm_next_number = IntProperty(default=1, min=1)
    bpy.types.Text.asm_active_index = IntProperty(default=0, min=0, update=redraw_views)
    bpy.types.Text.asm_review_history = StringProperty(default="[]")
    # View-only setting: does not gate the agent data API.
    bpy.types.WindowManager.asm_show_overlay = BoolProperty(
        name="显示表面标记", default=True, update=redraw_views
    )
    bpy.types.WindowManager.asm_search = StringProperty(
        name="搜索", options={"SKIP_SAVE"}, update=redraw_views
    )
    bpy.types.WindowManager.asm_expand_xray_note = BoolProperty(
        name="展开 X-Ray 注释", default=False, options={"SKIP_SAVE"}, update=redraw_views
    )
    bpy.types.WindowManager.asm_note_draft = PointerProperty(
        type=bpy.types.Text, options={"SKIP_SAVE"}
    )
    bpy.types.WindowManager.asm_note_input = StringProperty(
        name="注释",
        maxlen=MAX_NOTE_LENGTH,
        options={"SKIP_SAVE", "TEXTEDIT_UPDATE"},
    )
    bpy.types.WindowManager.asm_filter = EnumProperty(
        name="状态",
        default="ALL",
        items=[
            ("ALL", "全部", ""),
            ("PENDING", "待处理", "未完成与进行中"),
            ("RESOLVED", "已完成", ""),
            ("ARCHIVED", "已归档", ""),
            ("MODIFIED", "待审核", "Agent 已修改，等待用户审核"),
            ("CHANGES_REQUESTED", "已打回", "等待 Agent 按新注释修改"),
        ],
        update=redraw_views,
    )


def unregister():
    from . import compact

    compact.unregister()
    global LAST_AGENT_READ
    LAST_AGENT_READ = None
    for name in (
        "asm_scene",
        "asm_marks",
        "asm_next_number",
        "asm_active_index",
        "asm_review_history",
    ):
        delattr(bpy.types.Text, name)
    for name in (
        "asm_show_overlay",
        "asm_search",
        "asm_filter",
        "asm_expand_xray_note",
        "asm_note_draft",
        "asm_note_input",
    ):
        delattr(bpy.types.WindowManager, name)
    bpy.utils.unregister_class(ASM_Mark)
