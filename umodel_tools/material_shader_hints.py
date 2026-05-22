"""Infer high-level Blender shader choices from Unreal material descriptors."""

from __future__ import annotations

import dataclasses
import os
import typing as t


Color: t.TypeAlias = tuple[float, float, float, float]


@dataclasses.dataclass(frozen=True)
class MaterialShaderHint:
    shader: str
    color: Color
    alpha: float
    roughness: float | None = None


def infer_shader_hint(material_name: str,
                      material_path_local: str,
                      parent_reference: str | None,
                      scalar_parameters: dict[str, float],
                      vector_parameters: dict[str, Color],
                      blend_mode: str | None) -> MaterialShaderHint | None:
    if not _looks_like_refractive_surface(material_name, material_path_local, parent_reference, scalar_parameters):
        return None

    if blend_mode == 'BLEND_Opaque (0)':
        return None

    alpha = _first_scalar(scalar_parameters, ("alphascale", "opacity"), default=0.35)

    return MaterialShaderHint(
        shader="glass",
        color=_first_color(vector_parameters, ("color", "basecolor", "basecolortint", "watercolor", "dconst")),
        alpha=_clamp(alpha),
        roughness=_first_scalar(scalar_parameters, ("roughness level", "roughness"), default=None),
    )


def _looks_like_refractive_surface(material_name: str,
                                   material_path_local: str,
                                   parent_reference: str | None,
                                   scalar_parameters: dict[str, float]) -> bool:
    haystack = " ".join(
        value for value in (material_name, material_path_local, parent_reference or "") if value
    ).replace("\\", "/").lower()

    path_parts = [part for part in haystack.split("/") if part]
    basename = os.path.splitext(os.path.basename(material_path_local))[0].lower()
    name_parts = basename.replace("-", "_").split("_")

    return (
        "glass" in path_parts
        or "water" in path_parts
        or "glass" in name_parts
        or "water" in name_parts
        or "refraction" in scalar_parameters
        or "frostedglass" in haystack
        or "glass_" in haystack
        or "_glass" in haystack
        or "water_" in haystack
        or "_water" in haystack
    )


def _first_color(values: dict[str, Color], names: t.Iterable[str]) -> Color:
    for name in names:
        value = values.get(name)
        if value is not None:
            return value

    return 1.0, 1.0, 1.0, 1.0


def _first_scalar(values: dict[str, float], names: t.Iterable[str], default: float | None) -> float | None:
    for name in names:
        value = values.get(name)
        if value is not None:
            return value

    return default


def _clamp(value: float | None) -> float:
    if value is None:
        return 1.0

    return min(max(float(value), 0.0), 1.0)
