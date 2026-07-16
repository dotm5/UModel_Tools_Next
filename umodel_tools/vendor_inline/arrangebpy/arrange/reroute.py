# SPDX-License-Identifier: GPL-2.0-or-later

"""
Reroute Node Handling

This module contains functionality for processing reroute nodes in the Sugiyama layout,
including path detection, removal, alignment, and realization.
"""

from __future__ import annotations

from collections.abc import Callable

import networkx as nx
from bpy.types import NodeTree

from .. import config
from .graph import (
    FROM_SOCKET,
    TO_SOCKET,
    ClusterGraph,
    GNode,
    GType,
    Socket,
    add_dummy_edge,
    is_real,
)


def get_reroute_paths(
    cluster_graph: ClusterGraph,
    function: Callable | None = None,
    *,
    preserve_reroute_clusters: bool = True,
    must_be_aligned: bool = False,
) -> list[list[GNode]]:
    """
    Find connected chains of reroute nodes that can be processed together.
    """
    graph = cluster_graph.G
    reroutes = {
        vertex
        for vertex in graph
        if vertex.is_reroute and (not function or function(vertex))
    }
    subgraph = nx.DiGraph(graph.subgraph(reroutes))

    for vertex in subgraph:
        if graph.out_degree[vertex] > 1:
            subgraph.remove_edges_from(tuple(subgraph.out_edges(vertex)))

    if preserve_reroute_clusters:
        reroute_clusters = {
            cluster
            for cluster in cluster_graph.S
            if all(
                vertex.is_reroute
                for vertex in cluster_graph.T[cluster]
                if vertex.type != GType.CLUSTER
            )
        }
        subgraph.remove_edges_from(
            [
                (from_node, to_node)
                for from_node, to_node in subgraph.edges
                if from_node.cluster != to_node.cluster
                and {from_node.cluster, to_node.cluster} & reroute_clusters
            ]
        )

    if must_be_aligned:
        subgraph.remove_edges_from(
            [
                (from_node, to_node)
                for from_node, to_node in subgraph.edges
                if from_node.y != to_node.y
            ]
        )

    indices = {
        vertex: i
        for i, vertex in enumerate(nx.topological_sort(graph))
        if vertex in reroutes
    }
    paths = [
        sorted(component, key=lambda vertex: indices[vertex])
        for component in nx.weakly_connected_components(subgraph)
    ]
    paths.sort(key=lambda path: indices[path[0]])
    return paths


def is_safe_to_remove(vertex: GNode) -> bool:
    """
    Check if a reroute node can be safely removed from the graph.
    """
    if not is_real(vertex):
        return True

    if vertex.node.label:
        return False

    for sort_values in config.multi_input_sort_ids.values():
        if any(vertex == sort_item[0].owner for sort_item in sort_values):
            return False

    return True


def dissolve_reroute_edges(graph: nx.DiGraph[GNode], path: list[GNode]) -> None:
    """
    Remove a reroute path by connecting its inputs directly to its outputs.
    """
    if not graph[path[-1]]:
        return

    try:
        predecessor, _, output_socket = next(
            iter(graph.in_edges(path[0], data=FROM_SOCKET))
        )
    except StopIteration:
        return

    successor_inputs = [edge[2] for edge in graph.out_edges(path[-1], data=TO_SOCKET)]

    # Check if a reroute has been used to link the same output to the same multi-input multiple times
    for *_, edge_data in graph.out_edges(predecessor, data=True):
        if (
            edge_data[FROM_SOCKET] == output_socket
            and edge_data[TO_SOCKET] in successor_inputs
        ):
            path.clear()
            return

    for input_socket in successor_inputs:
        graph.add_edge(
            predecessor,
            input_socket.owner,
            from_socket=output_socket,
            to_socket=input_socket,
        )
        input_socket.owner.node.id_data.links.new(output_socket.bpy, input_socket.bpy)


def remove_reroutes(cluster_graph: ClusterGraph) -> None:
    """
    Remove unnecessary reroute nodes from the cluster graph.
    """
    reroute_clusters = {
        cluster
        for cluster in cluster_graph.S
        if all(
            vertex.type != GType.CLUSTER and vertex.is_reroute
            for vertex in cluster_graph.T[cluster]
        )
    }
    for path in get_reroute_paths(cluster_graph, is_safe_to_remove):
        if path[0].cluster in reroute_clusters:
            if len(path) > 2:
                start_node, *intermediate_nodes, end_node = path
                add_dummy_edge(cluster_graph.G, start_node, end_node)
                cluster_graph.remove_nodes_from(intermediate_nodes)
        else:
            dissolve_reroute_edges(cluster_graph.G, path)
            cluster_graph.remove_nodes_from(path)


