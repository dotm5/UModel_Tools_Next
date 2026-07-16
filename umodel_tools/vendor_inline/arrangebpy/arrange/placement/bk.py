# SPDX-License-Identifier: GPL-2.0-or-later

# http://dx.doi.org/10.1007/3-540-45848-4_3
# http://dx.doi.org/10.1007/978-3-319-27261-0_12
# https://arxiv.org/abs/2008.01252

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Hashable, Iterator
from itertools import chain, pairwise
from math import ceil, floor, inf
from statistics import fmean
from typing import Any, cast

import networkx as nx

from ...settings import Direction, SocketAlignment
from ...utils import group_by
from ..graph import Cluster, GNode, GType


def marked_conflicts(
    G: nx.DiGraph[GNode],
    *,
    should_ensure_alignment: Callable[[GNode], Any],
) -> set[frozenset[GNode]]:
    """
    Find conflicting edges that cross each other in the layout.

    Args:
        G: The directed graph
        should_ensure_alignment: Function to determine if a node should be aligned

    Returns:
        Set of edge pairs that conflict with each other
    """
    columns = G.graph["columns"]
    marked_edges = set()

    for i, col in enumerate(columns[1:], 1):
        k_0 = 0
        idx = 0
        for l_1, u in enumerate(col):
            if should_ensure_alignment(u):
                upper_nbr = next(iter(G.pred[u]))
                k_1 = upper_nbr.col.index(upper_nbr)
            elif u == col[-1]:
                k_1 = len(columns[i - 1]) - 1
            else:
                continue

            while idx <= l_1:
                v = col[idx]
                idx += 1

                if should_ensure_alignment(v):
                    continue

                for pred in G.pred[v]:
                    k = pred.col.index(pred)
                    if k < k_0 or k > k_1:
                        marked_edges.add(frozenset((pred, v)))

            k_0 = k_1

    return marked_edges


def horizontal_alignment(
    G: nx.DiGraph[GNode],
    marked_edges: Collection[frozenset[GNode]],
    marked_nodes: Collection[GNode] = frozenset(),
) -> None:
    """
    Perform horizontal alignment of nodes to create straight edges.

    Args:
        G: The directed graph
        marked_edges: Edges that should not be aligned
        marked_nodes: Nodes that should not cross cluster boundaries when aligning
    """
    for col in G.graph["columns"]:
        prev_i = -1
        for v in col:
            predecessors = sorted(G.pred[v], key=lambda u: u.col.index(u))
            m = (len(predecessors) - 1) / 2
            for u in predecessors[floor(m) : ceil(m) + 1]:
                i = u.col.index(u)

                if v.aligned != v or {u, v} in marked_edges or prev_i >= i:
                    continue

                # Don't align across cluster boundaries if marked
                if u.cluster != v.cluster and {u, v} & marked_nodes:  # type: ignore
                    continue

                u.aligned = v
                v.root = u.root
                v.aligned = v.root
                prev_i = i


def iter_block(start: GNode) -> Iterator[GNode]:
    """Iterate through all nodes in an alignment block."""
    yield start
    w = start
    while (w := w.aligned) != start:
        yield w


def should_use_inner_shift(
    v: GNode,
    w: GNode,
    is_right: bool,
    socket_alignment: SocketAlignment,
) -> bool:
    """
    Determine if socket-level alignment should be used between two nodes.

    Args:
        v, w: The two nodes to align
        is_right: Whether we're processing right-to-left
        socket_alignment: The socket alignment mode

    Returns:
        True if socket-level alignment should be used
    """
    if v.is_reroute or w.is_reroute:
        return True

    if socket_alignment == "NONE":
        return False  # Only align node tops

    if socket_alignment == "FULL":
        return True  # Always align sockets

    # MODERATE: Smart decision based on node heights and clusters
    if v.cluster != w.cluster or GType.NODE in {v.type, w.type}:
        return True

    if not is_right:
        v, w = w, v

    # Don't use inner shift for tall nodes connected to short hidden nodes
    if v.height > w.height and not getattr(w.node, "hide", False):
        return False

    # Use inner shift if height difference is significant
    return abs(v.height - w.height) > fmean((v.height, w.height)) / 2


