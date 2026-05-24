"""Build Blender world shaders from Unreal map environment settings."""

from __future__ import annotations

import dataclasses
import math
import typing as t

import bpy


SKY_ENTITY_MARKERS = (
    "sky",
    "atmosphere",
    "worldsettings",
    "exponentialheightfog",
    "directionallight",
)

BRIGHTNESS_KEYS = (
    "brightness",
    "intensity",
    "sunintensity",
    "sunbrightness",
    "strength",
    "exposure",
)
SUN_ELEVATION_KEYS = (
    "sunelevation",
    "sunheight",
    "sunaltitude",
    "sunangle",
    "elevation",
)
SUN_ROTATION_KEYS = (
    "sunrotation",
    "sunazimuth",
    "azimuth",
    "rotation",
)
ALTITUDE_KEYS = (
    "altitude",
    "height",
)
AIR_KEYS = (
    "airdensity",
    "air",
)
DUST_KEYS = (
    "dustdensity",
    "aerosoldensity",
    "aerosol",
    "haze",
)
OZONE_KEYS = (
    "ozonedensity",
    "ozone",
)


@dataclasses.dataclass
class WorldEnvironmentSettings:
    """Procedural sky settings inferred from Unreal/FModel map JSON."""

    brightness: float = 1.0
    sun_elevation: float = math.radians(35.0)
    sun_rotation: float = 0.0
    altitude: float = 0.0
    air_density: float = 1.0
    dust_density: float = 1.0
    ozone_density: float = 1.0
    fog_color: tuple[float, float, float] | None = None
    source: str = ""


def apply_world_environment(scene: bpy.types.Scene, json_object: t.Any) -> bool:
    """Configure the scene world from Unreal sky/fog settings if present."""
    settings = infer_world_environment(json_object)
    if settings is None:
        return False

    world = scene.world or bpy.data.worlds.new(name="UModel Tools World")
    scene.world = world
    world.use_nodes = True
    world.color = settings.fog_color or (0.05, 0.08, 0.12)
    world["umodel_tools_environment_source"] = settings.source

    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputWorld")
    background = nodes.new(type="ShaderNodeBackground")
    sky = nodes.new(type="ShaderNodeTexSky")

    sky.sky_type = _supported_sky_type(sky, "NISHITA")
    _set_node_float(sky, "sun_intensity", settings.brightness)
    _set_node_float(sky, "sun_elevation", settings.sun_elevation)
    _set_node_float(sky, "sun_rotation", settings.sun_rotation)
    _set_node_float(sky, "altitude", settings.altitude)
    _set_node_float(sky, "air_density", settings.air_density)
    _set_first_node_float(sky, ("dust_density", "aerosol_density"), settings.dust_density)
    _set_node_float(sky, "ozone_density", settings.ozone_density)

    background.inputs["Strength"].default_value = max(settings.brightness, 0.0)
    links.new(sky.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])

    sky.location = (-420, 80)
    background.location = (-140, 80)
    output.location = (120, 80)
    return True


def infer_world_environment(json_object: t.Any) -> WorldEnvironmentSettings | None:
    """Infer a Blender procedural sky rule from Unreal map JSON."""
    if not isinstance(json_object, list):
        return None

    explicit_settings = _infer_explicit_sky_settings(json_object)
    if explicit_settings is not None:
        return explicit_settings

    return _infer_fog_sky_settings(json_object)


def _infer_explicit_sky_settings(json_object: list[dict[str, t.Any]]) -> WorldEnvironmentSettings | None:
    settings = WorldEnvironmentSettings(source="sky_settings")
    matched = False

    for entity in json_object:
        if not isinstance(entity, dict) or not _is_sky_related_entity(entity):
            continue

        values = _flatten_numeric_properties(entity.get("Properties", {}))
        if not values:
            continue

        matched |= _assign_first(settings, values, BRIGHTNESS_KEYS, "brightness")
        matched |= _assign_angle(settings, values, SUN_ELEVATION_KEYS, "sun_elevation")
        matched |= _assign_angle(settings, values, SUN_ROTATION_KEYS, "sun_rotation")
        matched |= _assign_first(settings, values, ALTITUDE_KEYS, "altitude")
        matched |= _assign_first(settings, values, AIR_KEYS, "air_density")
        matched |= _assign_first(settings, values, DUST_KEYS, "dust_density")
        matched |= _assign_first(settings, values, OZONE_KEYS, "ozone_density")

    if not matched:
        return None

    _clamp_settings(settings)
    return settings


