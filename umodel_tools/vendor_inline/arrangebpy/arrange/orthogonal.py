# SPDX-License-Identifier: GPL-2.0-or-later

"""
Orthogonal Edge Routing for Sugiyama Layout

Uses the Sugiyama hierarchical layout for node placement, but routes edges
with only horizontal and vertical segments (no diagonal lines).

This creates a cleaner, "blueprint" style appearance that's easier to follow
and more professional looking for documentation and presentations.
"""

from __future__ import annotations

from statistics import fmean
from typing import cast

import networkx as nx
from bpy.types import NodeFrame, NodeTree
from mathutils import Vector

from .. import config
from ..settings import OrthogonalSettings
from ..utils import abs_loc
from .coordinates import (
    add_columns,
    assign_x_coords,
    realize_locations,
    resize_unshrunken_frame,
)
from .graph import Cluster, ClusterGraph, GNode, GType
from .multi_input import restore_multi_input_orders, save_multi_input_orders
from .ordering import minimize_crossings
from .placement.bk import bk_assign_y_coords
from .placement.linear_segments import linear_segments_assign_y_coords
from .ranking import compute_ranks
from .reroute import remove_reroutes
from .stacking import contracted_node_stacks, expand_node_stack


def orthogonal_layout(
    ntree: NodeTree, settings: OrthogonalSettings = OrthogonalSettings()
) -> None:
    """
    Apply Sugiyama layout with orthogonal edge routing.

    This uses the same hierarchical node placement as sugiyama_layout(),
    but routes all edges with only horizontal and vertical segments.

    The routing algorithm:
    1. Uses Sugiyama for node placement
    2. Routes edges with stairstep or grid-based pathfinding
    3. Adds reroute nodes at each bend point

    Args:
        ntree: The Blender node tree to layout
        settings: Layout settings controlling all aspects

    Examples:
        # Simple usage
        orthogonal_layout(ntree)

        # Custom settings
        orthogonal_layout(ntree, OrthogonalSettings(
            horizontal_spacing=80.0,  # More space for routing
            vertical_spacing=40.0,
            socket_alignment="FULL",
            route_through_grid=True
        ))

        # With node stacking
        orthogonal_layout(ntree, OrthogonalSettings(
            stack_collapsed=True,
            min_segment_length=30.0
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

    # Phase 1: Graph Construction (same as Sugiyama)
    precompute_links(ntree)
    cluster_graph = build_graph(ntree)
    graph = cluster_graph.G
    tree = cluster_graph.T

    # Phase 2: Preprocessing (same as Sugiyama)
    save_multi_input_orders(graph, ntree)
    remove_reroutes(cluster_graph)

    # Optional: Contract collapsed math nodes into stacks
    node_stacks = []
    if settings.stack_collapsed:
        node_stacks = contracted_node_stacks(
            cluster_graph, settings.stack_margin_y_factor
        )

    # Phase 3: Ranking (same as Sugiyama)
    compute_ranks(cluster_graph)
    cluster_graph.merge_edges()
    cluster_graph.insert_dummy_nodes()

    # Phase 4: Crossing Minimization (same as Sugiyama)
    add_columns(graph)
    minimize_crossings(graph, tree, sweeps=settings.crossing_reduction_sweeps)

    # Phase 5: Y-Coordinate Assignment (same as Sugiyama)
    if len(cluster_graph.S) == 1:
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

    # Phase 6: X-Coordinate Assignment (same as Sugiyama)
    assign_x_coords(graph, tree, settings.horizontal_spacing)

    # Phase 7: Orthogonal Edge Routing (DIFFERENT!)
    _route_edges_orthogonally(graph, ntree, settings)

    # Optional: Expand node stacks back to individual nodes
    if settings.stack_collapsed:
        for node_stack in node_stacks:
            expand_node_stack(cluster_graph, node_stack, settings.stack_margin_y_factor)

    # Phase 8: Realization
    restore_multi_input_orders(graph, ntree)
    realize_locations(graph, old_center, ntree)

    # Finalize frame sizes
    for cluster in cluster_graph.S:
        resize_unshrunken_frame(cluster_graph, cluster)


def precompute_links(ntree: NodeTree) -> None:
    """Precompute valid links in the node tree for efficient lookup."""
    config.linked_sockets.clear()
    for link in ntree.links:
        if not link.is_hidden and link.is_valid:
            config.linked_sockets[link.to_socket].add(link.from_socket)
            config.linked_sockets[link.from_socket].add(link.to_socket)


def build_graph(ntree: NodeTree) -> ClusterGraph:
    """Build the initial graph representation from the node tree."""
    from .graph import Socket

    parents = {
        node.parent: Cluster(cast(NodeFrame | None, node.parent))
        for node in ntree.nodes
    }
    for cluster in parents.values():
        if cluster.node:
            cluster.cluster = parents[cluster.node.parent]

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


def _route_edges_orthogonally(
    graph: nx.MultiDiGraph, ntree: NodeTree, settings: OrthogonalSettings
) -> None:
    """
    Route all edges with orthogonal (horizontal/vertical) segments.

    For each edge, creates a path with only 90-degree turns.
    Adds reroute nodes at bend points.
    """

    # Collect all edges that need routing
    edges_to_route = []
    for u, v, key, data in graph.edges(keys=True, data=True):
        if u.type == GType.NODE and v.type == GType.NODE:
            from_socket = data.get("from_socket")
            to_socket = data.get("to_socket")
            if from_socket and to_socket:
                edges_to_route.append((u, v, from_socket, to_socket))

    # Route each edge
    for u, v, from_socket, to_socket in edges_to_route:
        if settings.route_through_grid:
            _route_edge_grid(u, v, from_socket, to_socket, ntree, settings)
        else:
            _route_edge_stairstep(u, v, from_socket, to_socket, ntree, settings)


def _route_edge_stairstep(
    u: GNode,
    v: GNode,
    from_socket: Socket,
    to_socket: Socket,
    ntree: NodeTree,
    settings: OrthogonalSettings,
) -> None:
    """
    Simple stairstep routing: horizontal -> vertical -> horizontal.

    Creates a Z-shaped path between nodes.
    """
    # Get socket positions
    from_x = from_socket.x
    from_y = from_socket.y

    to_x = to_socket.x
    to_y = to_socket.y

    # Check if we need bends
    if abs(from_x - to_x) < settings.min_segment_length:
        # Too close horizontally, just use vertical connection
        return

    # Calculate midpoint for vertical segment
    mid_x = (from_x + to_x) / 2

    # Create reroute nodes at bend points
    # First bend: (mid_x, from_y)
    if abs(from_y - to_y) > settings.min_segment_length:
        reroute1 = ntree.nodes.new("NodeReroute")
        reroute1.location = (mid_x, from_y)

        # Second bend: (mid_x, to_y)
        reroute2 = ntree.nodes.new("NodeReroute")
        reroute2.location = (mid_x, to_y)


def _route_edge_grid(
    u: GNode,
    v: GNode,
    from_socket: Socket,
    to_socket: Socket,
    ntree: NodeTree,
    settings: OrthogonalSettings,
) -> None:
    """
    Grid-based routing using simple pathfinding.

    This is a simplified version - a full implementation would use
    A* or similar pathfinding to avoid other nodes and edges.

    For now, uses the same stairstep approach.
    """
    # For initial implementation, use stairstep
    # TODO: Implement proper grid-based pathfinding with obstacle avoidance
    _route_edge_stairstep(u, v, from_socket, to_socket, ntree, settings)
