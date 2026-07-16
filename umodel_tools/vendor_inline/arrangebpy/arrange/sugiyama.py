# SPDX-License-Identifier: GPL-2.0-or-later

"""
Sugiyama Framework Implementation.

This module orchestrates the Sugiyama layout algorithm by coordinating
the individual phases, each handled by specialized modules.
"""

from __future__ import annotations

from statistics import fmean
from typing import cast

import networkx as nx
from bpy.types import NodeFrame, NodeTree
from mathutils import Vector

from .. import config
from ..settings import LayoutSettings
from ..utils import abs_loc
from .coordinates import (
    add_columns,
    assign_x_coords,
    realize_locations,
    resize_unshrunken_frame,
)
from .graph import Cluster, ClusterGraph, GNode, GType, Socket
from .multi_input import restore_multi_input_orders, save_multi_input_orders
from .ordering import minimize_crossings
from .placement.bk import bk_assign_y_coords
from .placement.linear_segments import linear_segments_assign_y_coords
from .ranking import compute_ranks
from .reroute import align_reroutes_with_sockets, realize_dummy_nodes, remove_reroutes
from .routing import route_edges
from .stacking import contracted_node_stacks, expand_node_stack


def precompute_links(ntree: NodeTree) -> None:
    """Precompute valid links in the node tree for efficient lookup."""
    config.linked_sockets.clear()
    for link in ntree.links:
        if not link.is_hidden and link.is_valid:
            config.linked_sockets[link.to_socket].add(link.from_socket)
            config.linked_sockets[link.from_socket].add(link.to_socket)


def build_graph(ntree: NodeTree) -> ClusterGraph:
    """Build the initial graph representation from the node tree."""
    # Build cluster hierarchy
    parents = {
        node.parent: Cluster(cast(NodeFrame | None, node.parent))
        for node in ntree.nodes
    }
    for cluster in parents.values():
        if cluster.node:
            cluster.cluster = parents[cluster.node.parent]

    # Create graph with nodes and edges
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(
        [
            GNode(node, parents[node.parent])
            for node in ntree.nodes
            if node.bl_idname != "NodeFrame"
        ]
    )

    for graph_node in graph:
        for output_idx, from_output in enumerate(graph_node.node.outputs):
            for to_input in config.linked_sockets[from_output]:
                target_node = next(
                    (target for target in graph if target.node == to_input.node), None
                )
                if target_node is None:
                    continue

                input_idx = to_input.node.inputs[:].index(to_input)
                graph.add_edge(
                    graph_node,
                    target_node,
                    from_socket=Socket(graph_node, output_idx, True),
                    to_socket=Socket(target_node, input_idx, False),
                )

    return ClusterGraph(graph)


def sugiyama_layout(
    ntree: NodeTree, settings: LayoutSettings = LayoutSettings()
) -> None:
    """
    Apply the complete Sugiyama layout algorithm to nodes.

    Main orchestration function that coordinates all layout phases:
    1. Graph construction
    2. Preprocessing (includes optional node stacking)
    3. Ranking
    4. Crossing minimization
    5. Coordinate assignment (with direction and socket alignment)
    6. Edge routing
    7. Realization

    Args:
        ntree: The Blender node tree to layout
        settings: Layout settings controlling all aspects of the algorithm

    Examples:
        # Simple usage with defaults
        sugiyama_layout(ntree)

        # Custom settings
        settings = LayoutSettings(
            direction="LEFT_DOWN",
            socket_alignment="FULL",
            stack_collapsed=True,
            iterations=10
        )
        sugiyama_layout(ntree, settings)

        # Quick spacing override
        sugiyama_layout(ntree, LayoutSettings(
            horizontal_spacing=60.0,
            vertical_spacing=30.0
        ))
    """

    # Get layout nodes and preserve center
    layout_nodes = [node for node in ntree.nodes if node.bl_idname != "NodeFrame"]
    locations = [abs_loc(node) for node in layout_nodes]
    if not locations:
        return

    old_center = Vector(map(fmean, zip(*locations)))

    # Clear and initialize config
    config.multi_input_sort_ids.clear()

    # Phase 1: Graph Construction
    precompute_links(ntree)
    cluster_graph = build_graph(ntree)
    graph = cluster_graph.G
    tree = cluster_graph.T

    # Phase 2: Preprocessing
    save_multi_input_orders(graph, ntree)

    if settings.add_reroutes:
        # Keep reroutes parameter implementation
        # Note: keep_reroutes_outside_frames would need to be passed to remove_reroutes
        remove_reroutes(cluster_graph)

    # Optional: Contract collapsed math nodes into stacks
    node_stacks = []
    if settings.stack_collapsed:
        node_stacks = contracted_node_stacks(
            cluster_graph, settings.stack_margin_y_factor
        )

    # Phase 3: Ranking
    compute_ranks(cluster_graph)
    cluster_graph.merge_edges()
    cluster_graph.insert_dummy_nodes()

    # Phase 4: Crossing Minimization
    add_columns(graph)
    minimize_crossings(
        graph,
        tree,
        sweeps=settings.crossing_reduction_sweeps,
    )

    # Phase 5: Y-Coordinate Assignment
    if len(cluster_graph.S) == 1:
        # Simple case: no frames or all in one frame
        bk_assign_y_coords(
            graph,
            tree,
            vertical_spacing=settings.vertical_spacing,
            direction=settings.direction,
            socket_alignment=settings.socket_alignment,
            iterations=settings.iterations,
            align_top_layer=settings.align_top_layer,
        )
    else:
        # Complex case: multiple frames with vertical borders
        cluster_graph.add_vertical_border_nodes()
        linear_segments_assign_y_coords(
            cluster_graph,
            vertical_spacing=settings.vertical_spacing,
            direction=settings.direction,
            socket_alignment=settings.socket_alignment,
            iterations=settings.iterations,
            align_top_layer=settings.align_top_layer,
        )
        cluster_graph.remove_nodes_from(
            [vertex for vertex in graph if vertex.type == GType.VERTICAL_BORDER]
        )

    # Phase 6: Coordinate Assignment and Routing
    if settings.add_reroutes:
        align_reroutes_with_sockets(cluster_graph)

    assign_x_coords(graph, tree, settings.horizontal_spacing)

    if settings.add_reroutes:
        route_edges(
            graph,
            tree,
            settings.horizontal_spacing / 2,
            settings.vertical_spacing / 2,
        )

    # Optional: Expand node stacks back to individual nodes
    if settings.stack_collapsed:
        for node_stack in node_stacks:
            expand_node_stack(cluster_graph, node_stack, settings.stack_margin_y_factor)

    # Phase 7: Realization
    if settings.add_reroutes:
        realize_dummy_nodes(cluster_graph, ntree)

    restore_multi_input_orders(graph, ntree)
    realize_locations(graph, old_center, ntree)

    # Finalize frame sizes
    for cluster in cluster_graph.S:
        resize_unshrunken_frame(cluster_graph, cluster)
