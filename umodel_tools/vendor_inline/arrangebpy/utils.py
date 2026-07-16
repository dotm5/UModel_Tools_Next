# SPDX-License-Identifier: GPL-2.0-or-later

from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable
from functools import cache
from operator import itemgetter
from typing import TypeVar

import bpy
from bpy.types import Node, NodeTree
from mathutils import Vector


_T1 = TypeVar("_T1", bound=Hashable)
_T2 = TypeVar("_T2", bound=Hashable)


def group_by(
    iterable: Iterable[_T1],
    key: Callable[[_T1], _T2],
    sort: bool = False,
) -> dict[tuple[_T1, ...], _T2]:
    groups = defaultdict(list)
    for item in iterable:
        groups[key(item)].append(item)

    items = sorted(groups.items(), key=itemgetter(0)) if sort else groups.items()
    return {tuple(group): key for key, group in items}


def abs_loc(node: Node) -> Vector:
    loc = node.location.copy()

    parent = node
    while parent := parent.parent:
        loc += parent.location

    return loc


REROUTE_DIM = Vector((8, 8))


def dimensions(node: Node) -> Vector:
    """Get node dimensions, accounting for reroutes and optionally UI scale."""
    if node.bl_idname != "NodeReroute":
        measured = None
        try:
            if bpy.context and hasattr(bpy.context, "preferences"):
                ui_scale = bpy.context.preferences.system.ui_scale
                if ui_scale > 0:
                    measured = node.dimensions / ui_scale
        except (AttributeError, RuntimeError, ZeroDivisionError):
            pass

        if measured is None:
            measured = node.dimensions
        if measured.x > 0 and measured.y > 0:
            return measured

        # Blender does not populate Node.dimensions for node trees created in
        # background mode. Estimate a conservative box so the layout remains
        # useful when UModel Tools builds material libraries without a UI.
        visible_sockets = sum(
            1
            for socket in (*node.inputs, *node.outputs)
            if socket.enabled and not socket.hide
        )
        estimated_height = 40.0 + visible_sockets * 22.0
        if node.bl_idname == "ShaderNodeTexImage":
            estimated_height = max(estimated_height, 260.0)
        return Vector((
            max(float(node.width), 100.0),
            max(float(node.height), estimated_height),
        ))
    else:
        return REROUTE_DIM


_HIDE_OFFSET = 10


def get_top(node: Node, y_loc: float | None = None) -> float:
    if y_loc is None:
        y_loc = abs_loc(node).y

    return (y_loc + dimensions(node).y / 2) - _HIDE_OFFSET if node.hide else y_loc


def get_bottom(node: Node, y_loc: float | None = None) -> float:
    if y_loc is None:
        y_loc = abs_loc(node).y

    dim_y = dimensions(node).y
    bottom = y_loc - dim_y
    return bottom + dim_y / 2 - _HIDE_OFFSET if node.hide else bottom


@cache
def frame_padding() -> float:
    """Get frame padding, with fallback for headless mode."""
    try:
        if bpy.context and hasattr(bpy.context, "preferences"):
            prefs = bpy.context.preferences.system
            if prefs.ui_scale > 0:
                widget_unit = int(18 * prefs.ui_scale) + (2 * prefs.pixel_size)
                return 1.5 * widget_unit / prefs.ui_scale
    except (AttributeError, RuntimeError, ZeroDivisionError):
        pass
    # Use fixed padding for headless usage
    return 27.0  # 1.5 * 18 (default widget unit)


def get_ntree() -> NodeTree | None:
    """
    Get the currently active node tree from context.

    Returns None if no context is available (e.g., in headless mode).
    This function is provided for compatibility with the original add-on,
    but passing the node tree as a parameter is preferred.
    """
    try:
        if bpy.context and hasattr(bpy.context, "space_data"):
            return bpy.context.space_data.edit_tree  # type: ignore
    except (AttributeError, RuntimeError):
        pass
    return None
