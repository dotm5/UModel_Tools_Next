import argparse
import json
import os
import re
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
DEFAULT_MANUAL_BLEND = os.path.join(ADDON_ROOT, "reference", "my real project", "kanami1.blend")
DEFAULT_PACKAGE_ROOT = os.path.join(
    ADDON_ROOT,
    "reference",
    "calabiyau_references",
    "SK_Kanami_Lobby_S103",
)
DEFAULT_EXPORT_ROOT = os.path.join(DEFAULT_PACKAGE_ROOT, "Content")
DEFAULT_UEMODEL = os.path.join(
    DEFAULT_EXPORT_ROOT,
    "PaperMan",
    "SkinAssets",
    "Characters",
    "Kanami",
    "S103",
    "Mesh3D",
    "Kanami_Mesh_103.uemodel",
)
DEFAULT_RUNTIME_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "calabiyau_s103_shader_baseline")

MATERIALS_OF_INTEREST = {
    "MI_Kanami_Body_103",
    "MI_Kanami_Eye",
    "MI_Kanami_Face",
    "MI_Kanami_Hair_103",
    "T_Kanami_Body_Metal_103",
    "T_Kanami_Skin_103",
}

EXPECTED_TEXTURES = {
    "MI_Kanami_Body_103": {
        "T_Kanami_Body_103_D.png",
        "T_Kanami_Body_103_N.png",
        "T_Kanmami_Body_Mask1_Map.png",
        "T_Kanmami_Body_Mask2_Map.png",
        "Materials1.png",
    },
    "MI_Kanami_Hair_103": {
        "T_Kanami_Hair_103_D.png",
        "T_Kanami_Hair_Mask1_Map.png",
        "T_Toon_DefaultMask2_Linear_NoAlpha.png",
    },
    "MI_Kanami_Eye": {
        "T_Kanami_Face_D.png",
        "T_Toon_DefaultMask1_Linear_NoAlpha.png",
        "T_Kanami_Face_Mask2_Map.png",
    },
    "MI_Kanami_Face": {
        "T_Kanami_Face_D.png",
        "T_Kanami_SDF.png",
        "T_Toon_DefaultMask1_Linear_NoAlpha.png",
        "T_DefaultBlue_Linear.png",
    },
    "T_Kanami_Body_Metal_103": {
        "T_Kanami_Body_103_D.png",
        "T_Kanami_Body_103_N.png",
        "T_Kanmami_Body_Mask1_Map.png",
        "T_Toon_DefaultMask2_Linear_NoAlpha.png",
        "metallic2.png",
    },
    "T_Kanami_Skin_103": {
        "T_Kanami_Body_103_D.png",
        "T_Toon_DefaultMask1_Linear_NoAlpha.png",
    },
}


def main() -> int:
    args = _parse_args()
    runtime_root = os.path.abspath(args.runtime_root)
    report_path = os.path.join(runtime_root, "shader_baseline_report.json")

    _reset_runtime_root(runtime_root)
    baseline = _snapshot_manual_baseline(args.manual_blend)
    imported = _snapshot_current_rules_import(
        uemodel=args.uemodel,
        export_root=args.export_root,
        runtime_root=runtime_root,
    )
    comparisons = _compare_snapshots(baseline, imported)

    report = {
        "manual_blend": os.path.abspath(args.manual_blend),
        "uemodel": os.path.abspath(args.uemodel),
        "export_root": os.path.abspath(args.export_root),
        "runtime_root": runtime_root,
        "baseline": baseline,
        "imported": imported,
        "comparisons": comparisons,
    }

    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    _print_summary(comparisons, report_path)
    return 1 if any(item["issues"] for item in comparisons) else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare current UEFormat shader rules against Kanami S103 baseline.")
    parser.add_argument("--manual-blend", default=DEFAULT_MANUAL_BLEND)
    parser.add_argument("--package-root", default=DEFAULT_PACKAGE_ROOT)
    parser.add_argument("--export-root", default=DEFAULT_EXPORT_ROOT)
    parser.add_argument("--uemodel", default=DEFAULT_UEMODEL)
    parser.add_argument("--runtime-root", default=DEFAULT_RUNTIME_ROOT)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def _reset_runtime_root(runtime_root: str) -> None:
    resolved = os.path.abspath(runtime_root)
    allowed_root = os.path.abspath(os.path.join(ADDON_ROOT, "tests", "runtime"))
    if os.path.isdir(resolved):
        if not os.path.normcase(resolved).startswith(os.path.normcase(allowed_root + os.sep)):
            raise RuntimeError(f"Refusing to delete runtime root outside tests/runtime: {resolved}")
        shutil.rmtree(resolved)
    os.makedirs(resolved, exist_ok=True)


def _snapshot_manual_baseline(manual_blend: str) -> dict[str, dict]:
    if not os.path.isfile(manual_blend):
        raise RuntimeError(f"Missing manual baseline blend: {manual_blend}")

    bpy.ops.wm.open_mainfile(filepath=manual_blend)
    return _snapshot_materials()


