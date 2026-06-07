"""Config-backed texture rule helpers for game profiles."""

from __future__ import annotations

import os
import tomllib
import dataclasses
import typing as t

from .. import import_support


RULE_FILE_EXTENSIONS = frozenset({".toml"})
Color: t.TypeAlias = tuple[float, float, float, float]


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
    node_groups: tuple[str, ...] = ()
    skip_when: frozenset[tuple[str, bool]] = frozenset()

    def matches_param(self, tex_type: str) -> bool:
        return import_support.normalize_token(tex_type) in self.param_names

    def matches_suffix(self, tex_short_name: str) -> bool:
        return import_support.matches_texture_suffix(tex_short_name, self.suffixes)


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


@dataclasses.dataclass(frozen=True)
class MaterialShaderHint:
    shader: str
    color: Color
    alpha: float
    roughness: float | None = None


def load_rule_sets(rule_paths: t.Iterable[str]) -> MaterialRuleSet:
    rules: list[TextureRule] = []
    normalized_paths = _deduplicate_paths(rule_paths)

    for rule_path in normalized_paths:
        try:
            rules.extend(load_rule_set(rule_path).rules)
        except (OSError, RuntimeError) as exc:
            print(f"Warning: Material rule dataset {rule_path!r} could not be loaded: {exc}")

    if not rules:
        return load_rule_set(default_rule_path("generic"))

    return MaterialRuleSet(rules)


def load_rule_set(rule_path: str) -> MaterialRuleSet:
    extension = os.path.splitext(rule_path)[1].lower()
    if extension == ".toml":
        return parse_rule_set_dict(load_rule_data(rule_path), rule_path)
    raise RuntimeError(f"Unsupported material rule file extension {extension!r} for {rule_path!r}.")


def parse_rule_set_dict(data: t.Any, rule_path: str) -> MaterialRuleSet:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Material rule file {rule_path} must be a mapping.")

    raw_rules = data.get("texture_rules", [])
    if not isinstance(raw_rules, list):
        raise RuntimeError(f"Material rule file {rule_path} must define texture_rules as a list.")

    return MaterialRuleSet([_parse_texture_rule(raw_rule, rule_path) for raw_rule in raw_rules])


def default_rule_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "game_profiles", "rules", f"{name}.toml")


def default_rule_dataset() -> tuple[str, str]:
    return "Generic", default_rule_path("generic")


def dataset_display_name(rule_path: str) -> str:
    try:
        data = load_rule_data(rule_path)
    except (OSError, RuntimeError):
        return os.path.splitext(os.path.basename(rule_path))[0] or "Material Rules"

    name = str(data.get("name", "")).strip() if isinstance(data, dict) else ""
    return name or os.path.splitext(os.path.basename(rule_path))[0] or "Material Rules"


def load_rule_data(rule_path: str) -> dict[str, t.Any]:
    extension = os.path.splitext(rule_path)[1].lower()
    if extension == ".toml":
        with open(rule_path, mode="rb") as rule_file:
            return tomllib.load(rule_file)
    raise RuntimeError(f"Unsupported material rule file extension {extension!r} for {rule_path!r}.")


