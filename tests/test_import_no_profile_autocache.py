import json
import os
import shutil
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "no_profile_param_cache")


def main():
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(TEST_ROOT, exist_ok=True)
    params_cache_path = os.path.join(ADDON_ROOT, "umodel_tools", "last_import_params.json")
    if os.path.isfile(params_cache_path):
        os.remove(params_cache_path)

    sys.path.insert(0, ADDON_ROOT)
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        prefs = bpy.context.preferences.addons["umodel_tools"].preferences
        while len(prefs.profiles):
            prefs.profiles.remove(0)
        prefs.active_profile_index = 0

        export_dir = os.path.join(TEST_ROOT, "UmodelExport")
        cache_dir = os.path.join(export_dir, "temp-assets")
        manual_cache_dir = os.path.join(TEST_ROOT, "manual_asset_cache")
        map_path = os.path.join(TEST_ROOT, "empty_map.json")
        os.makedirs(export_dir, exist_ok=True)
        with open(map_path, "w", encoding="utf-8") as handle:
            json.dump([], handle)

        result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            umodel_export_dir=export_dir,
            game_profile="generic",
            import_storage_mode="LINKED_ASSET_LIBRARY",
            enable_import_validation=False,
            save_missing_asset_report=True,
        )
        print(f"RESULT {result}")
        if result != {"FINISHED"}:
            raise AssertionError(f"Expected FINISHED without active profile, got {result!r}")
        if not os.path.isdir(cache_dir):
            raise AssertionError(f"Asset cache directory was not created: {cache_dir}")
        if not os.path.isfile(params_cache_path):
            raise AssertionError(f"Import parameter cache was not created: {params_cache_path}")
        with open(params_cache_path, "r", encoding="utf-8") as handle:
            cached_params = json.load(handle)["params"]
        if cached_params["umodel_export_dir"] != export_dir:
            raise AssertionError("UModel export dir was not cached.")
        if "asset_cache_dir" in cached_params:
            raise AssertionError("Asset cache dir should not be cached when it is derived from UModel export dir.")
        if cached_params["game_profile"] != "generic":
            raise AssertionError("Game profile was not cached.")

        cached_result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            enable_import_validation=False,
            save_missing_asset_report=True,
        )
        print(f"CACHED_RESULT {cached_result}")
        if cached_result != {"FINISHED"}:
            raise AssertionError(f"Expected FINISHED using cached directories, got {cached_result!r}")

        prefs.manual_asset_cache_dir = manual_cache_dir
        manual_result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            umodel_export_dir=export_dir,
            enable_import_validation=False,
            save_missing_asset_report=True,
        )
        print(f"MANUAL_RESULT {manual_result}")
        if manual_result != {"FINISHED"}:
            raise AssertionError(f"Expected FINISHED using manual asset cache dir, got {manual_result!r}")
        if not os.path.isdir(manual_cache_dir):
            raise AssertionError(f"Manual asset cache directory was not created: {manual_cache_dir}")

        op = bpy.ops.umodel_tools.import_unreal_map
        rna = op.get_rna_type()
        if "game_profile" not in rna.properties:
            raise AssertionError("Import operator is missing game_profile")

        print("TEST_IMPORT_NO_PROFILE_PARAM_CACHE_OK")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        if os.path.isfile(params_cache_path):
            os.remove(params_cache_path)


if __name__ == "__main__":
    main()