def align_reroutes_with_sockets(cluster_graph: ClusterGraph) -> None:
    """
    Align reroute nodes with their connected sockets for cleaner routing.
    """
    reroute_paths: dict[tuple[GNode, ...], list[Socket]] = {}
    for path in get_reroute_paths(
        cluster_graph, preserve_reroute_clusters=False, must_be_aligned=True
    ):
        inputs = cluster_graph.G.in_edges(path[0], data=FROM_SOCKET)
        outputs = cluster_graph.G.out_edges(path[-1], data=TO_SOCKET)
        reroute_paths[tuple(path)] = [edge[2] for edge in (*inputs, *outputs)]

    max_iterations = 100  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations and reroute_paths:
        iteration += 1
        changed = False

        # Process a copy of the paths to avoid modification during iteration
        paths_to_process = list(reroute_paths.items())

        for path, foreign_sockets in paths_to_process:
            if path not in reroute_paths:  # Path was already removed
                continue

            current_y = path[0].y

            # Ensure foreign_sockets is not empty
            if not foreign_sockets:
                del reroute_paths[path]
                continue

            foreign_sockets.sort(key=lambda socket: abs(current_y - socket.y))
            foreign_sockets.sort(
                key=lambda socket: current_y == socket.owner.y, reverse=True
            )

            if current_y - foreign_sockets[0].y == 0:
                del reroute_paths[path]
                continue

            movement = current_y - foreign_sockets[0].y
            new_y = current_y - movement

            # Check collision constraints
            collision = False
            if movement < 0:
                above_y_vals = []
                for vertex in path:
                    if vertex.col and vertex in vertex.col and vertex != vertex.col[0]:
                        vertex_index = vertex.col.index(vertex)
                        above_node = vertex.col[vertex_index - 1]
                        above_y_vals.append(above_node.y - above_node.height)
                if above_y_vals and new_y > min(above_y_vals):
                    collision = True
            else:
                below_y_vals = []
                for vertex in path:
                    if vertex.col and vertex in vertex.col and vertex != vertex.col[-1]:
                        vertex_index = vertex.col.index(vertex)
                        below_node = vertex.col[vertex_index + 1]
                        below_y_vals.append(below_node.y)
                if below_y_vals and max(below_y_vals) > new_y - path[0].height:
                    collision = True

            if not collision:
                # Apply movement
                for vertex in path:
                    vertex.y = new_y
                changed = True
                del reroute_paths[path]
            else:
                # Remove this socket option and try again later
                if len(foreign_sockets) > 1:
                    foreign_sockets.pop(0)
                else:
                    del reroute_paths[path]

        # If no changes occurred, we're done
        if not changed:
            break


def simplify_path(cluster_graph: ClusterGraph, path: list[GNode]) -> None:
    """
    Simplify a reroute path by removing unnecessary intermediate nodes.
    """
    if len(path) == 1:
        return

    start_node, *intermediate_nodes, end_node = path
    graph = cluster_graph.G

    if (
        graph.pred[start_node]
        and (
            input_socket := next(iter(graph.in_edges(start_node, data=FROM_SOCKET)))[2]
        ).y
        == start_node.y
    ):
        graph.add_edge(
            input_socket.owner,
            end_node,
            from_socket=input_socket,
            to_socket=Socket(end_node, 0, False),
        )
        intermediate_nodes.append(start_node)
    elif (
        graph.out_degree[end_node] == 1
        and end_node.y
        == (output_socket := next(iter(graph.out_edges(end_node, data=TO_SOCKET)))[2]).y
    ):
        graph.add_edge(
            start_node,
            output_socket.owner,
            from_socket=Socket(start_node, 0, True),
            to_socket=output_socket,
        )
        intermediate_nodes.append(end_node)
    elif intermediate_nodes:
        add_dummy_edge(graph, start_node, end_node)

    cluster_graph.remove_nodes_from(intermediate_nodes)
    for node in intermediate_nodes:
        if node not in graph:
            path.remove(node)


def add_reroute(vertex: GNode, ntree: NodeTree) -> None:
    """
    Convert a dummy node into a real Blender reroute node.
    """
    reroute = ntree.nodes.new(type="NodeReroute")
    assert vertex.cluster
    reroute.parent = vertex.cluster.node
    vertex.node = reroute
    vertex.type = GType.NODE


def realize_edges(graph: nx.DiGraph[GNode], vertex: GNode) -> None:
    """
    Create actual Blender node links for edges connected to a realized node.
    """
    assert is_real(vertex)
    links = vertex.node.id_data.links

    if graph.pred[vertex]:
        predecessor_output = next(iter(graph.in_edges(vertex, data=FROM_SOCKET)))[2]
        links.new(predecessor_output.bpy, vertex.node.inputs[0])

    for _, successor_node, successor_input in graph.out_edges(vertex, data=TO_SOCKET):
        if is_real(successor_node):
            links.new(vertex.node.outputs[0], successor_input.bpy)


def realize_dummy_nodes(cluster_graph: ClusterGraph, ntree: NodeTree) -> None:
    """
    Convert all dummy nodes in reroute paths to actual Blender reroute nodes.
    """
    for path in get_reroute_paths(
        cluster_graph, is_safe_to_remove, must_be_aligned=True
    ):
        simplify_path(cluster_graph, path)

        for vertex in path:
            if not is_real(vertex):
                add_reroute(vertex, ntree)

            realize_edges(cluster_graph.G, vertex)
