#!/usr/bin/env python3
"""Audit UModel map JSON material references without importing meshes or textures."""

from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import os
import re
import sys
import time
import typing as t


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
UMODEL_TOOLS_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")

# Ensure umodel_tools is importable as a package for materials.audit imports.
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)


def _load_module(name: str, path: str) -> t.Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


material_rules = _load_module("audit_material_rules", os.path.join(UMODEL_TOOLS_ROOT, "material_rules.py"))
material_shader_hints = _load_module(
    "audit_material_shader_hints",
    os.path.join(UMODEL_TOOLS_ROOT, "material_shader_hints.py"),
)
props_txt_parser = _load_module("audit_props_txt_parser", os.path.join(UMODEL_TOOLS_ROOT, "props_txt_parser.py"))
umodel_path_resolver = _load_module(
    "audit_umodel_path_resolver",
    os.path.join(UMODEL_TOOLS_ROOT, "umodel_path_resolver.py"),
)

# Pure helpers moved to the materials sub-package.
from umodel_tools.materials.audit import (  # noqa: E402
    actor_name,
    asset_name_from_props_path,
    asset_ref_to_props_path,
    base_row,
    effective_rule_connections,
    looks_like_intentional_constant_material,
    principled_summary,
    rule_disabled_by_static_switch,
    rule_feeds_alpha,
    rule_feeds_ao,
    shader_plan_from_blend,
    skip_rule_connection,
    split_object_path,
    static_switch_is_disabled,
    uses_packed_diffuse_alpha_emission,
)


STATIC_MESH_TYPES = {
    "StaticMeshComponent",
    "InstancedStaticMeshComponent",
    "HierarchicalInstancedStaticMeshComponent",
}

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


def main() -> None:
    args = _parse_args()
    settings = umodel_path_resolver.UModelPathInferenceSettings(
        enable_umodel_path_inference=not args.strict_exact,
        path_inference_mode=umodel_path_resolver.STRICT_EXACT
        if args.strict_exact else umodel_path_resolver.AGGRESSIVE,
        enable_suffix_index=True,
    )
    rule_set = material_rules.load_rule_sets(
        material_rules.default_rule_path(rule_name.strip())
        for rule_name in args.rules.split(",")
        if rule_name.strip()
    )

    map_paths = _expand_map_paths(args.maps)
    rows = []
    total_start = time.monotonic()
    for index, map_path in enumerate(map_paths, start=1):
        print(f"[audit] map {index}/{len(map_paths)} start: {map_path}", flush=True)
        map_start = time.monotonic()
        before_count = len(rows)
        rows.extend(audit_map(
            map_path=map_path,
            export_dir=os.path.abspath(args.umodel_export_dir),
            rule_set=rule_set,
            settings=settings,
            include_all=args.include_all,
            progress_interval=args.progress_interval,
        ))
        map_seconds = time.monotonic() - map_start
        map_rows = len(rows) - before_count
        print(
            f"[audit] map {index}/{len(map_paths)} done: rows={map_rows} "
            f"seconds={map_seconds:.1f}",
            flush=True,
        )

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, mode="w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"Wrote {len(rows)} material audit row(s) to {output_path} "
        f"in {time.monotonic() - total_start:.1f}s",
        flush=True,
    )


