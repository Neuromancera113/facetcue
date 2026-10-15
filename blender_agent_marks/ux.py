"""Shared presentation helpers; none of these filters restrict the agent API."""

import bpy
from bpy.app.handlers import persistent

from .core import MAX_NOTE_LENGTH

STATUS_LABELS = {
    "OPEN": "待处理",
    "IN_PROGRESS": "进行中",
    "RESOLVED": "已通过",
    "ARCHIVED": "已归档",
    "MODIFIED": "已修改 · 待审核",
    "CHANGES_REQUESTED": "已打回",
}
STATUS_ICONS = {
    "OPEN": "RADIOBUT_OFF",
    "IN_PROGRESS": "TIME",
    "RESOLVED": "CHECKMARK",
    "ARCHIVED": "PACKAGE",
    "MODIFIED": "FILE_TICK",
    "CHANGES_REQUESTED": "LOOP_BACK",
}
GEOMETRY_CACHE = {}


def matches(mark, wm):
    query = wm.asm_search.strip().casefold()
    haystack = f"M{mark.number:04d} {mark.note} {mark.target.name if mark.target else mark.target_name_at_creation}"
    if query and query not in haystack.casefold():
        return False
    status = wm.asm_filter
    return (
        status == "ALL"
        or status == mark.status
        or status == "PENDING"
        and mark.status in {"OPEN", "IN_PROGRESS", "CHANGES_REQUESTED"}
    )


def active_mark(scene):
    from .api import document

    store = document(scene)
    if not store or not store.asm_marks:
        return None
    return store.asm_marks[min(store.asm_active_index, len(store.asm_marks) - 1)]


def message(exc):
    if getattr(exc, "code", "") == "UNSUPPORTED_VIEW":
        return {
            "requires_solid_view": "请切换到实体显示后放置标记（支持 Alt+Z）",
            "quad_view_not_supported": "暂不支持四分视图，请切换到单视图后添加",
            "custom_clip_planes_not_supported": "请先关闭视图裁剪区域（Alt+B）再添加标记",
        }.get(str(exc), "当前视图暂不支持：" + str(exc))
    if getattr(exc, "code", "") == "NON_MESH_TARGET":
        return f"点中了曲线或文字「{exc}」；请点击需要修改的网格表面"
    if getattr(exc, "code", "") == "INSTANCE_TARGET":
        return f"点中了实例「{exc}」；暂只能在原始网格表面附着标记"
    if getattr(exc, "code", "") == "UNSUPPORTED_TARGET":
        reason, _, name = str(exc).partition("|")
        hint = {
            "in_front_geometry": "开启了在前面显示",
            "wire_or_bounds_geometry": "使用线框或包围盒显示",
            "non_surface_geometry": "没有可用的网格表面",
        }.get(reason, "使用暂不支持的显示方式")
        return f"射线经过「{name}」，该物体{hint}"
    return {
        "NO_SURFACE": "未点中表面，请继续点击模型；Esc 取消",
        "OUTSIDE_VIEW": "请点击 3D 视口内的模型表面",
        "EDIT_MODE": "请先切换到物体模式",
        "UNSUPPORTED_GEOMETRY": "此物体有修改器或形态键，暂不支持在其表面添加标记",
        "REVISION_CONFLICT": "注释已被其他操作修改，请重新读取并合并",
        "STALE_TOPOLOGY": "模型拓扑已改变，原标记需要重新附着",
        "MESH_REPLACED": "物体网格已更换，原标记需要重新附着",
        "ORPHANED": "标记所附着的物体已不存在",
        "OBJECT_HIDDEN": "请先在视图中显示此物体，再定位标记",
        "NO_VIEWPORT": "请先打开 3D 视口",
        "INVALID_NOTE": f"注释最多支持 {MAX_NOTE_LENGTH} 个字符",
        "CORRUPT_ANNOTATION": "标记位置数据损坏；注释仍可读取和编辑",
        "INVALID_GEOMETRY": "物体包含无效坐标，请检查网格和变换",
        "AMBIGUOUS_DOCUMENT": "标记或注册表身份重复，请先检查数据；未覆盖原词条",
        "NOT_FOUND": "标记已不存在",
        "SCENE_CHANGED": "当前场景已切换，请重新选择要删除的标记",
        "INVALID_REVIEW_STATE": "请先选择带蓝色状态角标的待审核标记",
        "NO_REVIEW_HISTORY": "没有可撤回的审核操作",
        "CORRUPT_REVIEW_HISTORY": "审核记录损坏，未修改当前词条",
        "EDITOR_WINDOW_FAILED": "无法打开小型注释框：" + str(exc),
    }.get(getattr(exc, "code", ""), str(exc))


def wrap(value, width, measure=len):
    """Wrap CJK and Latin text without dropping explicit line breaks."""
    lines = []
    for paragraph in value.expandtabs(4).split("\n"):
        line = ""
        for char in paragraph:
            if line and measure(line + char) > width:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


@persistent
def invalidate(*args):
    from . import spatial

    GEOMETRY_CACHE.clear()
    depsgraph = next((arg for arg in args if isinstance(arg, bpy.types.Depsgraph)), None)
    spatial.invalidate(depsgraph)


@persistent
def on_load(*args):
    from . import compact, runtime, ui

    compact.close()
    runtime.LAST_AGENT_READ = None
    ui._pending.clear()
    ui._active_placements.clear()
    ui._last_click = None
    invalidate()


def register():
    for handlers, callback in (
        (bpy.app.handlers.depsgraph_update_post, invalidate),
        (bpy.app.handlers.undo_post, invalidate),
        (bpy.app.handlers.redo_post, invalidate),
        (bpy.app.handlers.load_post, on_load),
    ):
        if callback not in handlers:
            handlers.append(callback)


def unregister():
    for handlers, callback in (
        (bpy.app.handlers.depsgraph_update_post, invalidate),
        (bpy.app.handlers.undo_post, invalidate),
        (bpy.app.handlers.redo_post, invalidate),
        (bpy.app.handlers.load_post, on_load),
    ):
        if callback in handlers:
            handlers.remove(callback)
    invalidate()
