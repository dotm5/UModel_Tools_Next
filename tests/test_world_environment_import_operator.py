import json
import os
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "world_environment")


def main():
    _enable_source_addon()
    try:
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        os.makedirs(TEST_ROOT, exist_ok=True)

        map_path = os.path.join(TEST_ROOT, "world_fog.json")
        export_dir = os.path.join(TEST_ROOT, "UmodelExport")
        asset_cache_dir = os.path.join(TEST_ROOT, "asset_cache")
        os.makedirs(export_dir, exist_ok=True)
        with open(map_path, mode="w", encoding="utf-8") as file:
            json.dump([
                {
                    "Type": "ExponentialHeightFogComponent",
                    "Name": "HeightFogComponent0",
                    "Properties": {
                        "FogDensity": 0.03,
                        "FogInscatteringColor": {"R": 0.48, "G": 0.76, "B": 1.0, "A": 1.0},
                    },
                }
            ], file)

        result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            umodel_export_dir=export_dir,
            asset_cache_dir=asset_cache_dir,
            game_profile="generic",
            enable_import_validation=False,
            save_missing_asset_report=False,
        )
        if result != {"FINISHED"}:
            raise AssertionError(f"Expected FINISHED, got {result!r}.")

        _assert_world_environment(bpy.context.scene)

        print("TEST_WORLD_ENVIRONMENT_IMPORT_OPERATOR_OK")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)


def _assert_world_environment(scene):
    world = scene.world
    if world is None:
        raise AssertionError(f"Import did not assign a scene world for {scene.name!r}.")
    if world.get("umodel_tools_environment_source") != "exponential_height_fog":
        raise AssertionError(f"Import did not record the expected world environment source for {scene.name!r}.")

    node_types = {node.bl_idname for node in world.node_tree.nodes}
    if "ShaderNodeTexSky" not in node_types or "ShaderNodeBackground" not in node_types:
        raise AssertionError(f"Import did not create a procedural sky world for {scene.name!r}: {node_types!r}")


def _enable_source_addon():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")


if __name__ == "__main__":
    main()