def _snapshot_current_rules_import(uemodel: str, export_root: str, runtime_root: str) -> dict[str, dict]:
    if not os.path.isfile(uemodel):
        raise RuntimeError(f"Missing UEFormat model: {uemodel}")
    if not os.path.isdir(export_root):
        raise RuntimeError(f"Missing export root: {export_root}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    _enable_source_addon()

    prefs = bpy.context.preferences.addons["umodel_tools"].preferences
    prefs.default_load_pbr_maps = True
    prefs.default_texture_format = ".png"
    prefs.default_import_backface_culling = False
    prefs.enable_umodel_path_inference = True
    prefs.enable_suffix_index = True

    result = bpy.ops.umodel_tools.import_ueformat_model(
        filepath=uemodel,
        umodel_export_dir=export_root,
        asset_cache_dir=runtime_root,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"UEFormat import did not finish: {result!r}")

    return _snapshot_materials()


def _enable_source_addon() -> None:
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")


def _snapshot_materials() -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for mat in bpy.data.materials:
        normalized = _normalize_material_name(mat.name)
        if normalized not in MATERIALS_OF_INTEREST:
            continue
        if not mat.use_nodes or mat.node_tree is None:
            snapshot[normalized] = {
                "source_name": mat.name,
                "blend_method": mat.blend_method,
                "alpha_threshold": getattr(mat, "alpha_threshold", None),
                "nodes": [],
                "images": [],
                "links": [],
            }
            continue

        image_nodes = [node for node in mat.node_tree.nodes if node.bl_idname == "ShaderNodeTexImage"]
        snapshot[normalized] = {
            "source_name": mat.name,
            "blend_method": mat.blend_method,
            "alpha_threshold": getattr(mat, "alpha_threshold", None),
            "nodes": sorted(node.bl_idname for node in mat.node_tree.nodes),
            "images": [_image_summary(node) for node in image_nodes],
            "links": sorted(
                (_link_summary(link) for link in mat.node_tree.links),
                key=lambda item: (item["from"], item["to"]),
            ),
        }
    return snapshot


def _normalize_material_name(name: str) -> str:
    normalized = re.sub(r"\.\d+$", "", name)
    if normalized.endswith("_eevee"):
        normalized = normalized[:-len("_eevee")]
    return normalized


def _image_summary(node: bpy.types.Node) -> dict[str, str | None]:
    image = getattr(node, "image", None)
    return {
        "node": node.name,
        "image": image.name if image is not None else None,
        "colorspace": image.colorspace_settings.name if image is not None else None,
        "alpha_mode": image.alpha_mode if image is not None else None,
        "filepath": bpy.path.abspath(image.filepath) if image is not None and image.filepath else "",
    }


def _link_summary(link: bpy.types.NodeLink) -> dict[str, str]:
    return {
        "from_node": link.from_node.name,
        "from_socket": link.from_socket.name,
        "to_node": link.to_node.name,
        "to_socket": link.to_socket.name,
        "from": f"{link.from_node.name}.{link.from_socket.name}",
        "to": f"{link.to_node.name}.{link.to_socket.name}",
    }


def _compare_snapshots(baseline: dict[str, dict], imported: dict[str, dict]) -> list[dict]:
    comparisons = []
    for material_name in sorted(MATERIALS_OF_INTEREST):
        base = baseline.get(material_name)
        current = imported.get(material_name)
        issues: list[str] = []

        if base is None:
            issues.append("missing_manual_baseline_material")
        if current is None:
            issues.append("missing_imported_material")
            comparisons.append({"material": material_name, "issues": issues})
            continue

        if "Placeholder" in current.get("source_name", ""):
            issues.append("imported_placeholder_material")

        if current.get("blend_method") != base.get("blend_method"):
            issues.append(f"blend_method_diff:{current.get('blend_method')}!=baseline:{base.get('blend_method')}")

        current_images = _image_names(current)
        expected = EXPECTED_TEXTURES.get(material_name, set())
        missing_textures = sorted(texture for texture in expected if texture not in current_images)
        if missing_textures:
            issues.append("missing_expected_textures:" + ",".join(missing_textures))

        duplicates = sorted(name for name in current_images if current_images.count(name) > 1)
        if duplicates:
            issues.append("duplicate_image_nodes:" + ",".join(sorted(set(duplicates))))

        current_links = current.get("links", [])
        base_links = base.get("links", []) if base is not None else []
        for socket in ("Base Color", "Roughness", "Metallic", "Normal", "Emission Strength"):
            if _has_socket_target(base_links, socket) and not _has_socket_target(current_links, socket):
                issues.append(f"missing_baseline_socket_target:{socket}")

        if _has_mask_texture(current, "Mask1") and not (
            _has_socket_target(current_links, "Roughness") and _has_socket_target(current_links, "Metallic")
        ):
            issues.append("mask1_not_driving_roughness_metallic")

        if _has_matcap_texture(current) and not _has_socket_target(current_links, "Emission Strength"):
            issues.append("matcap_not_driving_emission_strength")

        comparisons.append({
            "material": material_name,
            "manual_images": sorted(set(_image_names(base))) if base is not None else [],
            "imported_images": sorted(set(current_images)),
            "issues": issues,
        })
    return comparisons


def _image_names(material_snapshot: dict | None) -> list[str]:
    if material_snapshot is None:
        return []
    return [
        image["image"]
        for image in material_snapshot.get("images", [])
        if image.get("image")
    ]


def _has_socket_target(links: list[dict], socket_name: str) -> bool:
    return any(link.get("to_socket") == socket_name for link in links)


def _has_mask_texture(material_snapshot: dict, mask: str) -> bool:
    return any(mask.lower() in (name or "").lower() for name in _image_names(material_snapshot))


def _has_matcap_texture(material_snapshot: dict) -> bool:
    names = " ".join(_image_names(material_snapshot)).lower()
    return any(token in names for token in ("materials1", "metallic2", "matcap"))


def _print_summary(comparisons: list[dict], report_path: str) -> None:
    issue_count = sum(len(item["issues"]) for item in comparisons)
    print(f"CALABIYAU_S103_SHADER_BASELINE_REPORT {report_path}")
    print(f"CALABIYAU_S103_SHADER_BASELINE_ISSUES {issue_count}")
    for item in comparisons:
        status = "FAIL" if item["issues"] else "PASS"
        print(f"{status} {item['material']}")
        for issue in item["issues"]:
            print(f"  - {issue}")


if __name__ == "__main__":
    raise SystemExit(main())