def audit_map(map_path: str,
              export_dir: str,
              rule_set: material_rules.MaterialRuleSet,
              settings: umodel_path_resolver.UModelPathInferenceSettings,
              include_all: bool,
              progress_interval: int = 0) -> list[dict[str, str]]:
    with open(map_path, mode="r", encoding="utf-8") as file:
        entities = json.load(file)

    rows = []
    start = time.monotonic()
    static_mesh_seen = 0
    for entity_index, entity in enumerate(entities, start=1):
        entity_type = entity.get("Type", "")
        if entity_type not in STATIC_MESH_TYPES:
            continue

        static_mesh_seen += 1
        if progress_interval > 0 and static_mesh_seen % progress_interval == 0:
            print(
                f"[audit] {os.path.basename(map_path)}: "
                f"entities={entity_index}/{len(entities)} "
                f"static_mesh={static_mesh_seen} rows={len(rows)} "
                f"elapsed={time.monotonic() - start:.1f}s",
                flush=True,
            )

        props = entity.get("Properties") or {}
        static_mesh = props.get("StaticMesh") or {}
        mesh_object_path = _split_object_path(static_mesh.get("ObjectPath", ""))
        if not mesh_object_path or "BasicShapes" in mesh_object_path:
            continue

        actor_name = _actor_name(entity)
        component_name = entity.get("Name", "")
        mesh_asset_path = _asset_ref_to_props_path(mesh_object_path)
        material_refs = _material_refs_from_override(props)
        material_source = "json_override"

        if not material_refs:
            material_refs = _material_refs_from_mesh_props(
                export_dir=export_dir,
                mesh_asset_path=mesh_asset_path,
                settings=settings,
            )
            material_source = "mesh_props"

        if not material_refs:
            rows.append(_base_row(
                map_file=map_path,
                actor_name=actor_name,
                component_name=component_name,
                component_type=entity_type,
                mesh_object_path=mesh_object_path,
                mesh_asset_path=mesh_asset_path,
                material_slot="",
                material_name="",
                material_asset_path="",
                fallback_reason="missing_material_reference",
                suggestion="Check map JSON OverrideMaterials or mesh .props.txt Materials.",
            ))
            continue

        for slot_index, material_ref in enumerate(material_refs):
            row = audit_material_ref(
                map_path=map_path,
                actor_name=actor_name,
                component_name=component_name,
                component_type=entity_type,
                mesh_object_path=mesh_object_path,
                mesh_asset_path=mesh_asset_path,
                material_slot=f"{material_source}:{slot_index}",
                material_ref=material_ref,
                export_dir=export_dir,
                rule_set=rule_set,
                settings=settings,
            )
            if include_all or row["fallback_reason"]:
                rows.append(row)

    return rows