def _infer_fog_sky_settings(json_object: list[dict[str, t.Any]]) -> WorldEnvironmentSettings | None:
    for entity in json_object:
        if not isinstance(entity, dict) or entity.get("Type") != "ExponentialHeightFogComponent":
            continue

        props = entity.get("Properties", {})
        settings = WorldEnvironmentSettings(source="exponential_height_fog")
        if (color := props.get("FogInscatteringColor")) is not None:
            settings.fog_color = _color_to_linear_rgb(color)

        fog_density = _safe_float(props.get("FogDensity"))
        if fog_density is not None:
            settings.air_density = _clamp(fog_density * 35.0, 0.0, 10.0)
            settings.dust_density = _clamp(fog_density * 120.0, 0.0, 10.0)
            settings.brightness = _clamp(1.0 + fog_density * 8.0, 0.1, 5.0)

        if settings.fog_color is not None or fog_density is not None:
            return settings

    return None


def _is_sky_related_entity(entity: dict[str, t.Any]) -> bool:
    haystack = " ".join(
        str(entity.get(key, ""))
        for key in ("Type", "Name", "Class")
    ).lower()
    return any(marker in haystack for marker in SKY_ENTITY_MARKERS)


def _flatten_numeric_properties(value: t.Any, prefix: str = "") -> dict[str, float]:
    values: dict[str, float] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalize_key(f"{prefix}{key}")
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                values[normalized] = float(item)
            elif isinstance(item, dict):
                values.update(_flatten_numeric_properties(item, normalized))
            elif isinstance(item, list):
                for list_item in item:
                    values.update(_flatten_numeric_properties(list_item, normalized))
    elif isinstance(value, list):
        for item in value:
            values.update(_flatten_numeric_properties(item, prefix))
    return values


def _assign_first(settings: WorldEnvironmentSettings,
                  values: dict[str, float],
                  keys: tuple[str, ...],
                  attr_name: str) -> bool:
    for key in keys:
        if key in values:
            setattr(settings, attr_name, values[key])
            return True
    return False


def _assign_angle(settings: WorldEnvironmentSettings,
                  values: dict[str, float],
                  keys: tuple[str, ...],
                  attr_name: str) -> bool:
    for key in keys:
        if key in values:
            setattr(settings, attr_name, _angle_to_radians(values[key]))
            return True
    return False


def _angle_to_radians(value: float) -> float:
    if abs(value) > math.tau:
        return math.radians(value)
    return value


def _color_to_linear_rgb(color: dict[str, t.Any]) -> tuple[float, float, float]:
    return (
        _srgb_to_linear(_color_channel(color, "R")),
        _srgb_to_linear(_color_channel(color, "G")),
        _srgb_to_linear(_color_channel(color, "B")),
    )


def _color_channel(color: dict[str, t.Any], channel: str) -> float:
    value = _safe_float(color.get(channel))
    if value is None:
        return 1.0
    if value > 1.0:
        value /= 255.0
    return _clamp(value, 0.0, 1.0)


def _srgb_to_linear(value: float) -> float:
    if value <= 0.0404482362771082:
        return value / 12.92
    return pow((value + 0.055) / 1.055, 2.4)


def _clamp_settings(settings: WorldEnvironmentSettings) -> None:
    settings.brightness = _clamp(settings.brightness, 0.0, 1000.0)
    settings.altitude = _clamp(settings.altitude, 0.0, 60000.0)
    settings.air_density = _clamp(settings.air_density, 0.0, 10.0)
    settings.dust_density = _clamp(settings.dust_density, 0.0, 10.0)
    settings.ozone_density = _clamp(settings.ozone_density, 0.0, 10.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(min(value, maximum), minimum)


def _safe_float(value: t.Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _normalize_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _set_node_float(node: bpy.types.Node, attr_name: str, value: float) -> None:
    if hasattr(node, attr_name):
        setattr(node, attr_name, value)


def _set_first_node_float(node: bpy.types.Node, attr_names: tuple[str, ...], value: float) -> None:
    for attr_name in attr_names:
        if hasattr(node, attr_name):
            setattr(node, attr_name, value)
            return


def _supported_sky_type(node: bpy.types.Node, preferred: str) -> str:
    prop = node.bl_rna.properties.get("sky_type")
    if prop is not None and preferred in {item.identifier for item in prop.enum_items}:
        return preferred
    return node.sky_type
