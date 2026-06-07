import contextlib
import csv
import io
import json
import os
import re
import shutil
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UMODEL_EXPORT_DIR = os.path.join(ADDON_ROOT, "tests", "fixtures", "umodel_export_truncated_test")
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "missing_report")
VALID_MESH_OBJECT_PATH = (
    "/PM/Content/PaperMan/Environment/Meshes/Foliage/"
    "S_Envi_common_flowerpot_01a.S_Envi_common_flowerpot_01a"
)


class Tee(io.StringIO):
    def __init__(self, target):
        super().__init__()
        self.target = target

    def write(self, text):
        self.target.write(text)
        return super().write(text)

    def flush(self):
        self.target.flush()
        return super().flush()

    def fileno(self):
        return self.target.fileno()


def main():
    sys.path.insert(0, ADDON_ROOT)
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(TEST_ROOT, exist_ok=True)
    cleanup_report_csvs()

    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        prefs = bpy.context.preferences.addons["umodel_tools"].preferences

        missing_output = run_case(
            case_name="reporttest_missing_mesh",
            mesh_paths=[
                VALID_MESH_OBJECT_PATH,
                missing_mesh_path(1),
            ],
            missing_mesh_policy="WARN_SKIP",
            min_mesh_count=1,
        )
        assert_result(missing_output, "RESULT {'FINISHED'}")
        assert_no_traceback_markers(missing_output)
        csv_path = extract_csv_path(missing_output)
        if not csv_path.startswith(UMODEL_EXPORT_DIR):
            raise AssertionError(f"CSV was not saved under UModel export dir: {csv_path}")
        rows = read_csv_rows(csv_path)
        assert_csv_core_fields(rows)
        if not any(row["resource_type"] == "mesh" and row["fallback_used"] == "skipped_instance" for row in rows):
            raise AssertionError("Missing mesh row with skipped_instance fallback was not found.")
        if not any(row["resource_type"] == "texture" and row["fallback_used"] == "placeholder_color" for row in rows):
            raise AssertionError("Missing texture row with placeholder_color fallback was not found.")
        if not any(row["actor_name"] == "Actor_1" for row in rows):
            raise AssertionError("CSV did not preserve actor_name context for missing mesh.")
        if "Skipped instances: 1" not in missing_output:
            raise AssertionError("Console summary did not include skipped instance count.")

        many_output = run_case(
            case_name="reporttest_many_missing",
            mesh_paths=[missing_mesh_path(index) for index in range(35)],
            missing_mesh_policy="WARN_SKIP",
            min_mesh_count=0,
            max_console_rows=30,
        )
        assert_result(many_output, "RESULT {'FINISHED'}")
        assert_no_traceback_markers(many_output)
        many_csv_path = extract_csv_path(many_output)
        many_rows = read_csv_rows(many_csv_path)
        mesh_rows = [row for row in many_rows if row["resource_type"] == "mesh"]
        if len(mesh_rows) != 35:
            raise AssertionError(f"Expected 35 missing mesh CSV rows, got {len(mesh_rows)}.")
        if "[UModelTools] First 30 missing assets:" not in many_output:
            raise AssertionError("Console did not cap printed missing assets at 30.")
        if "Remaining 5 missing assets are written to CSV." not in many_output:
            raise AssertionError("Console did not report remaining missing assets.")
        printed_rows = len(re.findall(r"^\d\d\. \[mesh\]", many_output, flags=re.MULTILINE))
        if printed_rows != 30:
            raise AssertionError(f"Expected 30 printed mesh rows, got {printed_rows}.")

        no_missing_output = run_case(
            case_name="reporttest_no_missing",
            mesh_paths=[],
            missing_mesh_policy="WARN_SKIP",
            min_mesh_count=0,
        )
        assert_result(no_missing_output, "RESULT {'FINISHED'}")
        assert_no_traceback_markers(no_missing_output)
        if "[UModelTools] No missing assets detected." not in no_missing_output:
            raise AssertionError("No-missing case did not print the expected summary.")
        if "Full missing asset report:" in no_missing_output:
            raise AssertionError("No-missing case unexpectedly generated a CSV report.")

        strict_output = run_case(
            case_name="reporttest_strict_missing",
            mesh_paths=[missing_mesh_path(99)],
            missing_mesh_policy="FAIL_IMPORT",
            min_mesh_count=0,
        )
        assert_result(strict_output, "RESULT {'CANCELLED'}")
        assert_no_traceback_markers(strict_output)
        strict_csv_path = extract_csv_path(strict_output)
        strict_rows = read_csv_rows(strict_csv_path)
        if not strict_rows or strict_rows[0]["severity"] != "error":
            raise AssertionError("Strict failure CSV did not record an error-severity missing asset.")

        print(f"TEST_MISSING_ASSET_REPORT_CSV {csv_path}")
        print(f"TEST_MISSING_ASSET_REPORT_MANY_CSV {many_csv_path}")
        print(f"TEST_MISSING_ASSET_REPORT_STRICT_CSV {strict_csv_path}")
        print("TEST_MISSING_ASSET_REPORT_OK")
    finally:
        cleanup_report_csvs()
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        bpy.ops.preferences.addon_disable(module="umodel_tools")