def _deduplicate_paths(rule_paths: t.Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique_paths: list[str] = []
    for rule_path in rule_paths:
        if not rule_path:
            continue
        normalized = os.path.abspath(os.path.normpath(rule_path))
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(normalized)
    return tuple(unique_paths)


def _parse_texture_rule(raw_rule: t.Any, rule_path: str) -> TextureRule:
    if not isinstance(raw_rule, dict):
        raise RuntimeError(f"Material rule entries in {rule_path} must be mappings.")

    name = str(raw_rule.get("name", "")).strip()
    if not name:
        raise RuntimeError(f"Material rule entries in {rule_path} must have a name.")

    match = raw_rule.get("match", {})
    if not isinstance(match, dict):
        raise RuntimeError(f"Material rule {name!r} in {rule_path} has an invalid match block.")

    nodes = raw_rule.get("nodes", {})
    if nodes is None:
        nodes = {}
    if not isinstance(nodes, dict):
        raise RuntimeError(f"Material rule {name!r} in {rule_path} has an invalid nodes block.")

    connections = raw_rule.get("connections", [])
    if not isinstance(connections, list):
        raise RuntimeError(f"Material rule {name!r} in {rule_path} has an invalid connections block.")

    return TextureRule(
        name=name,
        diffuse=bool(raw_rule.get("diffuse", False)),
        prefer_suffix=bool(raw_rule.get("prefer_suffix", False)),
        param_names=frozenset(import_support.normalize_token(value) for value in match.get("param_names", [])),
        suffixes=frozenset(import_support.normalize_token(value) for value in match.get("suffixes", [])),
        node_groups=tuple(str(value).strip() for value in raw_rule.get("node_groups", []) if str(value).strip()),
        nodes=tuple(NodeSpec(str(node_name), str(node_type)) for node_name, node_type in nodes.items()),
        connections=tuple(_parse_connection(connection, name, rule_path) for connection in connections),
        skip_when=_parse_skip_when(raw_rule.get("skip_when", {}), name, rule_path),
    )


def _parse_connection(raw_connection: t.Any, rule_name: str, rule_path: str) -> ConnectionSpec:
    if not isinstance(raw_connection, dict):
        raise RuntimeError(f"Connection entries in rule {rule_name!r} from {rule_path} must be mappings.")

    source = str(raw_connection.get("from", "")).strip()
    target = str(raw_connection.get("to", "")).strip()
    if not source or not target:
        raise RuntimeError(f"Connection entries in rule {rule_name!r} from {rule_path} need from/to values.")

    return ConnectionSpec(source=source, target=target)


def _parse_skip_when(raw_skip_when: t.Any, rule_name: str, rule_path: str) -> frozenset[tuple[str, bool]]:
    if raw_skip_when in (None, {}):
        return frozenset()
    if not isinstance(raw_skip_when, dict):
        raise RuntimeError(f"skip_when in rule {rule_name!r} from {rule_path} must be a mapping.")

    conditions: list[tuple[str, bool]] = []
    for switch_name, expected_value in raw_skip_when.items():
        normalized_name = import_support.normalize_token(switch_name)
        if not normalized_name:
            raise RuntimeError(f"skip_when in rule {rule_name!r} from {rule_path} has an empty switch name.")
        if not isinstance(expected_value, bool):
            raise RuntimeError(
                f"skip_when value for switch {switch_name!r} in rule {rule_name!r} from {rule_path} must be true/false."
            )
        conditions.append((normalized_name, expected_value))

    return frozenset(conditions)


def _matches_texture_suffix(tex_short_name: str, suffixes: frozenset[str]) -> bool:
    return import_support.matches_texture_suffix(tex_short_name, suffixes)


def _texture_suffix(normalized_tex_name: str) -> str:
    return import_support.texture_suffix(normalized_tex_name)


def _normalize_texture_name(tex_short_name: str) -> str:
    return import_support.normalize_texture_name(tex_short_name)


def _normalize_token(value: t.Any) -> str:
    return import_support.normalize_token(value)


def infer_shader_hint(material_name: str,
                      material_path_local: str,
                      parent_reference: str | None,
                      scalar_parameters: dict[str, float],
                      vector_parameters: dict[str, Color],
                      blend_mode: str | None) -> MaterialShaderHint | None:
    if not _looks_like_refractive_surface(material_name, material_path_local, parent_reference, scalar_parameters):
        return None

    if blend_mode == 'BLEND_Opaque (0)':
        return None

    alpha = _first_scalar(scalar_parameters, ("alphascale", "opacity"), default=0.35)

    return MaterialShaderHint(
        shader="glass",
        color=_first_color(vector_parameters, ("color", "basecolor", "basecolortint", "watercolor", "dconst")),
        alpha=_clamp(alpha),
        roughness=_first_scalar(scalar_parameters, ("roughness level", "roughness"), default=None),
    )


def _looks_like_refractive_surface(material_name: str,
                                   material_path_local: str,
                                   parent_reference: str | None,
                                   scalar_parameters: dict[str, float]) -> bool:
    haystack = " ".join(
        value for value in (material_name, material_path_local, parent_reference or "") if value
    ).replace("\\", "/").lower()

    path_parts = [part for part in haystack.split("/") if part]
    basename = os.path.splitext(os.path.basename(material_path_local))[0].lower()
    name_parts = basename.replace("-", "_").split("_")

    return (
        "glass" in path_parts
        or "water" in path_parts
        or "glass" in name_parts
        or "water" in name_parts
        or "refraction" in scalar_parameters
        or "frostedglass" in haystack
        or "glass_" in haystack
        or "_glass" in haystack
        or "water_" in haystack
        or "_water" in haystack
    )


def _first_color(values: dict[str, Color], names: t.Iterable[str]) -> Color:
    for name in names:
        value = values.get(name)
        if value is not None:
            return value

    return 1.0, 1.0, 1.0, 1.0


def _first_scalar(values: dict[str, float], names: t.Iterable[str], default: float | None) -> float | None:
    for name in names:
        value = values.get(name)
        if value is not None:
            return value

    return default


def _clamp(value: float | None) -> float:
    if value is None:
        return 1.0

    return min(max(float(value), 0.0), 1.0)
