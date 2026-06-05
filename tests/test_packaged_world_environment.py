import json
import os
import shutil
import sys

import bpy
import addon_utils


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
ZIP_PATH = os.path.join(ADDON_ROOT, "dist", "umodel_tools_next_manual_test.zip")
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "packaged_world_environment")


def main():
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(TEST_ROOT, exist_ok=True)

    if not os.path.isfile(ZIP_PATH):
        raise SystemExit(f"Missing package zip: {ZIP_PATH}")

    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]

    bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        import umodel_tools  # pylint: disable=import-error,import-outside-toplevel
        from umodel_tools import world_environment  # pylint: disable=import-error,import-outside-toplevel

        print(f"PACKAGED_ADDON_FILE {umodel_tools.__file__}")
        print(f"PACKAGED_WORLD_ENV_FILE {world_environment.__file__}")

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

        world = bpy.context.scene.world
        node_types = {node.bl_idname for node in world.node_tree.nodes} if world and world.node_tree else set()
        print(f"PACKAGED_WORLD_SOURCE {world.get('umodel_tools_environment_source') if world else None}")
        print(f"PACKAGED_WORLD_NODE_TYPES {sorted(node_types)}")
        if "ShaderNodeTexSky" not in node_types:
            raise AssertionError("Packaged add-on did not create a Sky Texture world node.")

        print("TEST_PACKAGED_WORLD_ENVIRONMENT_OK")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)


if __name__ == "__main__":
    main()