def audit_material_ref(map_path: str,
                       actor_name: str,
                       component_name: str,
                       component_type: str,
                       mesh_object_path: str,
                       mesh_asset_path: str,
                       material_slot: str,
                       material_ref: str,
                       export_dir: str,
                       rule_set: material_rules.MaterialRuleSet,
                       settings: umodel_path_resolver.UModelPathInferenceSettings) -> dict[str, str]:
    material_asset_path = _asset_ref_to_props_path(material_ref)
    material_name = _asset_name_from_props_path(material_asset_path)
    row = _base_row(
        map_file=map_path,
        actor_name=actor_name,
        component_name=component_name,
        component_type=component_type,
        mesh_object_path=mesh_object_path,
        mesh_asset_path=mesh_asset_path,
        material_slot=material_slot,
        material_name=material_name,
        material_asset_path=material_asset_path,
    )

    resolved = umodel_path_resolver.resolve_umodel_export_asset_path(
        export_dir=export_dir,
        asset_path=material_asset_path,
        extensions=(".props.txt",),
        settings=settings,
    )
    row["material_resolution_status"] = resolved.status
    row["material_props_path"] = resolved.relative_path or resolved.expected_path

    if not resolved.found or resolved.path is None:
        row["fallback_reason"] = "missing_material_props"
        row["suggestion"] = "Export this material props file or check path inference settings."
        row["shader_plan"] = "fallback_principled"
        row["node_summary"] = _principled_summary(has_ao=False)
        return row

    desc_ast, texture_infos, base_prop_overrides = props_txt_parser.parse_props_txt(resolved.path, mode="MATERIAL")
    parent_reference = props_txt_parser.extract_parent_reference(desc_ast)
    scalars = props_txt_parser.extract_scalar_parameters(desc_ast)
    vectors = props_txt_parser.extract_vector_parameters(desc_ast)
    static_switches = props_txt_parser.extract_static_switch_parameters(desc_ast)
    blend_mode = base_prop_overrides.get("BlendMode") if base_prop_overrides else None
    shader_hint = material_shader_hints.infer_shader_hint(
        material_name=material_name,
        material_path_local=material_asset_path,
        parent_reference=parent_reference,
        scalar_parameters=scalars,
        vector_parameters=vectors,
        blend_mode=blend_mode,
    )

    row["blend_mode"] = blend_mode or ""
    row["parent_reference"] = parent_reference or ""
    row["texture_params"] = ";".join(sorted(texture_infos))

    if shader_hint is not None:
        row["shader_plan"] = shader_hint.shader
        row["node_summary"] = _shader_hint_summary(shader_hint)
        row["matched_rules"] = "material_hint:" + shader_hint.shader
        return row

    recognized = []
    unrecognized = []
    missing_texture_params = []
    has_diffuse = False
    has_ao = False
    has_alpha_source = False

    for tex_param, tex_ref in texture_infos.items():
        tex_path_no_ext, tex_short_name = os.path.splitext(tex_ref)
        rule = rule_set.resolve(tex_param, tex_short_name)
        if rule is None:
            unrecognized.append(f"{tex_param}={tex_ref}")
            continue

        if _rule_disabled_by_static_switch(rule, static_switches):
            recognized.append(f"{tex_param}->{rule.name}(disabled)")
            continue

        recognized.append(f"{tex_param}->{rule.name}")
        if rule.diffuse:
            has_diffuse = True
        if _rule_feeds_ao(rule):
            has_ao = True
        if _rule_feeds_alpha(rule, blend_mode):
            has_alpha_source = True
        if not tex_ref or tex_ref.strip().lower() == "none":
            missing_texture_params.append(tex_param)

    row["matched_rules"] = ";".join(recognized)
    row["unrecognized_texture_params"] = ";".join(unrecognized)
    row["missing_texture_params"] = ";".join(missing_texture_params)
    row["shader_plan"] = _shader_plan_from_blend(blend_mode)
    row["node_summary"] = _node_summary_for_rules(
        rule_set,
        texture_infos,
        has_ao,
        blend_mode,
        scalars,
        vectors,
        static_switches,
    )

    fallback_reasons = []
    suggestions = []
    if unrecognized:
        fallback_reasons.append("unrecognized_texture_params")
        suggestions.append("Add param/suffix aliases to generic.yaml or a material hint.")
    if texture_infos and not recognized:
        fallback_reasons.append("no_texture_rules_matched")
        suggestions.append("Inspect texture parameter names and suffixes.")
    if (
        not texture_infos
        and row["shader_plan"] == "principled"
        and not _looks_like_intentional_constant_material(material_name, parent_reference)
    ):
        fallback_reasons.append("no_textures_or_material_hint")
        suggestions.append("Add material-level hints for constant-only materials if this should not be plain BSDF.")
    if blend_mode == "BLEND_Translucent (2)" and row["shader_plan"] == "principled" and not has_alpha_source:
        fallback_reasons.append("translucent_without_shader_hint")
        suggestions.append("Likely needs glass/translucent/alpha material hint.")
    if missing_texture_params:
        fallback_reasons.append("texture_param_without_path")
        suggestions.append("Handle None texture parameters via scalar/vector constants or parent material hints.")

    row["fallback_reason"] = ";".join(dict.fromkeys(fallback_reasons))
    row["suggestion"] = ";".join(dict.fromkeys(suggestions))
    return row


def _material_refs_from_override(props: dict[str, t.Any]) -> list[str]:
    refs = []
    for material in props.get("OverrideMaterials") or []:
        object_path = material.get("ObjectPath") if isinstance(material, dict) else ""
        if object_path:
            refs.append(object_path)
    return refs


def _material_refs_from_mesh_props(export_dir: str,
                                   mesh_asset_path: str,
                                   settings: umodel_path_resolver.UModelPathInferenceSettings) -> list[str]:
    resolved = umodel_path_resolver.resolve_umodel_export_asset_path(
        export_dir=export_dir,
        asset_path=mesh_asset_path,
        extensions=(".props.txt",),
        settings=settings,
    )
    if not resolved.found or resolved.path is None:
        return []

    try:
        _, material_paths = props_txt_parser.parse_props_txt(resolved.path, mode="MESH")
    except RuntimeError:
        return []

    return material_paths


