"""Pure helper functions for material mapping audits.

These functions have no I/O, no Blender dependency, and no mutable state.
They are shared between the CLI audit script and unit tests.
"""

from __future__ import annotations

import os
import re
import typing as t

from .rules import ConnectionSpec, TextureRule


def split_object_path(value: str) -> str:
    """Parse a UE object reference into a clean asset path."""
    if not value:
        return ""

    if "'" in value:
        parts = value.split("'")
        if len(parts) >= 2:
            value = parts[1]

    if ":" in value:
        value = value.split(":", 1)[1]

    match = re.match(r"^(.*)\.\d+$", value)
    if match:
        return match.group(1)

    if "." in value:
        before, after = value.rsplit(".", 1)
        if after and "/" not in after and "\\" not in after:
            return before

    return value


def asset_ref_to_props_path(value: str) -> str:
    """Convert a UE asset reference to a .props.txt relative path."""
    path = split_object_path(value)
    path = path.replace("\\", "/")
    while path.startswith("/"):
        path = path[1:]
    return os.path.normpath(path + ".props.txt")


def asset_name_from_props_path(value: str) -> str:
    """Extract the asset name (without .props.txt) from a props path."""
    basename = os.path.basename(value)
    if basename.lower().endswith(".props.txt"):
        return basename[:-len(".props.txt")]
    return os.path.splitext(basename)[0]


def actor_name(entity: dict[str, t.Any]) -> str:
    """Extract a human-readable actor name from a map JSON entity dict."""
    outer = entity.get("Outer")
    if isinstance(outer, dict):
        object_name = outer.get("ObjectName", "")
        if "'" in object_name:
            inner = object_name.split("'")[1]
            return inner.rsplit(".", 1)[-1]
    return str(entity.get("Name", ""))


def rule_feeds_ao(rule: TextureRule) -> bool:
    """Return True if any connection target is ao_mix.Color2 (ambient occlusion feed)."""
    return any(connection.target == "ao_mix.Color2" for connection in rule.connections)


def rule_feeds_alpha(rule: TextureRule, blend_mode: str | None) -> bool:
    """Return True if the rule's effective connections feed an alpha channel."""
    alpha_targets = {"bsdf.Alpha", "mix_shader.Fac", "mix_shader.Factor"}
    return any(
        connection.target in alpha_targets
        for connection in effective_rule_connections(rule, blend_mode)
    )


def effective_rule_connections(rule: TextureRule, blend_mode: str | None) -> list[ConnectionSpec]:
    """Return rule connections with blend-mode skips applied."""
    return [
        connection for connection in rule.connections
        if not skip_rule_connection(rule, connection, blend_mode)
    ]


def skip_rule_connection(rule: TextureRule, connection: ConnectionSpec, blend_mode: str | None) -> bool:
    """Return True if a diffuse alpha->bsdf.Alpha connection should be skipped for opaque materials."""
    return (
        rule.diffuse
        and blend_mode == "BLEND_Opaque (0)"
        and connection.source == "image.Alpha"
        and connection.target == "bsdf.Alpha"
    )


def rule_disabled_by_static_switch(rule: TextureRule, static_switches: dict[str, bool]) -> bool:
    """Return True if a static switch (UseNormal, UseORM) disables this rule."""
    if rule.name == "normal" and static_switch_is_disabled(static_switches, "usenormal", "use normal"):
        return True

    if (
        rule.name in {"orm", "rmo", "mroh", "mro", "rm", "sro"}
        and static_switch_is_disabled(static_switches, "useorm", "use orm")
    ):
        return True

    return False


def static_switch_is_disabled(static_switches: dict[str, bool], *names: str) -> bool:
    """Return True if any of the named static switches is explicitly False."""
    for name in names:
        if static_switches.get(name.lower()) is False:
            return True
    return False


def shader_plan_from_blend(blend_mode: str | None) -> str:
    """Map a UE blend mode string to a shader plan identifier."""
    match blend_mode:
        case "BLEND_Additive (3)":
            return "additive"
        case "BLEND_Modulate (4)":
            return "modulate"
        case _:
            return "principled"


def principled_summary(has_ao: bool) -> str:
    """Generate a human-readable node summary for a principled BSDF setup."""
    if has_ao:
        return "ao_mix.Result->bsdf.Base Color;bsdf.BSDF->output.Surface"
    return "bsdf.BSDF->output.Surface"


def looks_like_intentional_constant_material(material_name: str, parent_reference: str | None) -> bool:
    """Heuristic: does this material intentionally have no texture parameters?"""
    haystack = " ".join(value for value in (material_name, parent_reference or "") if value).lower()
    return "nothing" in haystack


def uses_packed_diffuse_alpha_emission(
    blend_mode: str | None,
    scalars: dict[str, float],
    vectors: dict[str, t.Any],
) -> bool:
    """Return True if an opaque diffuse material uses alpha for emission strength."""
    return (
        blend_mode == "BLEND_Opaque (0)"
        and ("e_level" in scalars or "e_color" in vectors)
    )


def base_row(**overrides: str) -> dict[str, str]:
    """Create a CSV audit row dict with empty defaults for all known fields."""
    CSV_FIELDS = (
        "map_file",
        "actor_name",
        "component_name",
        "component_type",
        "mesh_object_path",
        "mesh_asset_path",
        "material_slot",
        "material_name",
        "material_asset_path",
        "material_props_path",
        "material_resolution_status",
        "blend_mode",
        "parent_reference",
        "shader_plan",
        "node_summary",
        "matched_rules",
        "texture_params",
        "unrecognized_texture_params",
        "missing_texture_params",
        "fallback_reason",
        "suggestion",
    )
    row = {field: "" for field in CSV_FIELDS}
    row.update({key: str(value) for key, value in overrides.items() if key in row})
    return row
