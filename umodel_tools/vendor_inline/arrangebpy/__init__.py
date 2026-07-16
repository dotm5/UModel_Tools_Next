"""Node Arrange - Automatic layout of nodes for Blender node trees."""

# SPDX-License-Identifier: GPL-2.0-or-later
from . import arrange, config, utils
from .arrange.grid import grid_layout
from .arrange.orthogonal import orthogonal_layout
from .arrange.sugiyama import sugiyama_layout
from .arrange.topological import topological_layout
from .layout import layout
from .settings import (
    GridSettings,
    LayoutSettings,
    OrthogonalSettings,
    TopologicalSettings,
)

__all__ = [
    # Main unified interface
    "layout",
    # Individual algorithms
    "sugiyama_layout",
    "topological_layout",
    "grid_layout",
    "orthogonal_layout",
    # Settings
    "LayoutSettings",
    "TopologicalSettings",
    "GridSettings",
    "OrthogonalSettings",
    # Utilities
    "config",
    "utils",
]

__version__ = "0.1.0"
__author__ = "Brady Johnston"
__email__ = "brady.johnston@me.com"
