import dataclasses
import typing as t

import bpy

from . import preferences
from . import localization


BASIC_DEFAULT = "BASIC_DEFAULT"
STRICT = "STRICT"
CUSTOM = "CUSTOM"


@dataclasses.dataclass(frozen=True)
class ImportValidationSettings:
    enable_import_validation: bool = True
    validation_preset: str = BASIC_DEFAULT
    min_mesh_count: int = 1
    min_light_count: int = 0
    min_material_count: int = 0
    require_any_material_assigned: bool = False
    reject_dict_like_names: bool = True
    fail_on_traceback_like_errors: bool = True
    allow_missing_placeholder_materials: bool = True


@dataclasses.dataclass(frozen=True)
class ImportValidationResult:
    passed: bool
    counts: dict[str, int]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def get_import_validation_settings(source: t.Any = None) -> ImportValidationSettings:
    """Read validation settings from add-on preferences or a compatible object."""
    if source is None:
        try:
            source = preferences.get_addon_preferences()
        except Exception:  # pylint: disable=broad-exception-caught
            source = None

    preset = getattr(source, "validation_preset", BASIC_DEFAULT)

    if preset == STRICT:
        return ImportValidationSettings(
            enable_import_validation=getattr(source, "enable_import_validation", True),
            validation_preset=STRICT,
            min_mesh_count=max(getattr(source, "min_mesh_count", 1), 100),
            min_light_count=max(getattr(source, "min_light_count", 0), 30),
            min_material_count=max(getattr(source, "min_material_count", 0), 1),
            require_any_material_assigned=True,
            reject_dict_like_names=getattr(source, "reject_dict_like_names", True),
            fail_on_traceback_like_errors=getattr(source, "fail_on_traceback_like_errors", True),
            allow_missing_placeholder_materials=getattr(source, "allow_missing_placeholder_materials", True),
        )

    if preset == CUSTOM:
        return ImportValidationSettings(
            enable_import_validation=getattr(source, "enable_import_validation", True),
            validation_preset=CUSTOM,
            min_mesh_count=max(getattr(source, "min_mesh_count", 1), 0),
            min_light_count=max(getattr(source, "min_light_count", 0), 0),
            min_material_count=max(getattr(source, "min_material_count", 0), 0),
            require_any_material_assigned=getattr(source, "require_any_material_assigned", False),
            reject_dict_like_names=getattr(source, "reject_dict_like_names", True),
            fail_on_traceback_like_errors=getattr(source, "fail_on_traceback_like_errors", True),
            allow_missing_placeholder_materials=getattr(source, "allow_missing_placeholder_materials", True),
        )

    return ImportValidationSettings(
        enable_import_validation=getattr(source, "enable_import_validation", True),
        validation_preset=BASIC_DEFAULT,
        min_mesh_count=1,
        min_light_count=0,
        min_material_count=0,
        require_any_material_assigned=False,
        reject_dict_like_names=getattr(source, "reject_dict_like_names", True),
        fail_on_traceback_like_errors=getattr(source, "fail_on_traceback_like_errors", True),
        allow_missing_placeholder_materials=getattr(source, "allow_missing_placeholder_materials", True),
    )


def validate_import_result(
    scene: bpy.types.Scene,
    settings: ImportValidationSettings | None = None,
    log_text: str | None = None,
) -> ImportValidationResult:
    """Validate an imported scene with conservative defaults."""
    settings = settings or get_import_validation_settings()
    counts = _count_import_result(scene)
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.enable_import_validation:
        return ImportValidationResult(True, counts, (), ())

    if counts["mesh_count"] < settings.min_mesh_count:
        errors.append(
            f"Mesh count {counts['mesh_count']} is below required minimum {settings.min_mesh_count}."
        )

    if counts["light_count"] < settings.min_light_count:
        errors.append(
            f"Light count {counts['light_count']} is below required minimum {settings.min_light_count}."
        )

    if counts["material_count"] < settings.min_material_count:
        errors.append(
            f"Material count {counts['material_count']} is below required minimum {settings.min_material_count}."
        )

    if settings.require_any_material_assigned and counts["mesh_with_material_count"] == 0:
        errors.append("No imported mesh has an assigned material.")

    if settings.reject_dict_like_names:
        bad_names = _find_dict_like_names()
        if bad_names:
            errors.append(f"Found Blender datablock names that look like stringified dicts: {bad_names[:20]!r}")

    placeholder_count = sum(1 for mat in bpy.data.materials if mat.name.endswith("_Placeholder"))
    if placeholder_count:
        message = f"Import used {placeholder_count} placeholder material(s)."
        if settings.allow_missing_placeholder_materials:
            warnings.append(message)
        else:
            errors.append(message)

    if log_text and settings.fail_on_traceback_like_errors:
        traceback_markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
        found_traceback_markers = [marker for marker in traceback_markers if marker in log_text]
        if found_traceback_markers:
            errors.append(f"Import output contained traceback-like markers: {found_traceback_markers!r}")

    return ImportValidationResult(not errors, counts, tuple(errors), tuple(warnings))


def report_import_validation(operator: t.Any, result: ImportValidationResult) -> set[str]:
    """Report validation results through a Blender operator."""
    count_msg = (
        "Import validation counts: "
        f"mesh={result.counts['mesh_count']} "
        f"light={result.counts['light_count']} "
        f"material={result.counts['material_count']} "
        f"collection={result.counts['collection_count']}"
    )
    print(count_msg)

    for warning in result.warnings:
        print(f"Warning: {warning}")

    if result.errors:
        for error in result.errors:
            print(f"Error: {error}")
        operator.report({"ERROR"}, localization.t_report("Import validation failed. Check console for details."))
        return {"CANCELLED"}

    if result.warnings:
        operator.report(
            {"WARNING"},
            localization.t_report("Import finished with validation warnings. Check console for details."),
        )

    return {"FINISHED"}


def _count_import_result(scene: bpy.types.Scene) -> dict[str, int]:
    mesh_count = sum(1 for obj in scene.objects if obj.type == "MESH")
    light_count = sum(1 for obj in scene.objects if obj.type == "LIGHT")
    material_count = len(bpy.data.materials)
    collection_count = len(bpy.data.collections)
    mesh_with_material_count = sum(
        1 for obj in scene.objects
        if obj.type == "MESH" and obj.data.materials and any(obj.data.materials)
    )

    return {
        "mesh_count": mesh_count,
        "light_count": light_count,
        "material_count": material_count,
        "collection_count": collection_count,
        "mesh_with_material_count": mesh_with_material_count,
    }


def _find_dict_like_names() -> list[str]:
    bad_name_fragments = ("{'ObjectName':", '{"ObjectName":')
    bad_names: list[str] = []

    for container_name, datablocks in (
        ("object", bpy.data.objects),
        ("material", bpy.data.materials),
        ("light", bpy.data.lights),
    ):
        for datablock in datablocks:
            if any(fragment in datablock.name for fragment in bad_name_fragments):
                bad_names.append(f"{container_name}:{datablock.name}")

    return bad_names
