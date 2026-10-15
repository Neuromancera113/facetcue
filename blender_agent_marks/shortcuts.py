"""Scoped shortcut defaults with conservative Blender keymap conflict checks."""

import bpy

PREFIX = "Ctrl+Alt+Shift"
CONFLICTS = []
VIEW_BINDINGS = (
    ("asm.toggle_marks", "M", {}, "开关标记"),
    ("asm.place", "A", {}, "放置标记"),
    ("asm.delete", "X", {}, "删除当前标记"),
    ("asm.navigate", "LEFT_ARROW", {"direction": -1}, "上一个标记"),
    ("asm.navigate", "RIGHT_ARROW", {"direction": 1}, "下一个标记"),
    ("asm.review", "RET", {"action": "APPROVE"}, "通过"),
    ("asm.review", "BACK_SPACE", {"action": "REJECT"}, "打回并编辑"),
    ("asm.review", "Z", {"action": "WITHDRAW"}, "撤回审核"),
)


def conflicts(manager, event_type):
    found = set()
    for config in manager.keyconfigs:
        for keymap in config.keymaps:
            if keymap.is_modal or keymap.name not in {
                "Window",
                "Screen",
                "3D View",
                "3D View Generic",
                "Object Mode",
            }:
                continue
            for item in keymap.keymap_items:
                if not item.active or item.idname.startswith("asm."):
                    continue
                if (
                    item.type != event_type
                    or item.value not in {"PRESS", "ANY"}
                    or item.key_modifier != "NONE"
                ):
                    continue
                if item.any or (
                    all(getattr(item, key) in (-1, 1) for key in ("ctrl", "alt", "shift"))
                    and item.oskey in (-1, 0)
                ):
                    found.add(f"{keymap.name}: {item.idname}")
    return sorted(found)


def register(registered):
    CONFLICTS.clear()
    manager = bpy.context.window_manager
    config = manager.keyconfigs.addon
    if not config:
        return
    view_map = config.keymaps.new(name="3D View", space_type="VIEW_3D")
    for operator, key, properties, label in VIEW_BINDINGS:
        occupied = conflicts(manager, key)
        if occupied:
            CONFLICTS.append(f"{PREFIX}+{key}（{label}）：" + ", ".join(occupied))
            continue
        item = view_map.keymap_items.new(operator, key, "PRESS", ctrl=True, alt=True, shift=True)
        for name, value in properties.items():
            setattr(item.properties, name, value)
        registered.append((view_map, item))
    text_map = config.keymaps.new(name="Text", space_type="TEXT_EDITOR")
    # Polls only succeed for our annotation drafts. Ordinary Text datablocks
    # retain Blender's Enter/newline and Esc behavior.
    for operator, key, modifiers in (
        ("asm.apply_draft", "RET", {}),
        ("asm.apply_draft", "NUMPAD_ENTER", {}),
        ("asm.apply_draft", "RET", {"ctrl": True}),
        ("asm.draft_newline", "RET", {"shift": True}),
        ("asm.draft_newline", "NUMPAD_ENTER", {"shift": True}),
        ("asm.cancel_draft", "ESC", {}),
    ):
        registered.append(
            (text_map, text_map.keymap_items.new(operator, key, "PRESS", head=True, **modifiers))
        )
