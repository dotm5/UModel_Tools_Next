import contextlib
import io
import json
import os
import shutil
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UMODEL_EXPORT_DIR = os.path.join(ADDON_ROOT, "tests", "fixtures", "umodel_export_truncated_test")
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "local_single")
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

    map_path = os.path.join(TEST_ROOT, "local_single.json")
    cache_dir = os.path.join(TEST_ROOT, "asset_cache")
    os.makedirs(cache_dir, exist_ok=True)
    with open(map_path, "w", encoding="utf-8") as file:
        json.dump([{
            "Type": "StaticMeshComponent",
            "Name": "SM_Local",
            "Outer": "SM_Local_Outer",
            "Properties": {
                "StaticMesh": {"ObjectPath": VALID_MESH_OBJECT_PATH},
                "RelativeLocation": {"X": 0, "Y": 0, "Z": 0},
                "RelativeRotation": {"Roll": 0, "Pitch": 0, "Yaw": 0},
                "RelativeScale3D": {"X": 1, "Y": 1, "Z": 1},
                "bVisible": True,
            },
        }], file)

    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        clear_scene()
        prefs = bpy.context.preferences.addons["umodel_tools"].preferences
        profile = prefs.profiles.add()
        profile.name = "Local Single File Test"
        prefs.active_profile_index = len(prefs.profiles) - 1
        profile.game = "generic"
        profile.umodel_export_dir = UMODEL_EXPORT_DIR
        profile.asset_dir = cache_dir

        stdout_capture = Tee(sys.stdout)
        stderr_capture = Tee(sys.stderr)
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            result = bpy.ops.umodel_tools.import_unreal_map(
                filepath=map_path,
                umodel_export_dir=UMODEL_EXPORT_DIR,
                asset_cache_dir=cache_dir,
                import_storage_mode="LOCAL_SINGLE_FILE",
                path_inference_mode="BASIC_DEFAULT",
                missing_mesh_policy="WARN_SKIP",
                missing_material_policy="USE_PLACEHOLDER",
                missing_texture_policy="USE_PLACEHOLDER",
                validation_preset="BASIC_DEFAULT",
                enable_import_validation=True,
                min_mesh_count=1,
                report_path_resolution_stats=True,
                print_missing_asset_summary=True,
                save_missing_asset_report=False,
            )
            print(f"RESULT {result}")

        output = stdout_capture.getvalue() + stderr_capture.getvalue()
        if "RESULT {'FINISHED'}" not in output:
            raise AssertionError(f"LOCAL_SINGLE_FILE import failed:\n{output}")
        assert_no_traceback_markers(output)

        mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        if not mesh_objects:
            raise AssertionError("Expected at least one imported mesh object.")

        editable_material_found = False
        for obj in mesh_objects:
            if obj.library is not None:
                raise AssertionError(f"Object {obj.name!r} unexpectedly has linked library {obj.library!r}.")
            if obj.data.library is not None:
                raise AssertionError(f"Mesh data {obj.data.name!r} unexpectedly has linked library.")
            if obj.active_material is None:
                continue
            if obj.active_material.library is not None:
                raise AssertionError(f"Material {obj.active_material.name!r} unexpectedly has linked library.")
            obj.active_material.diffuse_color = (0.25, 0.5, 0.75, 1.0)
            editable_material_found = True

        if not editable_material_found:
            raise AssertionError("Expected at least one editable active material.")

        if "storage_mode=LOCAL_SINGLE_FILE" not in output:
            raise AssertionError("Import summary did not report LOCAL_SINGLE_FILE.")
        if "linked_object_count=0" not in output:
            raise AssertionError("LOCAL_SINGLE_FILE summary reported linked scene objects.")

        print("TEST_LOCAL_SINGLE_FILE_MODE_OK")
    finally:
        clear_scene()
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        bpy.ops.preferences.addon_disable(module="umodel_tools")


def clear_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def assert_no_traceback_markers(output):
    markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
    found = [marker for marker in markers if marker in output]
    if found:
        raise AssertionError(f"Import output contained traceback-like markers: {found!r}")


if __name__ == "__main__":
    main()
