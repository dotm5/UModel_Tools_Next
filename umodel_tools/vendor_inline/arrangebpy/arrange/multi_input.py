# SPDX-License-Identifier: GPL-2.0-or-later

"""
Multi-Input Socket Handling

This module manages the preservation and restoration of multi-input socket
connection orders during the layout process.
"""

from __future__ import annotations

from itertools import chain

import networkx as nx
from bpy.types import NodeTree

from .. import config
from .graph import FROM_SOCKET, TO_SOCKET, GNode, socket_graph


def save_multi_input_orders(graph: nx.MultiDiGraph[GNode], ntree: NodeTree) -> None:
    """
    Save the current ordering of connections to multi-input sockets.
    """
    links = {(link.from_socket, link.to_socket): link for link in ntree.links}
    for from_node, to_node, edge_data in graph.edges.data():
        to_socket = edge_data[TO_SOCKET]

        if not to_socket.bpy.is_multi_input:
            continue

        if from_node.is_reroute:
            for current_node, prev_node in chain(
                [(to_node, from_node)], nx.bfs_edges(graph, from_node, reverse=True)
            ):
                if not prev_node.is_reroute:
                    break
            base_from_socket = graph.edges[prev_node, current_node, 0][FROM_SOCKET]
        else:
            base_from_socket = edge_data[FROM_SOCKET]

        link = links[(edge_data[FROM_SOCKET].bpy, to_socket.bpy)]
        config.multi_input_sort_ids[to_socket].append(
            (base_from_socket, link.multi_input_sort_id)
        )


def restore_multi_input_orders(graph: nx.MultiDiGraph[GNode], ntree: NodeTree) -> None:
    """
    Restore the original connection order for multi-input sockets.
    """
    links = ntree.links
    socket_g = socket_graph(graph)
    for socket, sort_ids in config.multi_input_sort_ids.items():
        multi_input = socket.bpy
        assert multi_input

        socket_links = {
            link.from_socket: link for link in links if link.to_socket == multi_input
        }

        if len(socket_links) != len(
            {link.multi_input_sort_id for link in socket_links.values()}
        ):
            for link in socket_links.values():
                links.remove(link)

            for output in socket_links:
                socket_links[output] = links.new(output, multi_input)

        socket_subgraph = socket_g.subgraph(
            {sort_item[0] for sort_item in sort_ids}
            | {socket}
            | {vertex for vertex in socket_g if vertex.owner.is_reroute}
        )
        seen_sockets = set()
        for base_from_socket, sort_id in sort_ids:
            matching_link = min(
                socket_links.values(),
                key=lambda link: abs(link.multi_input_sort_id - sort_id),
            )
            from_socket = next(
                source
                for source, target in nx.edge_dfs(socket_subgraph, base_from_socket)
                if target == socket and source not in seen_sockets
            )
            socket_links[from_socket.bpy].swap_multi_input_sort_id(matching_link)
            seen_sockets.add(from_socket)
