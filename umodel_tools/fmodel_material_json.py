"""FModel material JSON adapter for the shared material import pipeline."""

from __future__ import annotations

import dataclasses
import json
import os
import typing as t


Color: t.TypeAlias = tuple[float, float, float, float]


BLEND_MODE_LABELS = {
    0: "BLEND_Opaque (0)",
    1: "BLEND_Masked (1)",
    2: "BLEND_Translucent (2)",
    3: "BLEND_Additive (3)",
    4: "BLEND_Modulate (4)",
}


@dataclasses.dataclass(frozen=True)
class MaterialDescription:
    material_name: str
    material_path_local: str
    texture_infos: dict[str, str]
    base_prop_overrides: dict[str, str | float | bool]
    parent_reference: str | None = None
    scalar_parameters: dict[str, float] = dataclasses.field(default_factory=dict)
    vector_parameters: dict[str, Color] = dataclasses.field(default_factory=dict)
    static_switch_parameters: dict[str, bool] = dataclasses.field(default_factory=dict)

    @property
    def blend_mode(self) -> str | None:
        value = self.base_prop_overrides.get("BlendMode")
        return str(value) if value is not None else None


def load_material_description(json_path: str,
                              material_name: str | None = None,
                              material_path_local: str | None = None) -> MaterialDescription:
    with open(json_path, "r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    if isinstance(raw_data, list):
        return _from_fmodel_export_array(raw_data, json_path, material_name, material_path_local)
    if isinstance(raw_data, dict):
        return _from_texture_dictionary(raw_data, json_path, material_name, material_path_local)

    raise RuntimeError(f"Unsupported FModel material JSON shape in {json_path}.")


def json_path_from_material_reference(material_reference: str) -> str:
    reference = material_reference.replace("\\", "/").strip()
    if "." in os.path.basename(reference):
        reference = reference[:reference.rfind(".")]
    return os.path.normpath(reference + ".json")


def _from_texture_dictionary(raw_data: dict[str, t.Any],
                             json_path: str,
                             material_name: str | None,
                             material_path_local: str | None) -> MaterialDescription:
    parameters = raw_data.get("Parameters", {}) if isinstance(raw_data.get("Parameters", {}), dict) else {}
    properties = parameters.get("Properties", {}) if isinstance(parameters.get("Properties", {}), dict) else {}
    base_overrides = properties.get("BasePropertyOverrides", {})
    if not isinstance(base_overrides, dict):
        base_overrides = {}

    blend_mode = parameters.get("BlendMode")
    base_prop_overrides: dict[str, str | float | bool] = {}
    if blend_mode is not None:
        try:
            base_prop_overrides["BlendMode"] = BLEND_MODE_LABELS.get(int(blend_mode), str(blend_mode))
        except (TypeError, ValueError):
            base_prop_overrides["BlendMode"] = str(blend_mode)

    if "TwoSided" in base_overrides:
        base_prop_overrides["TwoSided"] = bool(base_overrides["TwoSided"])
    if "ShadingModel" in base_overrides:
        base_prop_overrides["ShadingModel"] = str(base_overrides["ShadingModel"])
    if "OpacityMaskClipValue" in base_overrides:
        try:
            base_prop_overrides["OpacityMaskClipValue"] = float(base_overrides["OpacityMaskClipValue"])
        except (TypeError, ValueError):
            pass

    textures = raw_data.get("Textures", {})
    texture_infos = {
        str(name): str(path)
        for name, path in textures.items()
        if isinstance(textures, dict) and path
    }

    return MaterialDescription(
        material_name=material_name or os.path.splitext(os.path.basename(json_path))[0],
        material_path_local=material_path_local or _path_local_from_json_path(json_path),
        texture_infos=texture_infos,
        base_prop_overrides=base_prop_overrides,
        parent_reference=_optional_str(raw_data.get("Parent")),
        scalar_parameters=_parse_scalars(parameters.get("Scalars", {})),
        vector_parameters=_parse_colors(parameters.get("Colors", {})),
        static_switch_parameters=_parse_switches(parameters.get("Switches", {})),
    )


def _from_fmodel_export_array(raw_data: list[t.Any],
                              json_path: str,
                              material_name: str | None,
                              material_path_local: str | None) -> MaterialDescription:
    entry = raw_data[0] if raw_data and isinstance(raw_data[0], dict) else {}
    props = entry.get("Properties", {}) if isinstance(entry.get("Properties", {}), dict) else {}
    textures: dict[str, str] = {}
    for texture_param in props.get("TextureParameterValues", []) or []:
        if not isinstance(texture_param, dict):
            continue
        parameter_info = texture_param.get("ParameterInfo", {})
        parameter_name = parameter_info.get("Name") if isinstance(parameter_info, dict) else None
        parameter_value = texture_param.get("ParameterValue", {})
        object_path = parameter_value.get("ObjectPath") if isinstance(parameter_value, dict) else None
        if parameter_name and object_path:
            textures[str(parameter_name)] = str(object_path)

    base_prop_overrides = {}
    raw_overrides = props.get("BasePropertyOverrides", {})
    if isinstance(raw_overrides, dict):
        for key in ("BlendMode", "TwoSided", "OpacityMaskClipValue", "ShadingModel"):
            if key in raw_overrides:
                base_prop_overrides[key] = raw_overrides[key]

    return MaterialDescription(
        material_name=material_name or os.path.splitext(os.path.basename(json_path))[0],
        material_path_local=material_path_local or _path_local_from_json_path(json_path),
        texture_infos=textures,
        base_prop_overrides=base_prop_overrides,
        parent_reference=_object_path(props.get("Parent")),
        scalar_parameters={},
        vector_parameters={},
        static_switch_parameters={},
    )


def _parse_scalars(values: t.Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    parsed = {}
    for key, value in values.items():
        try:
            parsed[str(key).lower()] = float(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _parse_colors(values: t.Any) -> dict[str, Color]:
    if not isinstance(values, dict):
        return {}
    parsed = {}
    for key, value in values.items():
        if not isinstance(value, dict):
            continue
        try:
            parsed[str(key).lower()] = (
                float(value.get("R", 1.0)),
                float(value.get("G", 1.0)),
                float(value.get("B", 1.0)),
                float(value.get("A", 1.0)),
            )
        except (TypeError, ValueError):
            continue
    return parsed


def _parse_switches(values: t.Any) -> dict[str, bool]:
    if not isinstance(values, dict):
        return {}
    return {str(key).lower(): bool(value) for key, value in values.items()}


def _optional_str(value: t.Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def _object_path(value: t.Any) -> str | None:
    if isinstance(value, dict):
        object_path = value.get("ObjectPath")
        return str(object_path) if object_path else None
    return _optional_str(value)


def _path_local_from_json_path(json_path: str) -> str:
    return os.path.normpath(json_path)
