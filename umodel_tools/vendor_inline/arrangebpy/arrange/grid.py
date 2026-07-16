# SPDX-License-Identifier: GPL-2.0-or-later

"""
Grid Layout

Arranges nodes in a regular grid pattern, optionally grouping by type or cluster.

Good for:
- Organizing collections of similar nodes
- Creating inventory-style layouts
- Simple, predictable node arrangement
- Documentation or reference sheets
"""

from __future__ import annotations

import math
from statistics import fmean

from bpy.types import NodeTree
from mathutils import Vector

from ..settings import GridSettings
from ..utils import abs_loc, dimensions


def grid_layout(ntree: NodeTree, settings: GridSettings = GridSettings()) -> None:
    """
    Apply grid-based layout to nodes.

    This algorithm:
    1. Optionally groups nodes by type or cluster
    2. Arranges nodes in a regular grid
    3. Places nodes in cells, optionally centering them

    Args:
        ntree: The Blender node tree to layout
        settings: Layout settings controlling grid structure

    Examples:
        # Simple grid with auto-calculated columns
        grid_layout(ntree)

        # Fixed 5-column grid
        grid_layout(ntree, GridSettings(columns=5))

        # Group by node type
        grid_layout(ntree, GridSettings(
            grouping="TYPE",
            cell_width=250.0
        ))

        # Compact vertical layout
        grid_layout(ntree, GridSettings(
            direction="VERTICAL",
            compact=True,
            columns=3
        ))

        # Group by frame membership
        grid_layout(ntree, GridSettings(
            grouping="CLUSTER",
            center_in_cells=True
        ))
    """
    # Get layout nodes and preserve center
    layout_nodes = [node for node in ntree.nodes if node.bl_idname != "NodeFrame"]
    if not layout_nodes:
        return

    locations = [abs_loc(node) for node in layout_nodes]
    old_center = Vector(map(fmean, zip(*locations)))

    # Group nodes if requested
    if settings.grouping == "TYPE":
        node_groups = _group_by_type(layout_nodes)
    elif settings.grouping == "CLUSTER":
        node_groups = _group_by_cluster(layout_nodes)
    else:
        node_groups = [layout_nodes]

    # Calculate cell sizes if compact mode
    if settings.compact:
        cell_width, cell_height = _calculate_cell_sizes(layout_nodes)
    else:
        cell_width = settings.cell_width
        cell_height = settings.cell_height

    # Place each group
    current_offset = 0
    all_positions = []

    for group in node_groups:
        if not group:
            continue

        # Calculate grid dimensions for this group
        num_nodes = len(group)
        if settings.columns is not None:
            cols = settings.columns
        else:
            # Auto-calculate: roughly square grid
            cols = max(1, int(math.ceil(math.sqrt(num_nodes))))

        rows = math.ceil(num_nodes / cols)

        # Place nodes in grid
        for idx, node in enumerate(group):
            if settings.direction == "HORIZONTAL":
                # Fill left-to-right, then top-to-bottom
                col = idx % cols
                row = idx // cols
            else:  # VERTICAL
                # Fill top-to-bottom, then left-to-right
                col = idx // rows
                row = idx % rows

            # Calculate cell position
            x = col * cell_width
            y = -row * cell_height  # Negative because Blender Y is up

            # Center node in cell if requested
            if settings.center_in_cells:
                node_w, node_h = dimensions(node)
                x += (cell_width - node_w) / 2
                y -= (cell_height - node_h) / 2

            # Apply group offset (for multiple groups)
            if settings.direction == "HORIZONTAL":
                y -= current_offset
            else:
                x += current_offset

            all_positions.append((node, x, y))

        # Update offset for next group
        if settings.direction == "HORIZONTAL":
            current_offset += (
                rows * cell_height + cell_height
            )  # Extra gap between groups
        else:
            current_offset += cols * cell_width + cell_width

    # Compute new center
    new_center = Vector(map(fmean, zip(*[(x, y) for _, x, y in all_positions])))

    # Apply positions with offset to preserve center
    offset = old_center - new_center

    for node, x, y in all_positions:
        node.location.x = x + offset.x
        node.location.y = y + offset.y


def _group_by_type(nodes: list) -> list[list]:
    """
    Group nodes by their type (bl_idname).

    Returns a list of node lists, one per type.
    """
    type_groups = {}
    for node in nodes:
        type_name = node.bl_idname
        if type_name not in type_groups:
            type_groups[type_name] = []
        type_groups[type_name].append(node)

    # Sort groups by type name for consistency
    return [type_groups[key] for key in sorted(type_groups.keys())]


def _group_by_cluster(nodes: list) -> list[list]:
    """
    Group nodes by their parent frame (cluster).

    Returns a list of node lists, one per cluster.
    """
    cluster_groups = {}
    for node in nodes:
        # Use parent frame as cluster key (None for nodes without parent)
        cluster_key = id(node.parent) if node.parent else None
        if cluster_key not in cluster_groups:
            cluster_groups[cluster_key] = []
        cluster_groups[cluster_key].append(node)

    # Return groups (order doesn't matter much here)
    return list(cluster_groups.values())


def _calculate_cell_sizes(nodes: list) -> tuple[float, float]:
    """
    Calculate cell sizes based on the largest node dimensions.

    Adds some padding (20% extra space).
    """
    max_width = 0.0
    max_height = 0.0

    for node in nodes:
        w, h = dimensions(node)
        max_width = max(max_width, w)
        max_height = max(max_height, h)

    # Add 20% padding
    return max_width * 1.2, max_height * 1.2
