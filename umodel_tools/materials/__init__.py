"""Material rule matching, YAML parsing, and audit helpers.

This sub-package is pure Python — no Blender (bpy) dependency.
"""

from .decision import ConnectionSpec, MaterialRuleSet, NodeSpec, TextureRule
from . import rules_yaml

__all__ = [
    "ConnectionSpec",
    "MaterialRuleSet",
    "NodeSpec",
    "TextureRule",
    "rules_yaml",
]