def inner_shift(
    G: nx.MultiDiGraph[GNode],
    is_right: bool,
    is_up: bool,
    socket_alignment: SocketAlignment,
) -> None:
    """
    Compute socket-level alignment offsets for better visual alignment.

    Args:
        G: The multi-digraph with socket information
        is_right: Whether we're processing right-to-left
        is_up: Whether we're processing bottom-to-top
        socket_alignment: The socket alignment mode
    """
    for root in {v.root for v in G}:
        for v, w in pairwise(iter_block(root)):
            if not should_use_inner_shift(v, w, is_right, socket_alignment):
                w.inner_shift = v.inner_shift
                continue

            # Calculate alignment based on socket positions
            inner_shifts = []
            for k in G[v][w]:
                from ..graph import FROM_SOCKET, TO_SOCKET

                p = G[v][w][k][FROM_SOCKET]
                q = G[v][w][k][TO_SOCKET]
                if p.owner != v:
                    p, q = q, p

                if is_up:
                    inner_shifts.append(v.inner_shift - p._offset_y + q._offset_y)
                else:
                    inner_shifts.append(v.inner_shift + p._offset_y - q._offset_y)

            w.inner_shift = fmean(inner_shifts) if inner_shifts else v.inner_shift


def precompute_cells(G: nx.DiGraph[Hashable]) -> None:
    """Precompute cell information for efficient block placement."""
    columns = G.graph["columns"]
    blocks = group_by(chain(*columns), key=lambda v: v.root)
    for block, root in blocks.items():
        indicies = [columns.index(v.col) for v in block]
        root.cells = (indicies, [v.height for v in block])


def min_separation(
    u: GNode, v: GNode, is_up: bool, vertical_spacing: float = 50.0
) -> float:
    if is_up:
        u, v = v, u

    assert u.root.cells
    indicies = u.root.cells[0]
    heights = [h for i, h in zip(*v.root.cells) if indicies[0] <= i <= indicies[-1]]
    return max(heights, default=0) + vertical_spacing


def place_block(v: GNode, is_up: bool, vertical_spacing: float = 50.0) -> None:
    """
    Place a block of aligned nodes, considering their heights and spacing.

    Args:
        v: The root node of the block
        is_up: Whether we're processing bottom-to-top
        vertical_spacing: Minimum vertical spacing between nodes
    """
    if cast(float | None, v.y) is not None:
        return

    v.y = 0
    initial = True
    for w in iter_block(v):
        i = w.col.index(w)

        if i == 0:
            continue

        n = w.col[i - 1]
        u = n.root
        place_block(u, is_up, vertical_spacing)

        if v.sink == v:
            v.sink = u.sink

        if v.sink == u.sink:
            # Use inner_shift if available, otherwise use regular separation
            delta_l = (
                n.height + vertical_spacing if is_up else w.height + vertical_spacing
            )
            s_b = u.y + n.inner_shift - w.inner_shift + delta_l
            v.y = s_b if initial else max(v.y, s_b)
            initial = False

    for w in iter_block(v):
        w.y = v.y
        w.sink = v.sink


def vertical_compaction(
    G: nx.DiGraph[GNode], is_up: bool, vertical_spacing: float = 50.0
) -> None:
    """
    Compact the layout vertically while respecting spacing constraints.

    Args:
        G: The directed graph
        is_up: Whether we're processing bottom-to-top
        vertical_spacing: Minimum vertical spacing between nodes
    """
    for v in G:
        if v.root == v:
            place_block(v, is_up, vertical_spacing)

    columns = G.graph["columns"]
    neighborings = defaultdict(set)

    for col in columns:
        for v, u in pairwise(reversed(col)):
            if u.sink != v.sink:
                neighborings[tuple(v.sink.col)].add((u, v))

    for col in columns:
        if col[0].sink.shift == inf:
            col[0].sink.shift = 0

        for u, v in neighborings[tuple(col)]:
            delta_l = (
                u.height + vertical_spacing if is_up else v.height + vertical_spacing
            )
            s_c = v.y + v.inner_shift - u.y - u.inner_shift - delta_l
            u.sink.shift = min(u.sink.shift, v.sink.shift + s_c)

    for v in G:
        v.y += v.sink.shift + v.inner_shift


