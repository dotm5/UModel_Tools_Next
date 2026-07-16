# SPDX-License-Identifier: GPL-2.0-or-later

"""
Coordinate Assignment

This module handles the assignment of x and y coordinates to nodes in the
Sugiyama layout, including column organization and spacing calculations.
"""

from __future__ import annotations

from itertools import chain
from statistics import fmean
from typing import Sequence, Collection, cast

import networkx as nx
from bpy.types import Node, NodeTree
from mathutils import Vector

from ..utils import abs_loc, frame_padding, group_by
from .graph import FROM_SOCKET, TO_SOCKET, Cluster, GNode, is_real, node_name


def add_columns(graph: nx.DiGraph[GNode]) -> None:
    """
    Organize nodes into columns based on their rank and sort by position.
    """
    columns = [
        list(component)
        for component in group_by(graph, key=lambda vertex: vertex.rank, sort=True)
    ]
    graph.graph["columns"] = columns

    # Helper to check if a node is isolated (for more stable sorting)
    def y_loc(v):
        return abs_loc(v.node).y if is_real(v) and nx.is_isolate(graph, v) else 0

    for column in columns:
        # Sort by name first for stability, then by y-position
        column.sort(key=node_name)
        column.sort(key=y_loc, reverse=True)
        for vertex in column:
            vertex.col = column


def frame_padding_of_col(
    columns: Sequence[Collection[GNode]],
    column_index: int,
    tree: nx.DiGraph[GNode | Cluster],
) -> float:
    """
    Calculate additional spacing needed between columns due to frame nesting.
    """
    current_column = columns[column_index]

    if current_column == columns[-1]:
        return 0

    clusters1 = {cast(Cluster, vertex.cluster) for vertex in current_column}
    clusters2 = {cast(Cluster, vertex.cluster) for vertex in columns[column_index + 1]}

    if not clusters1 ^ clusters2:
        return 0

    subtree1 = tree.subgraph(
        chain(clusters1, *[nx.ancestors(tree, cluster) for cluster in clusters1])
    ).copy()
    subtree2 = tree.subgraph(
        chain(clusters2, *[nx.ancestors(tree, cluster) for cluster in clusters2])
    ).copy()

    for *edge_nodes, edge_data in subtree1.edges(data=True):
        edge_data["weight"] = int(edge_nodes not in subtree2.edges)

    for *edge_nodes, edge_data in subtree2.edges(data=True):
        edge_data["weight"] = int(edge_nodes not in subtree1.edges)

    distance = nx.dag_longest_path_length(subtree1) + nx.dag_longest_path_length(
        subtree2
    )
    return frame_padding() * distance


def assign_x_coords(
    graph: nx.DiGraph[GNode],
    tree: nx.DiGraph[GNode | Cluster],
    horizontal_spacing: float,
) -> None:
    """
    Assign horizontal coordinates to all nodes based on their columns.

    Args:
        graph: The directed graph with nodes to layout
        tree: The cluster tree for frame padding calculations
        horizontal_spacing: Horizontal spacing between columns
    """
    columns: list[list[GNode]] = graph.graph["columns"]
    current_x = 0.0

    for column_index, column in enumerate(columns):
        max_width = max(vertex.width for vertex in column)

        for vertex in column:
            # Reroutes are centered, other nodes are centered within the column width
            vertex.x = (
                current_x
                if vertex.is_reroute
                else current_x - (vertex.width - max_width) / 2
            )

        # Adaptive spacing: more space when edges have large vertical deltas
        # https://doi.org/10.7155/jgaa.00220 (p. 139)
        large_delta_edges = sum(
            1
            for *_, edge_data in graph.out_edges(column, data=True)
            if abs(edge_data[TO_SOCKET].y - edge_data[FROM_SOCKET].y)
            >= horizontal_spacing * 3
        )
        spacing_multiplier = 1 + min(large_delta_edges / 4, 2)
        spacing = spacing_multiplier * horizontal_spacing

        current_x += (
            max_width + spacing + frame_padding_of_col(columns, column_index, tree)
        )


def realize_locations(
    graph: nx.DiGraph[GNode], old_center: Vector, ntree: NodeTree
) -> None:
    """
    Apply computed node positions to actual Blender nodes.
    """
    if not graph:
        return

    # Collect valid coordinates, filtering out NaN values
    valid_x_coords = [
        vertex.x
        for vertex in graph
        if isinstance(vertex.x, (int, float)) and vertex.x == vertex.x
    ]
    valid_y_coords = [
        vertex.y
        for vertex in graph
        if isinstance(vertex.y, (int, float)) and vertex.y == vertex.y
    ]

    # Use fallback if no valid coordinates
    if not valid_x_coords or not valid_y_coords:
        new_center = (0.0, 0.0)
    else:
        new_center = (fmean(valid_x_coords), fmean(valid_y_coords))

    offset_x, offset_y = -Vector(new_center) + old_center

    for vertex in graph:
        if not isinstance(vertex.node, Node) or not vertex.cluster:
            continue

        # Optimization: avoid using bpy.ops for as many nodes as possible
        vertex.node.parent = None

        # Ensure coordinates are valid before applying
        if isinstance(vertex.x, (int, float)) and vertex.x == vertex.x:
            final_x = vertex.x + offset_x
        else:
            final_x = old_center.x

        if isinstance(vertex.y, (int, float)) and vertex.y == vertex.y:
            try:
                corrected_y = vertex.corrected_y()
                if isinstance(corrected_y, (int, float)) and corrected_y == corrected_y:
                    final_y = corrected_y + offset_y
                else:
                    final_y = vertex.y + offset_y
            except Exception:
                final_y = vertex.y + offset_y
        else:
            final_y = old_center.y

        vertex.node.location = (final_x, final_y)
        vertex.node.parent = vertex.cluster.node


def resize_unshrunken_frame(cluster_graph, cluster: Cluster) -> None:
    """
    Resize node frames that are set to not shrink automatically.
    """
    frame = cluster.node

    if not frame or frame.shrink:
        return

    real_children = [vertex for vertex in cluster_graph.T[cluster] if is_real(vertex)]

    for vertex in real_children:
        vertex.node.parent = None

    frame.shrink = False
    frame.shrink = True

    for vertex in real_children:
        vertex.node.parent = frame
