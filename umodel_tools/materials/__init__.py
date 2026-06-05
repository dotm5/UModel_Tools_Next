"""Material rule matching, config parsing, and audit helpers.

This sub-package is pure Python — no Blender (bpy) dependency.
"""

from .rules import ConnectionSpec, MaterialRuleSet, MaterialShaderHint, NodeSpec, TextureRule
from . import rules

__all__ = [
    "ConnectionSpec",
    "MaterialRuleSet",
    "MaterialShaderHint",
    "NodeSpec",
    "TextureRule",
    "rules",
]
