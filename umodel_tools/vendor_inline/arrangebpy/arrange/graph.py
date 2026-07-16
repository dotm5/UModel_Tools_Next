# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import cached_property
from itertools import chain, pairwise, product
from math import inf
from typing import TYPE_CHECKING, Any, Literal, Sequence, TypeGuard

import bpy
import networkx as nx
from bpy.types import Node, NodeFrame, NodeSocket

from .. import config
from ..utils import (
    REROUTE_DIM,
    abs_loc,
    dimensions,
    frame_padding,
    get_bottom,
    get_top,
    group_by,
)
from .structs import bNodeSocket

if TYPE_CHECKING:
    pass


class GType(Enum):
    NODE = auto()
    DUMMY = auto()
    CLUSTER = auto()
    HORIZONTAL_BORDER = auto()
    VERTICAL_BORDER = auto()


@dataclass(slots=True)
class CrossingReduction:
    socket_ranks: dict[Socket, float] = field(default_factory=dict)
    barycenter: float | None = None

    def reset(self) -> None:
        self.socket_ranks.clear()
        self.barycenter = None


_NonCluster = Literal[
    GType.NODE, GType.DUMMY, GType.HORIZONTAL_BORDER, GType.VERTICAL_BORDER
]


def is_real(v: GNode | Cluster) -> TypeGuard[_RealGNode]:
    return isinstance(v.node, Node)


def node_name(v: GNode) -> str:
    """Get the name of a node, or empty string if not a real node."""
    return getattr(v.node, "name", "")


class GNode:
    """Simplified graph node with essential attributes only."""

    def __init__(
        self,
        node: Node | None = None,
        cluster: Cluster | None = None,
        type: _NonCluster = GType.NODE,
        rank: int | None = None,
    ) -> None:
        # Core attributes
        self.node = node
        self.cluster = cluster
        self.type = type
        self.rank = rank or 0

        # Determine node characteristics
        real = isinstance(node, Node)
        self.is_reroute = type == GType.DUMMY or (
            real and node.bl_idname == "NodeReroute"
        )

        # Set dimensions
        if self.is_reroute:
            self.width = REROUTE_DIM.x
            self.height = REROUTE_DIM.y
        elif real:
            self.width = dimensions(node).x
            self.height = get_top(node) - get_bottom(node)
        else:
            self.width = 0
            self.height = 0

        # Initialize other attributes as needed
        self.po_num = 0
        self.lowest_po_num = 0
        self.col = None
        self.cr = CrossingReduction()
        self.x = 0.0
        self.y = 0.0

        # Layout attributes (initialized lazily)
        self.segment = None
        self.reset()

    def __hash__(self) -> int:
        return id(self)

    def reset(self) -> None:
        """Reset layout-specific attributes."""
        self.root = self
        self.aligned = self
        self.cells = None
        self.inner_shift = 0.0
        self.sink = self
        self.shift = inf
        self.y = None  # This will be set during layout

    def corrected_y(self) -> float:
        """Get y-coordinate corrected for Blender's coordinate system."""
        if self.y is None:
            return 0.0
        if not is_real(self):
            return self.y
        return self.y + (abs_loc(self.node).y - get_top(self.node))


class _RealGNode(GNode):
    node: Node  # type: ignore


@dataclass(slots=True)
class Cluster:
    node: NodeFrame | None
    cluster: Cluster | None = None
    nesting_level: int | None = None
    cr: CrossingReduction = field(default_factory=CrossingReduction)
    left: GNode = field(init=False)
    right: GNode = field(init=False)

    def __post_init__(self) -> None:
        self.left = GNode(None, self, GType.HORIZONTAL_BORDER)
        self.right = GNode(None, self, GType.HORIZONTAL_BORDER)

    def __hash__(self) -> int:
        return id(self)

    @property
    def type(self) -> Literal[GType.CLUSTER]:
        return GType.CLUSTER

    def label_height(self) -> float:
        frame = self.node
        if frame and frame.label:
            return -(frame_padding() / 2 - frame.label_size * 1.25)
        else:
            return 0


# -------------------------------------------------------------------


def get_nesting_relations(
    v: GNode | Cluster,
) -> Iterator[tuple[Cluster, GNode | Cluster]]:
    if c := v.cluster:
        yield (c, v)
        yield from get_nesting_relations(c)


