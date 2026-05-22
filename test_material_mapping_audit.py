import csv
import importlib.util
import os
import sys
import tempfile


ADDON_ROOT = r"D:\addon"
EXPORT_DIR = r"D:\UmodelExport"
MAP_PATH_CANDIDATES = [
    os.path.join(EXPORT_DIR, "Envi_Wlbl.json"),
    os.path.join(ADDON_ROOT, "Envi_Wlbl.json"),
]
MAP_PATH = next((path for path in MAP_PATH_CANDIDATES if os.path.exists(path)), MAP_PATH_CANDIDATES[0])
SCRIPT_PATH = os.path.join(ADDON_ROOT, "scripts", "audit_material_mappings.py")


def main():
    audit = _load_module("audit_material_mappings_test", SCRIPT_PATH)
    rule_set = audit.material_rules.load_rule_set(audit.material_rules.default_rule_path("generic"))
    settings = audit.umodel_path_resolver.UModelPathInferenceSettings(
        enable_umodel_path_inference=True,
        path_inference_mode=audit.umodel_path_resolver.AGGRESSIVE,
        enable_suffix_index=True,
    )

    rows = audit.audit_map(
        map_path=MAP_PATH,
        export_dir=EXPORT_DIR,
        rule_set=rule_set,
        settings=settings,
        include_all=True,
    )

    water_row = _find_row(rows, "S_Envi_Wlbl_Indoor_01g", "MI_Envi_Wlbl_Water_01")
    if water_row["shader_plan"] != "glass":
        raise AssertionError(f"Expected water material to use glass shader: {water_row}")
    if water_row["fallback_reason"]:
        raise AssertionError(f"Water material should not be suspicious: {water_row}")
    if water_row["node_summary"] != "glass.BSDF->output.Surface":
        raise AssertionError(f"Unexpected water node summary: {water_row['node_summary']!r}")
    if water_row["map_file"] != MAP_PATH:
        raise AssertionError(f"Expected map_file to be populated: {water_row['map_file']!r}")

    glass_row = _find_row(rows, "S_Envi_Wlbl_Indoor_01k_5", "MI_PM_Glass_03b")
    if glass_row["shader_plan"] != "glass":
        raise AssertionError(f"Expected glass material to use glass shader: {glass_row}")
    if "mix_shader.Fac=0.8" not in glass_row["node_summary"]:
        raise AssertionError(f"Expected transparent glass mix summary: {glass_row['node_summary']!r}")

    mouse_row = _find_row(rows, "S_Envi_Wlbl_Mouse_02a_26", "MI_Envi_Wlbl_Mouse_02a")
    if mouse_row["blend_mode"] != "BLEND_Opaque (0)":
        raise AssertionError(f"Expected mouse material to be opaque: {mouse_row}")
    if "D:image.Alpha->bsdf.Alpha" in mouse_row["node_summary"]:
        raise AssertionError(f"Opaque packed diffuse alpha should not feed BSDF alpha: {mouse_row}")
    if "D:image.Alpha->bsdf.Emission Strength" not in mouse_row["node_summary"]:
        raise AssertionError(f"Opaque packed diffuse alpha should feed emission strength: {mouse_row}")

    suspicious_rows = [
        row for row in rows
        if row["fallback_reason"] and row["shader_plan"] != "glass"
    ]
    if not suspicious_rows:
        raise AssertionError("Expected at least one suspicious material mapping row.")

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", delete=False) as temp_csv:
        writer = csv.DictWriter(temp_csv, fieldnames=audit.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(row for row in rows if row["fallback_reason"])
        csv_path = temp_csv.name

    try:
        with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as csv_file:
            loaded = list(csv.DictReader(csv_file))
        if not loaded:
            raise AssertionError("Suspicious CSV export should contain rows.")
    finally:
        os.remove(csv_path)

    print("TEST_MATERIAL_MAPPING_AUDIT_OK")


def _find_row(rows, actor_name, material_name):
    for row in rows:
        if row["actor_name"] == actor_name and row["material_name"] == material_name:
            return row
    raise AssertionError(f"Missing audit row for {actor_name!r} / {material_name!r}")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if not os.path.exists(MAP_PATH):
        raise SystemExit(f"Missing test fixture: {MAP_PATH}")
    main()
