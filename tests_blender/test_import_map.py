import contextlib
import io
import os
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MAP_PATH = os.path.join(ADDON_ROOT, "tests", "fixtures", "map_import_samples", "Envi_Wlbl.json")
UMODEL_EXPORT_DIR = os.environ.get("UMODEL_TEST_EXPORT_DIR", r"D:\UmodelExport")
ASSET_CACHE_DIR = os.path.join(ADDON_ROOT, "tests", "runtime", "blender_wlbl", "asset_cache_backend")


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
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        clear_scene()
        os.makedirs(ASSET_CACHE_DIR, exist_ok=True)
        stdout_capture = Tee(sys.stdout)
        stderr_capture = Tee(sys.stderr)
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            result = bpy.ops.umodel_tools.import_unreal_map(
                filepath=MAP_PATH,
                umodel_export_dir=UMODEL_EXPORT_DIR,
                asset_cache_dir=ASSET_CACHE_DIR,
                game_profile="generic",
                path_inference_mode="BASIC_DEFAULT",
                missing_mesh_policy="WARN_SKIP",
                missing_material_policy="USE_PLACEHOLDER",
                missing_texture_policy="USE_PLACEHOLDER",
                validation_preset="BASIC_DEFAULT",
                enable_import_validation=True,
                min_mesh_count=1,
                report_path_resolution_stats=True,
                print_missing_asset_summary=True,
                save_missing_asset_report=True,
            )
            print(f"RESULT {result}")

        output = stdout_capture.getvalue() + stderr_capture.getvalue()
        if result != {"FINISHED"}:
            raise AssertionError(f"Map import failed:\n{output}")
        assert_no_traceback_markers(output)

        mesh_count = len([obj for obj in bpy.context.scene.objects if obj.type == "MESH"])
        if mesh_count <= 0:
            raise AssertionError("Expected imported map to contain at least one mesh object.")

        print(f"TEST_IMPORT_MAP_OK mesh_count={mesh_count}")
    finally:
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