def get_merged_lines(lines: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping line segments."""
    merged = []
    for line in sorted(lines, key=lambda ln: ln[0]):
        if merged and merged[-1][1] >= line[0]:
            a, b = merged[-1]
            merged[-1] = (a, max(b, line[1]))
        else:
            merged.append(line)

    return merged


def has_large_gaps_in_frame(
    cluster: Cluster,
    T: nx.DiGraph[Cluster | GNode],
    is_up: bool,
    vertical_spacing: float,
) -> bool:
    """
    Check if a frame has large gaps that should be closed.

    Args:
        cluster: The cluster/frame to check
        T: The cluster tree
        is_up: Whether we're processing bottom-to-top
        vertical_spacing: The vertical spacing being used

    Returns:
        True if the frame has gaps larger than the spacing
    """
    lines = []
    for v in T[cluster]:
        if v.type == GType.VERTICAL_BORDER:
            continue

        if v.type != GType.CLUSTER:
            line = (v.y, v.y + v.height) if is_up else (v.y - v.height, v.y)
        else:
            vertical_border_roots = {
                w.root for w in T[v] if w.type == GType.VERTICAL_BORDER
            }
            if not vertical_border_roots:
                continue
            w, z = sorted(vertical_border_roots, key=lambda w: w.y)
            line = (w.y, z.y + z.height) if is_up else (w.y - w.height, z.y)

        lines.append(line)

    merged = get_merged_lines(lines)
    return any(l2[0] - l1[1] > vertical_spacing for l1, l2 in pairwise(merged))


def get_marked_nodes(
    G: nx.DiGraph[GNode],
    T: nx.DiGraph[GNode | Cluster],
    old_marked_nodes: set[GNode],
    is_up: bool,
    vertical_spacing: float,
) -> set[GNode]:
    """
    Find nodes that should be marked to prevent crossing cluster boundaries.

    This is used for iterative refinement to fix large gaps in frames.

    Args:
        G: The directed graph
        T: The cluster tree
        old_marked_nodes: Previously marked nodes
        is_up: Whether we're processing bottom-to-top
        vertical_spacing: The vertical spacing being used

    Returns:
        Set of newly marked nodes
    """
    marked_nodes = set()
    for cluster in T:
        if cluster.type != GType.CLUSTER or cluster.nesting_level != 1:
            continue

        descendant_clusters = cast(
            set[Cluster],
            (nx.descendants(T, cluster) & (T.nodes - G.nodes)) | {cluster},
        )
        for nested_cluster in sorted(
            descendant_clusters,
            key=lambda c: cast(int, c.nesting_level),
            reverse=True,
        ):
            children = {v for v in T[nested_cluster] if v.type != GType.CLUSTER}

            if children <= old_marked_nodes:
                continue

            if not has_large_gaps_in_frame(nested_cluster, T, is_up, vertical_spacing):
                continue

            if children & old_marked_nodes:
                marked_nodes.update(children)
            else:
                marked_nodes.update(children)
                break

    return marked_nodes


def balance(layouts: list[list[float]]) -> None:
    """Balance multiple layouts by aligning them to minimize total range."""
    smallest_layout = min(layouts, key=lambda a: max(a) - min(a))

    movement = min(smallest_layout)
    for i in range(len(smallest_layout)):
        smallest_layout[i] -= movement

    for i, layout in enumerate(layouts):
        if layout == smallest_layout:
            continue

        func = min if i % 2 != 1 else max
        movement = func(smallest_layout) - func(layout)
        for j in range(len(layout)):
            layout[j] += movement


_DIRECTION_TO_IDX: dict[Direction, int] = {
    "RIGHT_DOWN": 0,
    "RIGHT_UP": 1,
    "LEFT_DOWN": 2,
    "LEFT_UP": 3,
}


def _has_geometry_socket(node: GNode) -> bool:
    """
    Check if a node has any geometry input or output sockets.

    Only nodes that process geometry (have geometry sockets) should be
    considered for top layer alignment. Nodes that only provide data
    (colors, attributes, etc.) should remain below the main flow.

    Args:
        node: The graph node to check

    Returns:
        True if the node has any geometry sockets, False otherwise
    """
    from ..graph import GType

    if node.type != GType.NODE or node.node is None:
        return False

    # Check all input and output sockets for geometry type
    for socket in node.node.inputs:
        if "Geometry" in socket.bl_idname:
            return True

    for socket in node.node.outputs:
        if "Geometry" in socket.bl_idname:
            return True

    return False


def _apply_top_layer_alignment(
    G: nx.MultiDiGraph[GNode], columns: list[list[GNode]]
) -> None:
    """
    Align the topmost geometry-processing node in each column at Y=0.

    This identifies the "top branch" of the main geometry processing pipeline
    by taking the node with maximum Y coordinate in each column that has
    geometry sockets. Nodes without geometry sockets (like color/attribute
    providers) are excluded from top layer alignment and remain below.

    Args:
        G: The graph with assigned Y coordinates
        columns: The columns (ranks) of nodes
    """
    if len(columns) < 2:
        return  # Need at least 2 columns

    # Filter out dummy/reroute nodes - only consider real nodes
    from ..graph import GType

    top_nodes = []

    # For each column, find the topmost node with geometry sockets
    for column in columns:
        # Only consider real nodes with geometry sockets
        geometry_nodes = [
            node
            for node in column
            if node.type == GType.NODE and _has_geometry_socket(node)
        ]
        if not geometry_nodes:
            continue

        # Find the node with maximum Y (topmost position)
        top_node_in_column = max(geometry_nodes, key=lambda n: n.y)
        top_nodes.append(top_node_in_column)

    if not top_nodes:
        return

    # Find the maximum Y among all top nodes - this is our target for Y=0
    max_top_y = max(node.y for node in top_nodes)

    # Align all top nodes to Y=0
    for node in top_nodes:
        node.y = 0

    # Push all other nodes down by max_top_y (so they're below 0)
    top_nodes_set = set(top_nodes)
    for node in G:
        if node.type == GType.NODE and node not in top_nodes_set:
            # Move this node down relative to the top
            node.y -= max_top_y


def bk_assign_y_coords(
    G: nx.MultiDiGraph[GNode],
    T: nx.DiGraph[GNode | Cluster] | None = None,
    *,
    vertical_spacing: float = 25.0,
    direction: Direction = "BALANCED",
    socket_alignment: SocketAlignment = "MODERATE",
    iterations: int = 1,
    align_top_layer: bool = False,
) -> None:
    """
    Assign y-coordinates using the Brandes-Köpf algorithm.

    This creates a hierarchical layout with minimal edge crossings and
    clean alignment between connected nodes.

    Args:
        G: The multi-digraph with nodes to layout
        T: Optional cluster tree for frame gap detection
        vertical_spacing: Minimum vertical spacing between nodes
        direction: Layout direction (BALANCED uses all 4, others use specific)
        socket_alignment: How to align sockets (NONE, MODERATE, FULL)
        iterations: Number of refinement iterations for frame gap detection
        align_top_layer: If True, align first and last rank at Y=0, push others below
    """
    columns = G.graph["columns"]
    for col in columns:
        col.reverse()

    # Determine which nodes need alignment
    def is_incident_to_inner_segment(v):
        return v.is_reroute and any(u.is_reroute for u in G.pred[v])

    def is_incident_to_vertical_border(v):
        return v.type == GType.VERTICAL_BORDER and G.pred[v]

    marked_edges = marked_conflicts(
        G, should_ensure_alignment=is_incident_to_inner_segment
    )
    marked_edges |= marked_conflicts(
        G, should_ensure_alignment=is_incident_to_vertical_border
    )

    layouts = []
    for dir_x in (-1, 1):
        G = nx.reverse_view(G)  # type: ignore
        columns.reverse()
        for dir_y in (-1, 1):
            i = 0
            marked_nodes: set[GNode] = set()
            is_up = dir_y == 1

            # Iterative refinement for better frame layouts
            while i < iterations:
                i += 1
                horizontal_alignment(G, marked_edges, marked_nodes)
                inner_shift(G, dir_x == 1, is_up, socket_alignment)
                vertical_compaction(G, is_up, vertical_spacing)

                # Check for large gaps in frames
                if T and iterations > 1:
                    new_marked_nodes = get_marked_nodes(
                        G, T, marked_nodes, is_up, vertical_spacing
                    )
                    if new_marked_nodes:
                        marked_nodes.update(new_marked_nodes)
                        for v in G:
                            v.reset()
                    else:
                        break
                else:
                    break

            layouts.append([v.y * -dir_y for v in G])

            for v in G:
                v.reset()

            for col in columns:
                col.reverse()

    for col in columns:
        col.reverse()

    # Apply direction preference
    if direction == "BALANCED":
        balance(layouts)
        for i, v in enumerate(G):
            values = [layout[i] for layout in layouts]
            values.sort()
            v.y = fmean(values[1:3])  # Average of middle two
    else:
        # Use specific direction
        idx = _DIRECTION_TO_IDX[direction]
        for v, y in zip(G, layouts[idx]):
            v.y = y

    # Apply top layer alignment if requested
    if align_top_layer:
        _apply_top_layer_alignment(G, columns)
