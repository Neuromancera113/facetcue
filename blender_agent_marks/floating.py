"""Blender-managed text windows; no platform-specific window manipulation."""

import bpy

_windows = set()


def current_window():
    live = {window.as_pointer(): window for window in bpy.context.window_manager.windows}
    _windows.intersection_update(live)
    return next((live[pointer] for pointer in _windows), None)


def is_editor(window):
    return bool(window and window.as_pointer() in _windows)


def open_window(context, text):
    previous = current_window()
    window = previous
    if window is None or window != context.window:
        before = {item.as_pointer() for item in context.window_manager.windows}
        region = next(r for r in context.area.regions if r.type == "WINDOW")
        with context.temp_override(region=region):
            bpy.ops.screen.area_dupli("INVOKE_DEFAULT")
        window = next(
            (item for item in context.window_manager.windows if item.as_pointer() not in before),
            None,
        )
        if window is None:
            raise RuntimeError("Blender could not open an annotation editor window")
        _windows.add(window.as_pointer())
        # A new Blender-managed window gets native focus without an OS backend.
        if previous is not None:
            close_window(previous)
    area = window.screen.areas[0]
    area.type = "TEXT_EDITOR"
    area.show_menus = False
    space = area.spaces.active
    space.text = text
    space.use_live_edit = False
    space.show_syntax_highlight = False
    space.show_word_wrap = True
    space.show_line_numbers = False
    space.show_region_ui = False
    if hasattr(space, "show_region_footer"):
        space.show_region_footer = False
    space.top = 0
    text.cursor_set(0, character=0)
    area.header_text_set("Enter 保存关闭 · Shift+Enter 换行 · Esc 放弃")

    def focus_text():
        try:
            if window.as_pointer() not in _windows:
                return None
            region = next(r for r in area.regions if r.type == "WINDOW")
            window.cursor_warp(region.x + min(70, region.width // 2), region.y + region.height // 2)
            area.tag_redraw()
        except ReferenceError:
            pass
        return None

    bpy.app.timers.register(focus_text, first_interval=0.05)
    return window


def close_window(window):
    if not is_editor(window):
        return False
    _windows.discard(window.as_pointer())

    # Defer closure until the annotation operator finishes its Undo transaction.
    def close():
        if window in bpy.context.window_manager.windows[:]:
            with bpy.context.temp_override(window=window):
                bpy.ops.wm.window_close()
        return None

    bpy.app.timers.register(close, first_interval=0.01)
    return True


def shutdown():
    for window in list(bpy.context.window_manager.windows):
        close_window(window)
    _windows.clear()
