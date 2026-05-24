"""Config-backed texture rule helpers for game profiles."""

from __future__ import annotations

import importlib.util
import os
import sys
import typing as t


def _load_sibling_module(module_name: str):
    module_path = os.path.join(os.path.dirname(__file__), f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {module_name!r} from {module_path!r}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


try:
    from . import texture_path_utils
    from .material_decision import ConnectionSpec, MaterialRuleSet, NodeSpec, TextureRule
except ImportError:  # pragma: no cover - supports direct file loading in lightweight tests.
    texture_path_utils = _load_sibling_module("texture_path_utils")
    material_decision = _load_sibling_module("material_decision")
    ConnectionSpec = material_decision.ConnectionSpec
    MaterialRuleSet = material_decision.MaterialRuleSet
    NodeSpec = material_decision.NodeSpec
    TextureRule = material_decision.TextureRule


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
    try:
        import yaml  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load material rule YAML files.") from exc

    with open(rule_path, mode="r", encoding="utf-8") as rule_file:
        data = yaml.safe_load(rule_file) or {}

    raw_rules = data.get("texture_rules", [])
    if not isinstance(raw_rules, list):
        raise RuntimeError(f"Material rule file {rule_path} must define texture_rules as a list.")

    return MaterialRuleSet([_parse_texture_rule(raw_rule, rule_path) for raw_rule in raw_rules])


def default_rule_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "game_profiles", "rules", f"{name}.yaml")


def default_rule_dataset() -> tuple[str, str]:
    return "Generic", default_rule_path("generic")


def dataset_display_name(rule_path: str) -> str:
    try:
        import yaml  # pylint: disable=import-outside-toplevel
        with open(rule_path, mode="r", encoding="utf-8") as rule_file:
            data = yaml.safe_load(rule_file) or {}
    except (ImportError, OSError, RuntimeError):
        return os.path.splitext(os.path.basename(rule_path))[0] or "Material Rules"

    name = str(data.get("name", "")).strip() if isinstance(data, dict) else ""
    return name or os.path.splitext(os.path.basename(rule_path))[0] or "Material Rules"


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
        param_names=frozenset(texture_path_utils.normalize_token(value) for value in match.get("param_names", [])),
        suffixes=frozenset(texture_path_utils.normalize_token(value) for value in match.get("suffixes", [])),
        nodes=tuple(NodeSpec(str(node_name), str(node_type)) for node_name, node_type in nodes.items()),
        connections=tuple(_parse_connection(connection, name, rule_path) for connection in connections),
    )


def _parse_connection(raw_connection: t.Any, rule_name: str, rule_path: str) -> ConnectionSpec:
    if not isinstance(raw_connection, dict):
        raise RuntimeError(f"Connection entries in rule {rule_name!r} from {rule_path} must be mappings.")

    source = str(raw_connection.get("from", "")).strip()
    target = str(raw_connection.get("to", "")).strip()
    if not source or not target:
        raise RuntimeError(f"Connection entries in rule {rule_name!r} from {rule_path} need from/to values.")

    return ConnectionSpec(source=source, target=target)


def _matches_texture_suffix(tex_short_name: str, suffixes: frozenset[str]) -> bool:
    return texture_path_utils.matches_texture_suffix(tex_short_name, suffixes)


def _texture_suffix(normalized_tex_name: str) -> str:
    return texture_path_utils.texture_suffix(normalized_tex_name)


def _normalize_texture_name(tex_short_name: str) -> str:
    return texture_path_utils.normalize_texture_name(tex_short_name)


def _normalize_token(value: t.Any) -> str:
    return texture_path_utils.normalize_token(value)