# Aliases so existing local call sites don't need renaming.
_split_object_path = split_object_path
_asset_ref_to_props_path = asset_ref_to_props_path
_asset_name_from_props_path = asset_name_from_props_path
_actor_name = actor_name
_rule_feeds_ao = rule_feeds_ao
_rule_feeds_alpha = rule_feeds_alpha
_effective_rule_connections = effective_rule_connections
_skip_rule_connection = skip_rule_connection
_rule_disabled_by_static_switch = rule_disabled_by_static_switch
_static_switch_is_disabled = static_switch_is_disabled
_shader_plan_from_blend = shader_plan_from_blend
_principled_summary = principled_summary
_looks_like_intentional_constant_material = looks_like_intentional_constant_material
_uses_packed_diffuse_alpha_emission = uses_packed_diffuse_alpha_emission
_base_row = base_row


def _shader_hint_summary(shader_hint: material_shader_hints.MaterialShaderHint) -> str:
    if shader_hint.shader == "glass" and shader_hint.alpha < 1.0:
        return (
            "glass.BSDF->mix_shader.Shader;"
            "transparent.BSDF->mix_shader.Shader_001;"
            f"mix_shader.Fac={1.0 - shader_hint.alpha:.6g};"
            "mix_shader.Shader->output.Surface"
        )
    if shader_hint.shader == "glass":
        return "glass.BSDF->output.Surface"
    return f"{shader_hint.shader}->output.Surface"


def _node_summary_for_rules(rule_set: material_rules.MaterialRuleSet,
                            texture_infos: dict[str, str],
                            has_ao: bool,
                            blend_mode: str | None,
                            scalars: dict[str, float],
                            vectors: dict[str, props_txt_parser.Color],
                            static_switches: dict[str, bool]) -> str:
    parts = []
    if texture_infos:
        for tex_param, tex_ref in sorted(texture_infos.items()):
            tex_path_no_ext, tex_short_name = os.path.splitext(tex_ref)
            rule = rule_set.resolve(tex_param, tex_short_name)
            if rule is None:
                continue
            if _rule_disabled_by_static_switch(rule, static_switches):
                continue
            for connection in rule.connections:
                if _skip_rule_connection(rule, connection, blend_mode):
                    if _uses_packed_diffuse_alpha_emission(blend_mode, scalars, vectors):
                        parts.append(f"{tex_param}:image.Alpha->bsdf.Emission Strength")
                    continue
                parts.append(f"{tex_param}:{connection.source}->{connection.target}")

    parts.append(_principled_summary(has_ao=has_ao))
    return ";".join(parts)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit material shader-rule mapping from UModel map JSON files without importing meshes/textures.",
    )
    parser.add_argument(
        "--umodel-export-dir",
        required=True,
        help="Root directory of the UModel export containing .props.txt files.",
    )
    parser.add_argument(
        "--map",
        dest="maps",
        action="append",
        required=True,
        help="Map JSON file, directory, or glob. May be provided multiple times.",
    )
    parser.add_argument(
        "--output",
        default="material_mapping_audit.csv",
        help="CSV output path.",
    )
    parser.add_argument(
        "--rules",
        default="generic",
        help="Comma-separated material rule YAML names under umodel_tools/game_profiles/rules.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Write every material row instead of only rows with fallback/suspicious reasons.",
    )
    parser.add_argument(
        "--strict-exact",
        action="store_true",
        help="Disable UModel path inference and suffix lookup.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=250,
        help="Print progress after this many StaticMeshComponent rows. Use 0 to disable.",
    )
    return parser.parse_args()


def _expand_map_paths(values: t.Iterable[str]) -> list[str]:
    paths = []
    for value in values:
        absolute = os.path.abspath(value)
        if os.path.isdir(absolute):
            matches = glob.glob(os.path.join(absolute, "*.json"))
        else:
            matches = glob.glob(absolute)

        if not matches:
            raise SystemExit(f"No map JSON matched: {value}")

        paths.extend(os.path.abspath(path) for path in matches if path.lower().endswith(".json"))

    unique_paths = []
    seen = set()
    for path in sorted(paths):
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)

    return unique_paths


if __name__ == "__main__":
    main()