def lowest_common_cluster(
    T: nx.DiGraph[GNode | Cluster],
    edges: Iterable[tuple[GNode, GNode, Any]],
) -> dict[Edge, Cluster]:
    pairs = {(u, v) for u, v, _ in edges if u.cluster != v.cluster}
    return dict(nx.tree_all_pairs_lowest_common_ancestor(T, pairs=pairs))


def add_dummy_edge(G: nx.DiGraph[GNode], u: GNode, v: GNode) -> None:
    G.add_edge(u, v, from_socket=Socket(u, 0, True), to_socket=Socket(v, 0, False))


def add_dummy_nodes_to_edge(
    G: nx.MultiDiGraph[GNode],
    edge: MultiEdge,
    dummy_nodes: Sequence[GNode],
) -> None:
    if not dummy_nodes:
        return

    for pair in pairwise(dummy_nodes):
        if pair not in G.edges:
            add_dummy_edge(G, *pair)

    u, v, _ = edge
    d = G.edges[edge]  # type: ignore

    w = dummy_nodes[0]
    if w not in G[u]:
        G.add_edge(u, w, from_socket=d[FROM_SOCKET], to_socket=Socket(w, 0, False))

    z = dummy_nodes[-1]
    G.add_edge(z, v, from_socket=Socket(z, 0, True), to_socket=d[TO_SOCKET])

    G.remove_edge(*edge)

    if not is_real(u) or not is_real(v):
        return

    links = u.node.id_data.links
    if d[TO_SOCKET].bpy.is_multi_input:
        target_link = (d[FROM_SOCKET].bpy, d[TO_SOCKET].bpy)
        links.remove(
            next(
                link_item
                for link_item in links
                if (link_item.from_socket, link_item.to_socket) == target_link
            )
        )


# https://api.semanticscholar.org/CorpusID:14932050
class ClusterGraph:
    G: nx.MultiDiGraph[GNode]
    T: nx.DiGraph[GNode | Cluster]
    S: set[Cluster]
    __slots__ = tuple(__annotations__)

    def __init__(self, G: nx.MultiDiGraph[GNode]) -> None:
        self.G = G
        self.T = nx.DiGraph(chain(*map(get_nesting_relations, G)))
        self.S = {v for v in self.T if v.type == GType.CLUSTER}

    def remove_nodes_from(self, nodes: Iterable[GNode]) -> None:
        for v in nodes:
            self.G.remove_node(v)
            self.T.remove_node(v)
            if v.col:
                v.col.remove(v)

            if not is_real(v):
                continue

            sockets = {*v.node.inputs, *v.node.outputs}

            for socket in sockets:
                config.linked_sockets.pop(socket, None)

            for val in config.linked_sockets.values():
                val -= sockets

            # Remove the node from the Blender node tree
            v.node.id_data.nodes.remove(v.node)

    def merge_edges(self) -> None:
        G = self.G
        T = self.T
        groups = group_by(G.edges(keys=True), key=lambda e: G.edges[e][FROM_SOCKET])
        edges: tuple[MultiEdge, ...]
        for edges, from_socket in groups.items():
            long_edges = [(u, v, k) for u, v, k in edges if v.rank - u.rank > 1]

            if len(long_edges) < 2:
                continue

            long_edges.sort(key=lambda e: e[1].rank)
            lca = lowest_common_cluster(T, long_edges)
            dummy_nodes = []
            for u, v, k in long_edges:
                if dummy_nodes and dummy_nodes[-1].rank == v.rank - 1:
                    w = dummy_nodes[-1]
                else:
                    assert u.cluster
                    c = lca.get((u, v), u.cluster)
                    w = GNode(None, c, GType.DUMMY, v.rank - 1)
                    T.add_edge(c, w)
                    dummy_nodes.append(w)

                add_dummy_nodes_to_edge(G, (u, v, k), [w])
                G.remove_edge(u, w)

            for pair in pairwise(dummy_nodes):
                add_dummy_edge(G, *pair)

            w = dummy_nodes[0]
            G.add_edge(
                u,
                dummy_nodes[0],
                from_socket=from_socket,
                to_socket=Socket(w, 0, False),
            )

    def insert_dummy_nodes(self) -> None:
        G = self.G
        T = self.T

        # -------------------------------------------------------------------

        long_edges = [
            (u, v, k) for u, v, k in G.edges(keys=True) if v.rank - u.rank > 1
        ]
        lca = lowest_common_cluster(T, long_edges)
        for u, v, k in long_edges:
            assert u.cluster
            c = lca.get((u, v), u.cluster)
            dummy_nodes = []
            for i in range(u.rank + 1, v.rank):
                w = GNode(None, c, GType.DUMMY, i)
                T.add_edge(c, w)
                dummy_nodes.append(w)

            add_dummy_nodes_to_edge(G, (u, v, k), dummy_nodes)

        # -------------------------------------------------------------------

        for c in self.S:
            if not c.node:
                continue

            ranks = sorted(
                {v.rank for v in nx.descendants(T, c) if v.type != GType.CLUSTER}
            )
            for i, j in pairwise(ranks):
                if j - i == 1:
                    continue

                u = None
                for k in range(i + 1, j):
                    v = GNode(None, c, GType.VERTICAL_BORDER, k)
                    T.add_edge(c, v)

                    if u:
                        add_dummy_edge(G, u, v)
                    else:
                        G.add_node(v)

                    u = v

    def add_vertical_border_nodes(self) -> None:
        T = self.T
        G = self.G
        columns = G.graph["columns"]
        for c in self.S:
            if not c.node:
                continue

            nodes = [v for v in nx.descendants(T, c) if v.type != GType.CLUSTER]
            lower_border_nodes = []
            upper_border_nodes = []
            for subcol in group_by(
                nodes, key=lambda v: columns.index(v.col), sort=True
            ):
                col = subcol[0].col
                indices = [col.index(v) for v in subcol]

                lower_v = GNode(None, c, GType.VERTICAL_BORDER)
                col.insert(max(indices) + 1, lower_v)
                lower_v.col = col
                T.add_edge(c, lower_v)
                lower_border_nodes.append(lower_v)

                upper_v = GNode(None, c, GType.VERTICAL_BORDER)
                upper_v.height += c.label_height()
                col.insert(min(indices), upper_v)
                upper_v.col = col
                T.add_edge(c, upper_v)
                upper_border_nodes.append(upper_v)

            G.add_nodes_from(lower_border_nodes + upper_border_nodes)
            for p in *pairwise(lower_border_nodes), *pairwise(upper_border_nodes):
                add_dummy_edge(G, *p)


