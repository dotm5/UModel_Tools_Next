# SPDX-License-Identifier: GPL-2.0-or-later

"""
Simple Topological Layout

A simplified, faster alternative to Sugiyama that arranges nodes in layers
based on topological sort without performing crossing reduction.

Good for:
- Quick layouts during development
- Very large graphs where speed matters
- Simple node trees without complex interconnections
"""

from __future__ import annotations

from statistics import fmean
from typing import cast

import networkx as nx
from bpy.types import NodeFrame, NodeTree
from mathutils import Vector

from .. import config
from ..settings import TopologicalSettings
from ..utils import abs_loc, dimensions
from .graph import Cluster, GNode


def topological_layout(
    ntree: NodeTree, settings: TopologicalSettings = TopologicalSettings()
) -> None:
    """
    Apply simple topological (layered) layout to nodes.

    This algorithm:
    1. Builds a directed graph from the node tree
    2. Computes topological layers (nodes at same distance from sources)
    3. Optionally sorts nodes in each layer by degree
    4. Places nodes in a left-to-right layout

    Much faster than Sugiyama but produces more edge crossings.

    Args:
        ntree: The Blender node tree to layout
        settings: Layout settings controlling spacing and sorting

    Examples:
        # Simple usage with defaults
        topological_layout(ntree)

        # Custom spacing
        topological_layout(ntree, TopologicalSettings(
            horizontal_spacing=60.0,
            vertical_spacing=30.0
        ))

        # No sorting, minimal processing
        topological_layout(ntree, TopologicalSettings(
            sort_by_degree=False,
            center_nodes=False
        ))
    """
    # Get layout nodes and preserve center
    layout_nodes = [node for node in ntree.nodes if node.bl_idname != "NodeFrame"]
    if not layout_nodes:
        return

    locations = [abs_loc(node) for node in layout_nodes]
    old_center = Vector(map(fmean, zip(*locations)))

    # Clear config
    config.multi_input_sort_ids.clear()

    # Build graph
    graph = _build_simple_graph(ntree, layout_nodes)

    # Note: We skip save_multi_input_orders for simple topological layout
    # since we don't use MultiDiGraph with socket data

    # Early return if no nodes
    if len(graph) == 0:
        return

    # Compute layers using topological sort
    layers = _compute_layers(graph)

    # Optionally sort each layer
    if settings.sort_by_degree:
        _sort_layers_by_degree(layers, graph)

    # Assign positions
    _assign_positions(layers, graph, settings)

    # Note: We skip restore_multi_input_orders since we didn't save them

    # Realize positions back to Blender, preserving center
    _realize_positions(graph, layout_nodes, old_center)


def _build_simple_graph(ntree: NodeTree, layout_nodes: list) -> nx.DiGraph:
    """Build a simple directed graph from the node tree."""
    # Precompute links
    config.linked_sockets.clear()
    for link in ntree.links:
        if not link.is_hidden and link.is_valid:
            config.linked_sockets[link.to_socket].add(link.from_socket)
            config.linked_sockets[link.from_socket].add(link.to_socket)

    # Build cluster hierarchy (simplified - just for graph nodes)
    parents = {
        node.parent: Cluster(cast(NodeFrame | None, node.parent))
        for node in layout_nodes
    }

    # Create graph
    graph = nx.DiGraph()
    graph.add_nodes_from([GNode(node, parents[node.parent]) for node in layout_nodes])

    # Add edges (simplified - no socket info needed)
    for graph_node in graph:
        for output in graph_node.node.outputs:
            for to_input in config.linked_sockets[output]:
                target_node = next(
                    (target for target in graph if target.node == to_input.node), None
                )
                if target_node is not None:
                    graph.add_edge(graph_node, target_node)

    return graph


def _compute_layers(graph: nx.DiGraph) -> list[list[GNode]]:
    """
    Compute node layers based on longest path from sources.

    Each layer contains nodes at the same distance from source nodes.
    """
    # Find source nodes (no incoming edges)
    sources = [node for node in graph if graph.in_degree(node) == 0]

    # If no sources (cycle), pick node with lowest out-degree
    if not sources:
        sources = [min(graph.nodes(), key=lambda n: graph.out_degree(n))]

    # Compute longest path distance from any source
    distances = {}
    for node in nx.topological_sort(graph):
        if node in sources:
            distances[node] = 0
        else:
            # Distance is max of predecessor distances + 1
            predecessors = list(graph.predecessors(node))
            if predecessors:
                distances[node] = (
                    max(distances.get(pred, 0) for pred in predecessors) + 1
                )
            else:
                distances[node] = 0

    # Group nodes by distance into layers
    max_distance = max(distances.values()) if distances else 0
    layers = [[] for _ in range(max_distance + 1)]

    for node, distance in distances.items():
        layers[distance].append(node)

    return layers


def _sort_layers_by_degree(layers: list[list[GNode]], graph: nx.DiGraph) -> None:
    """
    Sort nodes within each layer by their total degree.

    Nodes with fewer connections are placed at the top.
    This can reduce edge crossings in some cases.
    """
    for layer in layers:
        layer.sort(key=lambda node: graph.degree(node))


def _assign_positions(
    layers: list[list[GNode]], graph: nx.DiGraph, settings: TopologicalSettings
) -> None:
    """
    Assign x and y coordinates to all nodes.

    X coordinate is based on layer index.
    Y coordinate is based on position within layer.
    """
    for layer_idx, layer in enumerate(layers):
        # X coordinate: layer index * horizontal spacing
        x = layer_idx * settings.horizontal_spacing

        if settings.flatten:
            # Flatten mode: all nodes at Y=0
            y_offset = 0
            for node in layer:
                node.x = x
                node.y = 0
        elif settings.center_nodes:
            # Center the layer vertically
            total_height = sum(dimensions(node.node)[1] for node in layer)
            total_spacing = (len(layer) - 1) * settings.vertical_spacing
            layer_height = total_height + total_spacing
            y_offset = -layer_height / 2

            # Assign positions to nodes in this layer
            current_y = y_offset
            for node in layer:
                node.x = x
                node.y = current_y
                # Move down by node height + spacing
                current_y += dimensions(node.node)[1] + settings.vertical_spacing
        else:
            # No centering
            y_offset = 0
            current_y = y_offset
            for node in layer:
                node.x = x
                node.y = current_y
                # Move down by node height + spacing
                current_y += dimensions(node.node)[1] + settings.vertical_spacing


def _realize_positions(
    graph: nx.DiGraph, layout_nodes: list, old_center: Vector
) -> None:
    """
    Apply computed positions back to Blender nodes, preserving center.
    """
    # Create mapping from blender nodes to graph nodes
    node_to_gnode = {gnode.node: gnode for gnode in graph}

    # Compute new center
    new_locations = [
        (node_to_gnode[node].x, node_to_gnode[node].y) for node in layout_nodes
    ]
    new_center = Vector(map(fmean, zip(*new_locations)))

    # Apply positions with offset to preserve center
    offset = old_center - new_center

    for node in layout_nodes:
        gnode = node_to_gnode[node]
        node.location.x = gnode.x + offset.x
        node.location.y = gnode.y + offset.y
