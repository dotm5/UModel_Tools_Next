"""Automatic layout for generated material node trees."""

from __future__ import annotations

import bpy


_WARNED_FAILURES: set[str] = set()


def _link_signature(node_tree: bpy.types.NodeTree) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(sorted(
        (
            link.from_node.name,
            link.from_socket.identifier,
            link.to_node.name,
            link.to_socket.identifier,
        )
        for link in node_tree.links
    ))


def _warn_once(message: str) -> None:
    if message in _WARNED_FAILURES:
        return
    _WARNED_FAILURES.add(message)
    print(f"Warning: automatic material-node layout skipped: {message}")


def arrange_material_node_tree(node_tree: bpy.types.NodeTree) -> bool:
    """Arrange a completed material node tree without changing its graph."""
    original_nodes = tuple(node_tree.nodes)
    if len(original_nodes) < 2:
        return False

    original_node_set = set(original_nodes)
    original_links = _link_signature(node_tree)
    original_state = {
        node: (tuple(node.location), node.parent)
        for node in original_nodes
    }

    try:
        # Imported lazily so a source checkout without built third-party
        # dependencies still imports materials, albeit without auto-layout.
        from .vendor_inline.arrangebpy import LayoutSettings, layout  # pylint: disable=import-outside-toplevel

        layout(
            node_tree,
            algorithm="sugiyama",
            settings=LayoutSettings(
                horizontal_spacing=80.0,
                vertical_spacing=40.0,
                direction="BALANCED",
                socket_alignment="NONE",
                add_reroutes=False,
                stack_collapsed=False,
            ),
        )

        if set(node_tree.nodes) != original_node_set:
            raise RuntimeError("layout changed the node set")
        if _link_signature(node_tree) != original_links:
            raise RuntimeError("layout changed material links")
        if any(node.parent is not parent for node, (_, parent) in original_state.items()):
            raise RuntimeError("layout changed node parent relationships")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Layout is cosmetic and must not block material imports.
        for node, (location, parent) in original_state.items():
            if node in node_tree.nodes[:]:
                node.parent = parent
                node.location = location
        _warn_once(f"{type(exc).__name__}: {exc}")
        return False

    return True
