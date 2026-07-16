# SPDX-License-Identifier: GPL-2.0-or-later

"""
Node Stacking

This module handles the stacking of collapsed math nodes on top of each other
to create more compact layouts for shader node trees.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from math import inf
from typing import TypeVar, cast

import networkx as nx

from ..utils import get_top
from .graph import (
    FROM_SOCKET,
    TO_SOCKET,
    Cluster,
    ClusterGraph,
    GNode,
    GType,
    MultiEdge,
    Socket,
    get_socket_y,
    is_real,
    node_name,
)


@dataclass(slots=True)
class NodeStack:
    """Represents a stack of collapsed math nodes."""

    rep_node: GNode
    """Representative node that replaces the stack in the graph"""

    path: list[GNode]
    """List of nodes in the stack, in topological order"""

    stack_sockets_to_originals: dict[Socket, Socket] = field(default_factory=dict)
    """Mapping from stack sockets to original node sockets"""


T = TypeVar("T", bound=Hashable)


# Adapted from NetworkX, to make it deterministic:
# https://github.com/networkx/networkx/blob/36e8a1ee85ca0ab4195a486451ca7d72153e2e00/networkx/algorithms/bipartite/matching.py#L59
def deterministic_hopcroft_karp_matching(
    G: nx.Graph[T], top_nodes: Iterable[T]
) -> dict[T, T]:
    """
    Compute maximum cardinality matching using Hopcroft-Karp algorithm.

    This is a deterministic version that produces consistent results.
    """

    def bfs() -> bool:
        for u in pair_U:
            if pair_U[u] is None:
                dist[u] = 0
                Q.append(u)
            else:
                dist[u] = inf

        dist[None] = inf
        while Q:
            u = Q.popleft()
            if dist[u] < dist[None]:
                for v in G[u]:
                    if dist[pair_V[v]] == inf:
                        dist[pair_V[v]] = dist[u] + 1
                        Q.append(pair_V[v])

        return dist[None] != inf

    def dfs(u: T | None) -> bool:
        if u is None:
            return True

        for v in G[u]:
            if dist[pair_V[v]] == dist[u] + 1 and dfs(pair_V[v]):
                pair_V[v] = u
                pair_U[u] = v
                return True

        dist[u] = inf
        return False

    pair_U: dict[T, T | None] = {v: None for v in top_nodes}
    pair_V: dict[T, T | None] = {v: None for v in G if v not in pair_U}
    dist = {}
    Q = deque()

    while bfs():
        for u, v in pair_U.items():
            if v is None:
                dfs(u)

    return {k: v for k, v in (pair_U | pair_V).items() if v is not None}


def max_linear_branching(G: nx.MultiDiGraph[GNode]) -> nx.MultiDiGraph[GNode]:
    """
    Compute maximum linear branching of a graph.

    Returns a subgraph where each node has at most one incoming and one outgoing edge.
    """
    # To make results deterministic
    nodes = sorted(G, key=node_name)
    edges = sorted(G.edges(keys=False), key=lambda e: node_name(e[0]) + node_name(e[1]))

    out_nodes = [(v, "out") for v in nodes]
    in_nodes = [(v, "in") for v in nodes]

    B: nx.Graph[tuple[GNode, str]] = nx.Graph()
    B.add_nodes_from(out_nodes, bipartite=0)
    B.add_nodes_from(in_nodes, bipartite=1)
    for u, v in edges:
        B.add_edge((u, "out"), (v, "in"))

    matching = deterministic_hopcroft_karp_matching(B, out_nodes)
    H = nx.MultiDiGraph()
    H.add_nodes_from(nodes)
    for u_out in out_nodes:
        if u_out in matching:
            H.add_edge(u_out[0], matching[u_out][0])

    return H


_WEIGHT = "weight"


# http://dx.doi.org/10.1016/S0020-0190(02)00491-X
def minimum_feedback_arc_set(G: nx.MultiDiGraph[GNode]) -> set[MultiEdge]:
    """
    Compute minimum feedback arc set to make graph acyclic.

    Returns the minimum set of edges whose removal makes the graph acyclic.
    """
    G_ = G.copy()
    while not nx.is_directed_acyclic_graph(G_):
        C = tuple((G_.subgraph(next(nx.simple_cycles(G_))).edges))
        min_weight = min([G.edges[e][_WEIGHT] for e in C])
        for u, v, k in C:
            d = G.edges[u, v, k]
            d[_WEIGHT] -= min_weight
            if d[_WEIGHT] == 0:
                G_.remove_edge(u, v, k)

    for u, v, k in G.edges:
        if (u, v, k) in G_.edges:
            continue

        G_.add_edge(u, v, k)
        if not nx.is_directed_acyclic_graph(G_):
            G_.remove_edge(u, v, k)

    return set(G.edges - G_.edges)


def edges_preventing_acyclic_contraction(
    G: nx.MultiDiGraph[GNode],
    K: nx.MultiDiGraph[GNode],
) -> list[tuple[GNode, GNode]]:
    """
    Find edges that must be reversed to allow acyclic contraction.

    Returns edges that need to be reversed for the graph to remain acyclic
    after contracting nodes in K.
    """
    G_ = G.copy()
    for u, v, k, d in tuple(G_.edges(data=True, keys=True)):
        if (u, v, k) in K.edges:
            d[_WEIGHT] = 1
            G_.remove_edge(u, v, k)
            G_.add_edge(v, u, k, **d)
        else:
            d[_WEIGHT] = inf

    F = minimum_feedback_arc_set(G_)
    return [(v, u) for u, v, _ in F]


def opposite(v: GNode, e: tuple[GNode, GNode] | tuple[GNode, ...]) -> GNode:
    """Get the opposite node in an edge."""
    return e[0] if v != e[0] else e[1]


def relabel_sockets(
    edges: nx.classes.reportviews.OutMultiEdgeView[GNode],
    v: GNode,
    node_stack: NodeStack,
    y: float,
) -> None:
    """
    Relabel sockets for a node being added to a stack.

    Creates new sockets on the representative node and tracks the mapping
    to original sockets.
    """
    assert is_real(v)
    external_edges = [
        (u, w, d)
        for u, w, d in edges(v, data=True)
        if opposite(v, (u, w)) not in node_stack.path
    ]

    if not external_edges:
        return

    is_output = external_edges[0][0] == v
    attr = FROM_SOCKET if is_output else TO_SOCKET
    external_edges.sort(key=lambda e: e[2][attr].idx)

    for *_, d in external_edges:
        sockets = node_stack.stack_sockets_to_originals
        i = max([s.idx for s in sockets], default=-1) + 1
        socket = Socket(
            node_stack.rep_node,
            i,
            is_output,
            get_socket_y(d[attr].bpy) - get_top(v.node) - y,
        )
        sockets[socket] = d[attr]
        d[attr] = socket


def contracted_node_stacks(
    CG: ClusterGraph, stack_margin_y_factor: float = 0.5
) -> list[NodeStack]:
    """
    Identify and contract collapsed math nodes into stacks.

    Args:
        CG: Cluster graph containing the nodes
        stack_margin_y_factor: Vertical spacing factor between stacked nodes (0-1)

    Returns:
        List of NodeStack objects representing the contracted stacks
    """
    G = CG.G
    T = CG.T

    # Find collapsed math nodes
    collapsed_math_nodes = [
        v
        for v in G
        if is_real(v)
        and v.node.hide
        and v.node.bl_idname in {"ShaderNodeMath", "ShaderNodeVectorMath"}
    ]
    H: nx.MultiDiGraph[GNode] = nx.MultiDiGraph(G.subgraph(collapsed_math_nodes))

    # Remove edges between different clusters
    H.remove_edges_from([(u, v, k) for u, v, k in H.edges if u.cluster != v.cluster])

    # Remove multi-edges (keep only simple connections)
    for u, a in H.adj.copy().items():
        for v, d in a.items():
            if len(d) > 1:
                H.remove_edges_from([(u, v, k) for k in d])  # type: ignore

    # Compute maximum linear branching for each component
    for c in nx.weakly_connected_components(H):
        H_c = H.subgraph(c)
        B = max_linear_branching(H_c)  # type: ignore
        H.remove_edges_from(H_c.edges - B.edges)

    # Remove edges that would prevent acyclic contraction
    for c in nx.weakly_connected_components(H):
        H.remove_edges_from(
            edges_preventing_acyclic_contraction(G, H.subgraph(c))  # type: ignore
        )

    H.remove_edges_from(edges_preventing_acyclic_contraction(G, H))

    # Create node stacks from components
    order = {v: i for i, v in enumerate(nx.topological_sort(H))}
    node_stacks = []

    for c in nx.weakly_connected_components(H):
        if len(c) == 1:
            continue

        # Create representative node for the stack
        rep_node = GNode(type=GType.NODE)
        path: list[GNode] = sorted(c, key=order.get)  # type: ignore
        node_stack = NodeStack(rep_node, path)

        # Calculate total height and width
        y = 0
        margin_y = stack_margin_y_factor * 25.0  # Base vertical spacing
        for v in path:
            relabel_sockets(G.in_edges, v, node_stack, y)
            relabel_sockets(G.out_edges, v, node_stack, y)
            y += v.height + margin_y

        rep_node.height = y
        rep_node.width = max([v.width for v in path])

        cluster = cast(Cluster, path[0].cluster)
        rep_node.cluster = cluster
        T.add_edge(cluster, rep_node)

        # Replace stack nodes with representative
        for u, v, k, d in (
            *G.in_edges(path, keys=True, data=True),
            *G.out_edges(path, keys=True, data=True),
        ):
            if u in path and v in path:
                continue

            G.remove_edge(u, v, k)
            e_ = (rep_node, v) if u in path else (u, rep_node)
            G.add_edge(*e_, **d)

        G.remove_nodes_from(path)
        T.remove_nodes_from(path)

        node_stacks.append(node_stack)

    assert nx.is_directed_acyclic_graph(G)

    return node_stacks


def expand_node_stack(
    CG: ClusterGraph, node_stack: NodeStack, stack_margin_y_factor: float = 0.5
) -> None:
    """
    Expand a contracted node stack back into individual nodes.

    Args:
        CG: Cluster graph
        node_stack: The stack to expand
        stack_margin_y_factor: Vertical spacing factor (same as used in contraction)
    """
    G = CG.G
    rep_node = node_stack.rep_node
    path = node_stack.path

    # Restore original socket connections
    for stack_socket, original_socket in node_stack.stack_sockets_to_originals.items():
        if stack_socket.is_output:
            for _, v, k, d in tuple(G.out_edges(rep_node, data=True, keys=True)):
                if d[FROM_SOCKET] != stack_socket:
                    continue

                G.remove_edge(rep_node, v, k)
                G.add_edge(
                    original_socket.owner,
                    v,
                    from_socket=original_socket,
                    to_socket=d[TO_SOCKET],
                )
        else:
            for u, _, k, d in G.in_edges(rep_node, data=True, keys=True):
                if d[TO_SOCKET] == stack_socket:
                    break
            G.remove_edge(u, rep_node, k)
            G.add_edge(
                u,
                original_socket.owner,
                from_socket=d[FROM_SOCKET],
                to_socket=original_socket,
            )

    # Add nodes back to graph
    G.add_nodes_from(path)

    # Insert nodes into column
    i = rep_node.col.index(rep_node)
    rep_node.col[i:i] = path

    # Set positions
    margin_y = stack_margin_y_factor * 25.0
    y = rep_node.y
    for v in path:
        CG.T.add_edge(cast(Cluster, rep_node.cluster), v)
        v.x = rep_node.x - (v.width - rep_node.width) / 2
        v.y = y
        y -= v.height + margin_y

    # Remove representative node
    CG.remove_nodes_from([rep_node])
