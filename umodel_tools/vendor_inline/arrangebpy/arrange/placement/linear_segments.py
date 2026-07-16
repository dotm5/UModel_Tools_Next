# SPDX-License-Identifier: GPL-2.0-or-later

# https://link.springer.com/chapter/10.1007/BFb0021828
# https://link.springer.com/chapter/10.1007/3-540-58950-3_371

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from functools import cache
from itertools import pairwise
from math import inf
from typing import TYPE_CHECKING

import networkx as nx

from ..graph import FROM_SOCKET, TO_SOCKET, Cluster, GNode, GType, Socket

if TYPE_CHECKING:
    from ..sugiyama import ClusterGraph


@dataclass(eq=False, slots=True)
class Segment:
    nodes: list[GNode]
    deflection: float = 0
    weight: int = 0
    ref_segment: Segment | None = None

    def __hash__(self) -> int:
        return id(self)

    def __iter__(self) -> Iterator[GNode]:
        return iter(self.nodes)

    def split(self, v: GNode) -> Segment:
        nodes = self.nodes
        new_segment = Segment(nodes[nodes.index(v) :])
        for w in new_segment:
            w.segment = new_segment
            nodes.remove(w)

        return new_segment

    def region(self) -> Segment:
        segment = self
        while s := segment.ref_segment:
            segment = s

        return segment


class _Mode(Enum):
    FORW_PENDULUM = auto()
    BACKW_PENDULUM = auto()
    RUBBER = auto()


def reroute_succ(G: nx.DiGraph[GNode], u: GNode) -> GNode | None:
    if not u.is_reroute:
        return None

    reroute_successors = [v for v in G[u] if v.is_reroute]
    return reroute_successors[0] if len(reroute_successors) == 1 else None


def linear_succ(G: nx.DiGraph[GNode], u: GNode) -> GNode | None:
    return next(iter(G[u]), None) if G.out_degree[u] < 2 else reroute_succ(G, u)


@cache
def complex_clusters(CG: ClusterGraph) -> set[Cluster]:
    G = CG.G
    T = CG.T
    clusters = set()
    for c in CG.S:
        if any(
            G.in_degree[v] > 1 or G.out_degree[v] > 1
            for v in T[c]
            if v.type != GType.CLUSTER
        ):
            clusters.add(c)

    return clusters


def clusters_are_incompatible(CG: ClusterGraph, c1: Cluster, c2: Cluster) -> bool:
    if c1 == c2:
        return False

    cu, cv = sorted((c1, c2), key=lambda c: c.nesting_level)  # type: ignore
    if nx.has_path(CG.T, cu, cv):
        return cv in complex_clusters(CG)

    return bool({c1, c2} & complex_clusters(CG))


def get_linear_segments(CG: ClusterGraph) -> list[Segment]:
    G = CG.G

    def linear_succ_iter(u: GNode) -> Iterator[GNode]:
        v = linear_succ(G, u)

        if not v or G.in_degree[v] > 1:
            return

        if G.out_degree[u] < 2 or reroute_succ(G, u):
            yield v

    linear_segments = []
    seen = set()
    for col in G.graph["columns"]:
        for u in col:
            if u in seen:
                continue

            nodes = [u]
            if linear_succ(G, u):
                for _, v in nx.generic_bfs_edges(G, u, linear_succ_iter):  # type: ignore
                    if clusters_are_incompatible(CG, u.cluster, v.cluster):  # type: ignore
                        break
                    nodes.append(v)

            linear_segments.append(Segment(nodes))
            seen.update(nodes)

    return linear_segments


def prevent_cycles(
    linear_segments: list[Segment], columns: Sequence[Sequence[GNode]]
) -> None:
    for col1, col2 in pairwise(reversed(columns)):
        for i, v in enumerate(col1):
            segments2 = [w.segment for w in col2]

            if v.segment not in segments2:
                continue

            segments1 = [w.segment for w in col1]
            below = set(segments2[segments2.index(v.segment) + 1 :])
            cycle_segments = [s for s in segments1[:i] if s in below]

            if not cycle_segments:
                continue

            if v.type == GType.VERTICAL_BORDER:
                for s in cycle_segments:
                    linear_segments.append(s.split(col1[segments1.index(s)]))
            else:
                linear_segments.append(v.segment.split(v))


def sort_linear_segments(
    linear_segments: list[Segment],
    columns: Sequence[Sequence[GNode]],
) -> None:
    for segment in linear_segments:
        for v in segment:
            v.segment = segment

    prevent_cycles(linear_segments, columns)

    SG = nx.DiGraph()
    SG.add_nodes_from(linear_segments)
    for col in columns:
        SG.add_edges_from([(v.segment, w.segment) for v, w in pairwise(col)])

    indicies = {v: i for i, v in enumerate(nx.topological_sort(SG))}
    linear_segments.sort(key=lambda v: indicies[v])


def create_unbalanced_placement(
    linear_segments: Sequence[Segment], vertical_spacing: float = 50.0
) -> None:
    heights = {s: max([v.height for v in s]) for s in linear_segments}
    for segment in linear_segments:
        # Find the bottom of the immediately preceding segment in the same column
        preceding_bottom = None
        for v in segment:
            # Look for already-placed nodes in the same column that are above this segment
            col_nodes_above = [
                w for w in v.col if w.y is not None and w.segment != segment
            ]
            if col_nodes_above:
                # Find the lowest (most negative) Y position of nodes above
                preceding_bottom = min(
                    w.y - heights[w.segment] for w in col_nodes_above
                )
                break

        # Position this segment below the preceding one with proper spacing
        if preceding_bottom is not None:
            lowest_y = preceding_bottom - vertical_spacing
        else:
            lowest_y = 0  # First segment starts at 0

        for v in segment:
            v.y = lowest_y


