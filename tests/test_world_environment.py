import json
import math
import os
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MAP_PATH = os.path.join(ADDON_ROOT, "Envi_Wlbl.json")


def main():
    _use_source_addon_path()
    from umodel_tools import world_environment  # pylint: disable=import-error,import-outside-toplevel

    explicit_json = [{
        "Type": "SkyAtmosphereComponent",
        "Name": "SkyAtmosphereComponent0",
        "Properties": {
            "Brightness": 2.5,
            "SunElevation": 45.0,
            "SunRotation": 90.0,
            "Altitude": 1500.0,
            "AirDensity": 1.3,
            "AerosolDensity": 3.2,
            "OzoneDensity": 2.1,
        },
    }]

    settings = world_environment.infer_world_environment(explicit_json)
    if settings is None:
        raise AssertionError("Expected explicit sky settings to be inferred.")
    _assert_close(settings.brightness, 2.5)
    _assert_close(settings.sun_elevation, math.radians(45.0))
    _assert_close(settings.sun_rotation, math.radians(90.0))
    _assert_close(settings.altitude, 1500.0)
    _assert_close(settings.air_density, 1.3)
    _assert_close(settings.dust_density, 3.2)
    _assert_close(settings.ozone_density, 2.1)

    if not world_environment.apply_world_environment(bpy.context.scene, explicit_json):
        raise AssertionError("Expected explicit sky settings to create a Blender world.")
    _assert_world_sky(
        brightness=2.5,
        sun_elevation=math.radians(45.0),
        sun_rotation=math.radians(90.0),
        altitude=1500.0,
        air_density=1.3,
        dust_density=3.2,
        ozone_density=2.1,
    )

    fog_json = [{
        "Type": "ExponentialHeightFogComponent",
        "Name": "HeightFogComponent0",
        "Properties": {
            "FogDensity": 0.03,
            "FogInscatteringColor": {"R": 0.48, "G": 0.76, "B": 1.0, "A": 1.0},
        },
    }]
    fog_settings = world_environment.infer_world_environment(fog_json)
    if fog_settings is None or fog_settings.source != "exponential_height_fog":
        raise AssertionError(f"Expected fog fallback sky settings, got {fog_settings!r}.")
    if not world_environment.apply_world_environment(bpy.context.scene, fog_json):
        raise AssertionError("Expected fog settings to create a Blender world.")
    if bpy.context.scene.world["umodel_tools_environment_source"] != "exponential_height_fog":
        raise AssertionError("World did not record the fog fallback source.")

    if os.path.exists(MAP_PATH):
        with open(MAP_PATH, mode="r", encoding="utf-8") as file:
            wlbl_json = json.load(file)
        wlbl_settings = world_environment.infer_world_environment(wlbl_json)
        if wlbl_settings is None or wlbl_settings.source != "exponential_height_fog":
            raise AssertionError(f"Expected Wlbl to use the fog world fallback, got {wlbl_settings!r}.")

    print("TEST_WORLD_ENVIRONMENT_OK")


def _use_source_addon_path():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)


def _assert_world_sky(**expected_values):
    world = bpy.context.scene.world
    if world is None or not world.use_nodes:
        raise AssertionError("Scene world is not node based.")

    sky = next((node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeTexSky"), None)
    background = next((node for node in world.node_tree.nodes if node.bl_idname == "ShaderNodeBackground"), None)
    if sky is None or background is None:
        raise AssertionError("World is missing Sky Texture or Background node.")
    if not background.inputs["Color"].is_linked:
        raise AssertionError("Sky Texture should feed Background Color.")

    for attr_name, expected_value in expected_values.items():
        if attr_name == "brightness":
            _assert_close(background.inputs["Strength"].default_value, expected_value)
            _assert_close(sky.sun_intensity, expected_value)
        elif attr_name == "dust_density":
            _assert_close(_sky_density_attr(sky, "dust_density", "aerosol_density"), expected_value)
        else:
            _assert_close(getattr(sky, attr_name), expected_value)


def _sky_density_attr(sky, *attr_names):
    for attr_name in attr_names:
        if hasattr(sky, attr_name):
            return getattr(sky, attr_name)
    raise AssertionError(f"Sky node is missing all density attributes: {attr_names!r}")


def _assert_close(actual, expected, tolerance=1.0e-4):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{actual!r} != {expected!r}")


if __name__ == "__main__":
    main()