# -------------------------------------------------------------------


def get_socket_y(socket: NodeSocket) -> float:
    if bpy.app.background:
        return get_top(socket.node)
    try:
        b_socket = bNodeSocket.from_address(socket.as_pointer())
        return b_socket.runtime.contents.location[1]
    except (AttributeError, ValueError):
        # Socket runtime locations are unavailable for node trees that have
        # never been drawn by a Node Editor, including background imports.
        # Falling back to the node top disables socket-specific offsets while
        # preserving the rest of the Sugiyama layout.
        return get_top(socket.node)


@dataclass(frozen=True)
class Socket:
    owner: GNode
    idx: int
    is_output: bool

    @property
    def bpy(self) -> NodeSocket | None:
        v = self.owner

        if not is_real(v):
            return None

        sockets = v.node.outputs if self.is_output else v.node.inputs
        return sockets[self.idx]

    @property
    def x(self) -> float:
        v = self.owner
        return v.x + v.width if self.is_output else v.x

    @cached_property
    def _offset_y(self) -> float:
        v = self.owner

        if v.is_reroute or not is_real(v):
            return 0

        assert self.bpy
        return get_socket_y(self.bpy) - get_top(v.node)

    @property
    def y(self) -> float:
        return self.owner.y + self._offset_y


Edge = tuple[GNode, GNode]
MultiEdge = tuple[GNode, GNode, int]

FROM_SOCKET = "from_socket"
TO_SOCKET = "to_socket"


def socket_graph(G: nx.MultiDiGraph[GNode]) -> nx.DiGraph[Socket]:
    H = nx.DiGraph()
    H.add_edges_from([(d[FROM_SOCKET], d[TO_SOCKET]) for *_, d in G.edges.data()])
    for sockets in group_by(H, key=lambda s: s.owner):
        outputs = {s for s in sockets if s.is_output}
        H.add_edges_from(product(set(sockets) - outputs, outputs))

    return H
