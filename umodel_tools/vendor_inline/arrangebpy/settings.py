# SPDX-License-Identifier: GPL-2.0-or-later

"""
Layout Settings

This module defines settings dataclasses for configuring different layout algorithms.
All settings are passed as function parameters rather than using global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["LEFT_DOWN", "RIGHT_DOWN", "LEFT_UP", "RIGHT_UP", "BALANCED"]
SocketAlignment = Literal["NONE", "MODERATE", "FULL"]
GridDirection = Literal["HORIZONTAL", "VERTICAL"]
GridGrouping = Literal["NONE", "TYPE", "CLUSTER"]


@dataclass
class LayoutSettings:
    """
    Configuration settings for the Sugiyama layout algorithm.

    All parameters have sensible defaults matching the original node-arrange add-on.
    """

    # Spacing
    horizontal_spacing: float = 50.0
    """Horizontal spacing between node columns"""

    vertical_spacing: float = 25.0
    """Vertical spacing between nodes in the same column"""

    # Algorithm behavior
    direction: Direction = "BALANCED"
    """
    Layout direction:
    - "BALANCED": Combine four extreme layouts, evening out directional tendencies
    - "LEFT_DOWN", "RIGHT_DOWN", "LEFT_UP", "RIGHT_UP": Use specific direction
    """

    socket_alignment: SocketAlignment = "MODERATE"
    """
    Socket alignment mode:
    - "NONE": Only try to align the tops of nodes
    - "MODERATE": Align sockets or node tops depending on node heights (default)
    - "FULL": Always try to align sockets with other sockets
    """

    iterations: int = 20
    """
    Number of iterations for BK algorithm refinement (for frame gap detection).
    Higher values may produce better layouts for complex frame hierarchies.
    Set to 1 for single-pass (faster but less refined).
    """

    crossing_reduction_sweeps: int = 24
    """
    Number of median heuristic sweeps for crossing reduction.
    More sweeps reduce crossings but take longer.
    """

    # Reroute handling
    add_reroutes: bool = True
    """If True, add reroute nodes to clean up edge routing"""

    keep_reroutes_outside_frames: bool = False
    """
    If True, always attach reroutes to the lowest common frame of the nodes they connect.
    If False, allow reroutes to be placed inside frames when beneficial.
    """

    # Node stacking
    stack_collapsed: bool = False
    """
    If True, stack collapsed math and vector math nodes on top of each other.
    This creates more compact layouts for shader node trees.
    """

    stack_margin_y_factor: float = 0.5
    """
    Factor for vertical spacing between stacked nodes (0.0 to 1.0).
    Lower values create tighter stacks.
    Only used when stack_collapsed is True.
    """

    align_top_layer: bool = False
    """
    If True, align the first and last rank (typically input/output nodes)
    at Y=0, with all intermediate ranks pushed below.
    Creates a clean "flat top" layout where sources and sinks are aligned.
    """

    def __post_init__(self):
        """Validate settings after initialization."""
        if self.iterations < 1:
            raise ValueError("iterations must be at least 1")
        if self.crossing_reduction_sweeps < 1:
            raise ValueError("crossing_reduction_sweeps must be at least 1")
        if not 0 <= self.stack_margin_y_factor <= 1:
            raise ValueError("stack_margin_y_factor must be between 0 and 1")


@dataclass
class TopologicalSettings:
    """
    Configuration settings for simple topological (layered) layout.

    This is a simplified, faster alternative to Sugiyama that doesn't perform
    crossing reduction. Good for quick layouts or very large graphs.
    """

    horizontal_spacing: float = 50.0
    """Horizontal spacing between node columns"""

    vertical_spacing: float = 25.0
    """Vertical spacing between nodes in the same column"""

    sort_by_degree: bool = True
    """If True, sort nodes in each column by their degree (fewer connections at top)"""

    center_nodes: bool = True
    """If True, center nodes vertically within their column"""

    flatten: bool = False
    """
    If True, force all nodes to Y=0 for a perfectly flat horizontal layout.
    Useful for simple linear chains where you want a single row.
    """


@dataclass
class OrthogonalSettings:
    """
    Configuration settings for orthogonal edge routing with Sugiyama layout.

    Uses the same hierarchical layout as Sugiyama, but routes all edges
    with only horizontal and vertical segments (no diagonal lines).
    """

    # Inherit most settings from LayoutSettings
    horizontal_spacing: float = 60.0
    """Horizontal spacing between node columns (needs more space for routing)"""

    vertical_spacing: float = 30.0
    """Vertical spacing between nodes"""

    direction: Direction = "BALANCED"
    """Layout direction (same as Sugiyama)"""

    socket_alignment: SocketAlignment = "MODERATE"
    """Socket alignment mode (same as Sugiyama)"""

    iterations: int = 20
    """BK algorithm refinement iterations"""

    crossing_reduction_sweeps: int = 24
    """Crossing reduction sweeps"""

    stack_collapsed: bool = False
    """Stack collapsed math nodes"""

    stack_margin_y_factor: float = 0.5
    """Vertical spacing factor for stacked nodes"""

    align_top_layer: bool = False
    """If True, align first and last rank at Y=0 (same as LayoutSettings)"""

    # Orthogonal-specific settings
    min_segment_length: float = 20.0
    """Minimum length for edge segments"""

    route_through_grid: bool = True
    """If True, use grid-based routing; if False, use simple stairstep routing"""

    def __post_init__(self):
        """Validate settings after initialization."""
        if self.iterations < 1:
            raise ValueError("iterations must be at least 1")
        if self.crossing_reduction_sweeps < 1:
            raise ValueError("crossing_reduction_sweeps must be at least 1")
        if not 0 <= self.stack_margin_y_factor <= 1:
            raise ValueError("stack_margin_y_factor must be between 0 and 1")
        if self.min_segment_length < 0:
            raise ValueError("min_segment_length must be non-negative")


@dataclass
class GridSettings:
    """
    Configuration settings for grid-based layout.

    Arranges nodes in a regular grid pattern, optionally grouping by type or cluster.
    Good for organizing collections of similar nodes or creating inventory-style layouts.
    """

    cell_width: float = 200.0
    """Width of each grid cell"""

    cell_height: float = 100.0
    """Height of each grid cell"""

    columns: int | None = None
    """
    Number of columns in the grid.
    If None, automatically determined based on number of nodes (roughly square).
    """

    direction: GridDirection = "HORIZONTAL"
    """
    Grid fill direction:
    - "HORIZONTAL": Fill left-to-right, then top-to-bottom
    - "VERTICAL": Fill top-to-bottom, then left-to-right
    """

    grouping: GridGrouping = "NONE"
    """
    How to group nodes:
    - "NONE": No grouping, just place in order
    - "TYPE": Group by node type (bl_idname)
    - "CLUSTER": Group by frame/cluster membership
    """

    center_in_cells: bool = True
    """If True, center nodes within their grid cells"""

    compact: bool = False
    """
    If True, use compact spacing (just enough for nodes).
    If False, use fixed cell_width/cell_height.
    """

    def __post_init__(self):
        """Validate settings after initialization."""
        if self.cell_width <= 0:
            raise ValueError("cell_width must be positive")
        if self.cell_height <= 0:
            raise ValueError("cell_height must be positive")
        if self.columns is not None and self.columns < 1:
            raise ValueError("columns must be at least 1")
