"""Material texture rule data structures and resolve order."""

from __future__ import annotations

import dataclasses
import typing as t

try:
    from . import texture_path_utils
except ImportError:  # pragma: no cover - supports direct file loading in lightweight tests.
    import texture_path_utils  # type: ignore


@dataclasses.dataclass(frozen=True)
class NodeSpec:
    name: str
    node_type: str


@dataclasses.dataclass(frozen=True)
class ConnectionSpec:
    source: str
    target: str


@dataclasses.dataclass(frozen=True)
class TextureRule:
    name: str
    diffuse: bool
    prefer_suffix: bool
    param_names: frozenset[str]
    suffixes: frozenset[str]
    nodes: tuple[NodeSpec, ...]
    connections: tuple[ConnectionSpec, ...]

    def matches_param(self, tex_type: str) -> bool:
        return texture_path_utils.normalize_token(tex_type) in self.param_names

    def matches_suffix(self, tex_short_name: str) -> bool:
        return texture_path_utils.matches_texture_suffix(tex_short_name, self.suffixes)


class MaterialRuleSet:
    def __init__(self, rules: t.Sequence[TextureRule]) -> None:
        self.rules = tuple(rules)

    def resolve(self, tex_type: str, tex_short_name: str) -> TextureRule | None:
        suffix_matches = [rule for rule in self.rules if rule.matches_suffix(tex_short_name)]
        for rule in suffix_matches:
            if rule.prefer_suffix:
                return rule

        for rule in self.rules:
            if rule.matches_param(tex_type):
                return rule

        return suffix_matches[0] if suffix_matches else None
