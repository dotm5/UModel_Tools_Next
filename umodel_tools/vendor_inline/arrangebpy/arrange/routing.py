# SPDX-License-Identifier: GPL-2.0-or-later

"""
Edge Routing

This module handles the creation of bend points and edge routing for clean
visual connections between nodes in the Sugiyama layout.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import chain

import networkx as nx
from mathutils.geometry import intersect_line_line_2d

from ..utils import frame_padding, group_by
from .graph import (
    FROM_SOCKET,
    TO_SOCKET,
    Cluster,
    GNode,
    GType,
    MultiEdge,
    Socket,
    add_dummy_nodes_to_edge,
    lowest_common_cluster,
)

_MIN_X_DIFF = 30
_MIN_Y_DIFF = 15


def is_unnecessary_bend_point(
    socket: Socket,
    other_socket: Socket,
    x_spacing: float = 25.0,
    y_spacing: float = 25.0,
) -> bool:
    """
    Determine if a bend point would be unnecessary for edge routing.
    """
    vertex = socket.owner

    if vertex.is_reroute:
        return False

    vertex_index = vertex.col.index(vertex)
    is_above = other_socket.y > socket.y

    try:
        neighbor = (
            vertex.col[vertex_index - 1] if is_above else vertex.col[vertex_index + 1]
        )
    except IndexError:
        return True

    if neighbor.is_reroute:
        return True

    neighbor_x_offset, neighbor_y_offset = x_spacing / 2, y_spacing / 2
    neighbor_y = (
        neighbor.y - neighbor.height - neighbor_y_offset
        if is_above
        else neighbor.y + neighbor_y_offset
    )

    assert neighbor.cluster
    if neighbor.cluster.node and neighbor.cluster != vertex.cluster:
        neighbor_x_offset += frame_padding()
        if is_above:
            neighbor_y -= frame_padding()
        else:
            neighbor_y += frame_padding() + neighbor.cluster.label_height()

    line_a = (
        (neighbor.x - neighbor_x_offset, neighbor_y),
        (neighbor.x + neighbor.width + neighbor_x_offset, neighbor_y),
    )
    line_b = ((socket.x, socket.y), (other_socket.x, other_socket.y))
    return intersect_line_line_2d(*line_a, *line_b) is None


def add_bend_points(
    graph: nx.MultiDiGraph[GNode],
    vertex: GNode,
    bend_points: defaultdict[MultiEdge, list[GNode]],
    x_spacing: float = 25.0,
    y_spacing: float = 25.0,
) -> None:
    """
    Add bend points for edges connected to a node to avoid visual conflicts.
    """
    edge_data: dict[str, Socket]
    largest = max(vertex.col, key=lambda node: node.width)
    for from_node, to_node, key, edge_data in (
        *graph.out_edges(vertex, data=True, keys=True),
        *graph.in_edges(vertex, data=True, keys=True),
    ):
        socket = edge_data[FROM_SOCKET] if vertex == from_node else edge_data[TO_SOCKET]
        bend_point = GNode(type=GType.DUMMY)
        bend_point.x = largest.x + largest.width if socket.is_output else largest.x

        if abs(socket.x - bend_point.x) <= _MIN_X_DIFF:
            continue

        bend_point.y = socket.y
        other_socket = next(sock for sock in edge_data.values() if sock != socket)

        if abs(other_socket.y - bend_point.y) <= _MIN_Y_DIFF:
            continue

        if is_unnecessary_bend_point(socket, other_socket, x_spacing, y_spacing):
            continue

        bend_points[from_node, to_node, key].append(bend_point)


def node_overlaps_edge(
    vertex: GNode,
    edge_line: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    """
    Check if a node's bounding box intersects with an edge line.
    """
    if vertex.is_reroute:
        return False

    top_line = ((vertex.x, vertex.y), (vertex.x + vertex.width, vertex.y))
    if intersect_line_line_2d(*edge_line, *top_line):
        return True

    bottom_line = (
        (vertex.x, vertex.y - vertex.height),
        (vertex.x + vertex.width, vertex.y - vertex.height),
    )
    if intersect_line_line_2d(*edge_line, *bottom_line):
        return True

    return False


def route_edges(
    graph: nx.MultiDiGraph[GNode],
    tree: nx.DiGraph[GNode | Cluster],
    x_spacing: float = 25.0,
    y_spacing: float = 25.0,
) -> None:
    """
    Create bend points for all edges to enable clean visual routing.
    """
    bend_points = defaultdict(list)
    for vertex in chain(*graph.graph["columns"]):
        add_bend_points(graph, vertex, bend_points, x_spacing, y_spacing)

    # Merge bend points that serve the same routing purpose
    edge_of = {
        bend_point: edge
        for edge, dummy_list in bend_points.items()
        for bend_point in dummy_list
    }

    def bend_point_key(bend_point: GNode) -> tuple[Socket, float, float]:
        return (
            graph.edges[edge_of[bend_point]][FROM_SOCKET],
            bend_point.x,
            bend_point.y,
        )

    for (target, *redundant), (from_socket, *_) in group_by(
        edge_of, key=bend_point_key
    ).items():
        for bend_point in redundant:
            dummy_nodes = bend_points[edge_of[bend_point]]
            dummy_nodes[dummy_nodes.index(bend_point)] = target

        owner_node = from_socket.owner
        if not owner_node.is_reroute or graph.out_degree[owner_node] < 2:
            continue

        # Handle reroute fan-out patterns
        for edge in graph.out_edges(owner_node, keys=True):
            if (
                target not in bend_points[edge]
                and graph.edges[edge][TO_SOCKET].y == target.y
            ):
                bend_points[edge].append(target)

    # Reuse bend points for edges that can share routing paths
    for edge, dummy_nodes in tuple(bend_points.items()):
        dummy_nodes.sort(key=lambda bend_point: bend_point.x)
        from_socket = graph.edges[edge][FROM_SOCKET]
        for other_edge in graph.out_edges(edge[0], keys=True):
            edge_data = graph.edges[other_edge]

            if edge_data[FROM_SOCKET] != from_socket or other_edge in bend_points:
                continue

            if edge_data[TO_SOCKET].x <= dummy_nodes[-1].x:
                continue

            last_bend_point = dummy_nodes[-1]
            line = (
                (last_bend_point.x, last_bend_point.y),
                (edge_data[TO_SOCKET].x, edge_data[TO_SOCKET].y),
            )
            if any(node_overlaps_edge(vertex, line) for vertex in edge[1].col):
                continue

            bend_points[other_edge] = dummy_nodes

    # Add dummy nodes to graph structure for visualization
    lowest_common_clusters = lowest_common_cluster(tree, bend_points)
    for (from_node, to_node, key), dummy_nodes in bend_points.items():
        add_dummy_nodes_to_edge(graph, (from_node, to_node, key), dummy_nodes)

        cluster = lowest_common_clusters.get((from_node, to_node), from_node.cluster)
        for dummy_node in dummy_nodes:
            dummy_node.cluster = cluster
            tree.add_edge(cluster, dummy_node)