_DEFLECTION_DAMPENING = 0.1
_ITERS = 10
_PENDULUM_ITERS = 4
_FINAL_ITERS = 3
_THRESH_FAC = 20


@cache
def get_out_edges(G: nx.DiGraph[GNode], v: GNode) -> list[tuple[Socket, Socket]]:
    return [  #
        (d[FROM_SOCKET], d[TO_SOCKET])
        for _, w, d in G.out_edges.data(nbunch=v)
        if w.segment != v.segment
    ]


@cache
def get_in_edges(G: nx.DiGraph[GNode], v: GNode) -> list[tuple[Socket, Socket]]:
    return [  #
        (d[FROM_SOCKET], d[TO_SOCKET])
        for u, _, d in G.in_edges.data(nbunch=v)
        if u.segment != v.segment
    ]


def calc_deflection(G: nx.DiGraph[GNode], segment: Segment, mode: _Mode) -> None:
    segment_deflection = 0
    node_weight_sum = 0
    for v in segment:
        node_deflection = 0
        edge_weight_sum = 0

        if mode != _Mode.FORW_PENDULUM:
            for from_socket, to_socket in get_out_edges(G, v):
                node_deflection += (
                    to_socket.owner.y + to_socket.y - (v.y + from_socket.y)
                )
                edge_weight_sum += 1

        if mode != _Mode.BACKW_PENDULUM:
            for from_socket, to_socket in get_in_edges(G, v):
                node_deflection += (
                    from_socket.owner.y + from_socket.y - (v.y + to_socket.y)
                )
                edge_weight_sum += 1

        if edge_weight_sum > 0:
            segment_deflection += node_deflection / edge_weight_sum
            node_weight_sum += 1

    segment.deflection = (
        _DEFLECTION_DAMPENING * segment_deflection / node_weight_sum
        if node_weight_sum > 0
        else 0
    )
    segment.weight = node_weight_sum


def merge_regions(
    columns: Sequence[Sequence[GNode]], vertical_spacing: float = 50.0
) -> None:
    while True:
        changed = False
        for col in columns:
            prev_region = col[0].segment.region()
            for v, w in pairwise(col):
                region1 = prev_region
                region2 = w.segment.region()
                prev_region = region2

                weight_sum = region1.weight + region2.weight

                if weight_sum == 0 or region1 == region2:
                    continue

                assert v.cluster and w.cluster
                if (
                    (
                        not v.cluster.node
                        or not w.cluster.node
                        or GType.VERTICAL_BORDER in {v.type, w.type}
                    )
                    and v.y + region1.deflection - v.height - vertical_spacing
                    >= w.y + region2.deflection
                ):
                    continue

                region2.deflection = (
                    region2.weight * region2.deflection
                    + region1.weight * region1.deflection
                ) / weight_sum
                region2.weight = weight_sum
                region1.ref_segment = region2

                changed = True

        if not changed:
            break


def balance_placement(
    G: nx.DiGraph[GNode],
    linear_segments: Sequence[Segment],
    vertical_spacing: float = 50.0,
) -> None:
    pendulum_iters = _PENDULUM_ITERS
    final_iters = _FINAL_ITERS

    ready = False
    mode = _Mode.FORW_PENDULUM
    prev_total_deflection = inf
    while True:
        total_deflection = 0
        for segment in linear_segments:
            segment.ref_segment = None
            calc_deflection(G, segment, mode)
            total_deflection += abs(segment.deflection)

        merge_regions(G.graph["columns"], vertical_spacing)

        for segment in linear_segments:
            deflection = segment.region().deflection
            for v in segment:
                v.y += deflection

        if mode in {_Mode.FORW_PENDULUM, _Mode.BACKW_PENDULUM}:
            pendulum_iters -= 1
            if pendulum_iters <= 0 and (
                total_deflection < prev_total_deflection or -pendulum_iters > _ITERS
            ):
                mode = _Mode.RUBBER
                prev_total_deflection = inf
            else:
                mode = (
                    _Mode.BACKW_PENDULUM
                    if mode == _Mode.FORW_PENDULUM
                    else _Mode.FORW_PENDULUM
                )
                prev_total_deflection = total_deflection
        else:
            ready = (
                total_deflection >= prev_total_deflection
                or prev_total_deflection - total_deflection < _THRESH_FAC / _ITERS
            )
            prev_total_deflection = total_deflection
            if ready:
                final_iters -= 1

        if ready and final_iters > 0:
            break


def linear_segments_assign_y_coords(
    CG: ClusterGraph,
    *,
    vertical_spacing: float = 25.0,
    direction: str = "BALANCED",
    socket_alignment: str = "MODERATE",
    iterations: int = 1,
    align_top_layer: bool = False,
) -> None:
    """
    Assign y-coordinates using linear segments for complex frame hierarchies.

    Args:
        CG: The cluster graph
        vertical_spacing: Vertical spacing between nodes
        direction: Layout direction (currently uses BALANCED)
        socket_alignment: Socket alignment mode (currently simplified)
        iterations: Iteration count (reserved for future use)
        align_top_layer: If True, align first and last rank at Y=0

    Note: This is a simplified version. Full socket alignment and direction
    support would require more complex implementation.
    """
    linear_segments = get_linear_segments(CG)
    sort_linear_segments(linear_segments, CG.G.graph["columns"])

    create_unbalanced_placement(linear_segments, vertical_spacing)

    # Apply top layer alignment if requested
    if align_top_layer:
        from .bk import _apply_top_layer_alignment

        _apply_top_layer_alignment(CG.G, CG.G.graph["columns"])
    balance_placement(CG.G, linear_segments, vertical_spacing)