def run_case(
    case_name,
    mesh_paths,
    missing_mesh_policy,
    min_mesh_count,
    max_console_rows=30,
):
    clear_scene()
    map_path = write_map(case_name, mesh_paths)
    cache_dir = os.path.join(TEST_ROOT, case_name, "asset_cache")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)

    stdout_capture = Tee(sys.stdout)
    stderr_capture = Tee(sys.stderr)
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        try:
            result = bpy.ops.umodel_tools.import_unreal_map(
                filepath=map_path,
                umodel_export_dir=UMODEL_EXPORT_DIR,
                asset_cache_dir=cache_dir,
                path_inference_mode="BASIC_DEFAULT",
                missing_mesh_policy=missing_mesh_policy,
                missing_material_policy="USE_PLACEHOLDER",
                missing_texture_policy="USE_PLACEHOLDER",
                validation_preset="CUSTOM",
                enable_import_validation=min_mesh_count > 0,
                min_mesh_count=min_mesh_count,
                min_light_count=0,
                min_material_count=0,
                max_missing_assets_printed_to_console=max_console_rows,
                save_missing_asset_report=True,
                missing_asset_report_format="CSV",
                deduplicate_missing_assets=True,
                missing_asset_report_directory_mode="UMODEL_EXPORT",
                include_actor_context_in_missing_report=True,
                report_path_resolution_stats=True,
                save_paths_as_recent=False,
            )
        except RuntimeError as exc:
            if "Map import failed" not in str(exc):
                raise
            result = {'CANCELLED'}
            print(f"EXPECTED_RUNTIME_ERROR {exc}")
        print(f"RESULT {result}")

    output = stdout_capture.getvalue() + stderr_capture.getvalue()
    print(f"TEST_MISSING_ASSET_REPORT_CASE {case_name}")
    print(output)
    return output


def write_map(case_name, mesh_paths):
    entities = []
    for index, mesh_path in enumerate(mesh_paths):
        entities.append({
            "Type": "StaticMeshComponent",
            "Name": f"Actor_{index}",
            "Outer": f"Actor_{index}_Outer",
            "ObjectPath": f"/Game/Test/Actor_{index}.Actor_{index}",
            "Properties": {
                "StaticMesh": {"ObjectPath": mesh_path},
                "RelativeLocation": {"X": index * 100, "Y": 0, "Z": 0},
                "RelativeRotation": {"Roll": 0, "Pitch": 0, "Yaw": 0},
                "RelativeScale3D": {"X": 1, "Y": 1, "Z": 1},
                "bVisible": True,
            },
        })

    map_path = os.path.join(TEST_ROOT, f"{case_name}.json")
    with open(map_path, "w", encoding="utf-8") as file:
        json.dump(entities, file)
    return map_path


def missing_mesh_path(index):
    return (
        "/PM/Content/PaperMan/Environment/Meshes/MissingReport/"
        f"S_Missing_Report_{index:03d}.S_Missing_Report_{index:03d}"
    )


def extract_csv_path(output):
    match = re.search(r"([A-Z]:\\[^\r\n]+umodel_tools_missing_assets_[^\r\n]+\.csv)", output)
    if match is None:
        raise AssertionError("CSV report path was not printed.")
    csv_path = match.group(1).strip()
    if not os.path.isfile(csv_path):
        raise AssertionError(f"CSV report does not exist: {csv_path}")
    return csv_path


def read_csv_rows(csv_path):
    with open(csv_path, mode="r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def assert_csv_core_fields(rows):
    if not rows:
        raise AssertionError("CSV report was empty.")
    required_fields = {
        "map_name",
        "resource_type",
        "severity",
        "policy",
        "json_asset_path",
        "normalized_asset_path",
        "attempted_extensions",
        "resolution_status",
        "expected_path",
        "resolved_candidate_count",
        "actor_name",
        "actor_object_path",
        "component_name",
        "component_object_path",
        "instance_index",
        "material_name",
        "texture_parameter_name",
        "fallback_used",
        "message",
        "occurrence_count",
        "first_actor_name",
        "first_component_name",
    }
    missing = required_fields - set(rows[0].keys())
    if missing:
        raise AssertionError(f"CSV missing required fields: {sorted(missing)!r}")


def cleanup_report_csvs():
    if not os.path.isdir(UMODEL_EXPORT_DIR):
        return
    for file_name in os.listdir(UMODEL_EXPORT_DIR):
        if file_name.startswith("umodel_tools_missing_assets_reporttest") and file_name.endswith(".csv"):
            os.remove(os.path.join(UMODEL_EXPORT_DIR, file_name))


def clear_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def assert_result(output, expected):
    if expected not in output:
        raise AssertionError(f"Expected {expected!r} in output.")


def assert_no_traceback_markers(output):
    markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
    found = [marker for marker in markers if marker in output]
    if found:
        raise AssertionError(f"Import output contained traceback-like markers: {found!r}")


if __name__ == "__main__":
    main()
