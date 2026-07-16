# SPDX-License-Identifier: GPL-2.0-or-later

"""
Unified Layout Interface

This module provides a single entry point for all layout algorithms.
Choose the algorithm and settings that best fit your use case.
"""

from __future__ import annotations

from typing import Literal, overload

from bpy.types import NodeTree

from .settings import (
    GridSettings,
    LayoutSettings,
    OrthogonalSettings,
    TopologicalSettings,
)

Algorithm = Literal["sugiyama", "topological", "grid", "orthogonal"]


@overload
def layout(
    ntree: NodeTree,
    *,
    algorithm: Literal["sugiyama"] = "sugiyama",
    settings: LayoutSettings = ...,
) -> None: ...


@overload
def layout(
    ntree: NodeTree,
    *,
    algorithm: Literal["topological"],
    settings: TopologicalSettings = ...,
) -> None: ...


@overload
def layout(
    ntree: NodeTree, *, algorithm: Literal["grid"], settings: GridSettings = ...
) -> None: ...


@overload
def layout(
    ntree: NodeTree,
    *,
    algorithm: Literal["orthogonal"],
    settings: OrthogonalSettings = ...,
) -> None: ...


def layout(
    ntree: NodeTree,
    *,
    algorithm: Algorithm = "sugiyama",
    settings: LayoutSettings
    | TopologicalSettings
    | GridSettings
    | OrthogonalSettings
    | None = None,
) -> None:
    """
    Apply automatic layout to a Blender node tree.

    This is a unified interface that dispatches to different layout algorithms
    based on the `algorithm` parameter.

    Args:
        ntree: The Blender node tree to layout
        algorithm: Which layout algorithm to use
        settings: Algorithm-specific settings (uses defaults if None)

    Available Algorithms:
        - "sugiyama": Hierarchical layout with minimal crossings (default)
          Best for: Most node trees, especially shader and geometry nodes
          Settings: LayoutSettings

        - "topological": Simple layered layout without crossing reduction
          Best for: Quick layouts, very large graphs, development
          Settings: TopologicalSettings

        - "grid": Regular grid arrangement, optionally grouped
          Best for: Collections of similar nodes, documentation
          Settings: GridSettings

        - "orthogonal": Hierarchical layout with orthogonal edge routing
          Best for: Professional presentations, blueprints
          Settings: OrthogonalSettings

    Examples:
        # Default Sugiyama layout
        layout(ntree)

        # Sugiyama with custom settings
        layout(ntree, algorithm="sugiyama", settings=LayoutSettings(
            direction="BALANCED",
            socket_alignment="FULL",
            stack_collapsed=True
        ))

        # Fast topological layout
        layout(ntree, algorithm="topological")

        # Topological with custom spacing
        layout(ntree, algorithm="topological", settings=TopologicalSettings(
            horizontal_spacing=60.0,
            sort_by_degree=True
        ))

        # Grid layout grouped by type
        layout(ntree, algorithm="grid", settings=GridSettings(
            grouping="TYPE",
            columns=5,
            cell_width=250.0
        ))

        # Orthogonal routing for clean presentation
        layout(ntree, algorithm="orthogonal", settings=OrthogonalSettings(
            horizontal_spacing=80.0,
            socket_alignment="FULL",
            route_through_grid=True
        ))

    Raises:
        ValueError: If algorithm is not recognized
        TypeError: If settings don't match the algorithm
    """
    if algorithm == "sugiyama":
        from .arrange.sugiyama import sugiyama_layout

        if settings is None:
            settings = LayoutSettings()
        elif not isinstance(settings, LayoutSettings):
            raise TypeError(
                f"algorithm='sugiyama' requires LayoutSettings, got {type(settings).__name__}"
            )
        sugiyama_layout(ntree, settings)

    elif algorithm == "topological":
        from .arrange.topological import topological_layout

        if settings is None:
            settings = TopologicalSettings()
        elif not isinstance(settings, TopologicalSettings):
            raise TypeError(
                f"algorithm='topological' requires TopologicalSettings, got {type(settings).__name__}"
            )
        topological_layout(ntree, settings)

    elif algorithm == "grid":
        from .arrange.grid import grid_layout

        if settings is None:
            settings = GridSettings()
        elif not isinstance(settings, GridSettings):
            raise TypeError(
                f"algorithm='grid' requires GridSettings, got {type(settings).__name__}"
            )
        grid_layout(ntree, settings)

    elif algorithm == "orthogonal":
        from .arrange.orthogonal import orthogonal_layout

        if settings is None:
            settings = OrthogonalSettings()
        elif not isinstance(settings, OrthogonalSettings):
            raise TypeError(
                f"algorithm='orthogonal' requires OrthogonalSettings, got {type(settings).__name__}"
            )
        orthogonal_layout(ntree, settings)

    else:
        raise ValueError(
            f"Unknown algorithm: {algorithm!r}. "
            f"Must be one of: 'sugiyama', 'topological', 'grid', 'orthogonal'"
        )
