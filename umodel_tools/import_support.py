"""Shared import support helpers.

This module is safe to import in normal Python; Blender-only APIs are imported
inside the functions that actually need them.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import functools
import os
import re
import shutil
import typing as t
import uuid


BASIC_DEFAULT = "BASIC_DEFAULT"
STRICT = "STRICT"
CUSTOM = "CUSTOM"


class AssetDB:
    """Class to edit and save Blender asset catalog database."""

    _version: int
    _catalogs: dict[str, tuple[str, str]]
    _db_cats_path: str

    def __init__(self, db_root_path: str) -> None:
        self._version = 1
        self._catalogs = {}
        self._db_cats_path = os.path.join(db_root_path, "blender_assets.cats.txt")
        self._open_db(db_root_path)

    def _open_db(self, db_root_path: str) -> None:
        if not os.path.exists(self._db_cats_path):
            os.makedirs(db_root_path, exist_ok=True)
            with open(self._db_cats_path, mode="w", encoding="utf-8") as f:
                f.writelines(f"VERSION {self._version}")
            return

        with open(self._db_cats_path, mode="r", encoding="utf-8") as f:
            for line in f.readlines():
                if not line or line.startswith("#") or line == "\n":
                    continue

                if len(components := line.split(":")) == 3:
                    uid, full_path, simple_path = components
                    self._catalogs[uid] = full_path, simple_path
                elif len(components := line.split(" ")) == 2 and components[0] == "VERSION":
                    self._version = components[1]
                else:
                    raise NotImplementedError()

    def uid_for_entry(self, dir_path: str) -> str:
        dir_path = dir_path.replace("\\", "/")

        for uid, (full_path, _) in self._catalogs.items():
            if full_path == dir_path:
                return uid

        uid = uuid.uuid1()
        assert uid.variant == uuid.RFC_4122

        self._catalogs[str(uid)] = dir_path, dir_path.replace("/", "-")
        return str(uid)

    def save_db(self) -> None:
        if not os.path.exists(self._db_cats_path):
            os.makedirs(os.path.dirname(self._db_cats_path), exist_ok=True)

        with open(self._db_cats_path, mode="w", encoding="utf-8") as f:
            f.write(f"VERSION {self._version}\n")

            for uid, (full_path, simple_path) in self._catalogs.items():
                f.write(f"{uid}:{full_path}:{simple_path}\n")

        shutil.copyfile(self._db_cats_path, f"{self._db_cats_path}~")


AssetDatabase = AssetDB
AssetIndex = AssetDB


@functools.lru_cache(maxsize=4096)
def path_cache_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def material_cache_is_current(material_lib_path: str, version_key: str, version: int) -> bool:
    if not os.path.isfile(material_lib_path):
        return False

    import bpy  # pylint: disable=import-outside-toplevel

    try:
        with bpy.data.libraries.load(filepath=material_lib_path, link=False) as (data_from, data_to):
            if not data_from.materials:
                return False
            data_to.materials = [data_from.materials[0]]

        material = data_to.materials[0]
        try:
            return int(material.get(version_key, 0)) == version
        finally:
            bpy.data.materials.remove(material, do_unlink=True)
    except Exception:
        return False


def asset_cache_is_current(asset_path_abs: str, version_key: str, version: int) -> bool:
    import bpy  # pylint: disable=import-outside-toplevel

    try:
        with bpy.data.libraries.load(filepath=asset_path_abs, link=False) as (data_from, data_to):
            if not data_from.objects:
                return False
            data_to.objects = [data_from.objects[0]]

        obj = data_to.objects[0]
        mesh = getattr(obj, "data", None)
        materials = list(mesh.materials) if mesh is not None and hasattr(mesh, "materials") else []
        current = int(obj.get(version_key, 0)) == version
        bpy.data.objects.remove(obj, do_unlink=True)
        try:
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh, do_unlink=True)
        except ReferenceError:
            pass
        for material in materials:
            try:
                if material is not None and material.users == 0:
                    bpy.data.materials.remove(material, do_unlink=True)
            except ReferenceError:
                pass
        return current
    except Exception:
        return False


class ImportCache:
    path_cache_key = staticmethod(path_cache_key)
    material_cache_is_current = staticmethod(material_cache_is_current)
    asset_cache_is_current = staticmethod(asset_cache_is_current)


def linked_library_cache_key(lib_filepath: str, dtype: type[t.Any]) -> tuple[str, str]:
    return (path_cache_key(lib_filepath), dtype.__name__)


def index_linked_libraries() -> dict[tuple[str, str], t.Any]:
    """Index Blender libraries once so cache misses stay O(1) during import."""

    import bpy  # pylint: disable=import-outside-toplevel

    cache: dict[tuple[str, str], t.Any] = {}
    for library in bpy.data.libraries:
        try:
            path_key = path_cache_key(bpy.path.abspath(library.filepath))
            users = library.users_id
        except ReferenceError:
            continue
        for data_block in users:
            cache.setdefault((path_key, type(data_block).__name__), data_block)
    return cache


def linked_libraries_search_cached(
    cache: dict[tuple[str, str], t.Any],
    lib_filepath: str,
    dtype: type[t.Any],
) -> t.Any | None:
    key = linked_library_cache_key(lib_filepath, dtype)
    cached = cache.get(key)
    if cached is not None:
        try:
            _ = cached.name
            return cached
        except ReferenceError:
            cache.pop(key, None)
    return None


def remember_linked_library(
    cache: dict[tuple[str, str], t.Any],
    lib_filepath: str,
    data_block: t.Any | None,
) -> None:
    if data_block is None:
        return
    cache[linked_library_cache_key(lib_filepath, type(data_block))] = data_block


def forget_linked_library(cache: dict[tuple[str, str], t.Any], lib_filepath: str) -> None:
    path_key = path_cache_key(lib_filepath)
    for key in [cache_key for cache_key in cache if cache_key[0] == path_key]:
        cache.pop(key, None)


def remove_loaded_material_library(material_lib_path: str) -> None:
    import bpy  # pylint: disable=import-outside-toplevel

    _remove_loaded_library_datablocks(material_lib_path, bpy.data.materials)


def remove_loaded_asset_library(asset_lib_path: str) -> None:
    import bpy  # pylint: disable=import-outside-toplevel

    _remove_loaded_library_datablocks(asset_lib_path, bpy.data.objects)


class LibraryLinker:
    linked_library_cache_key = staticmethod(linked_library_cache_key)
    index_linked_libraries = staticmethod(index_linked_libraries)
    linked_libraries_search_cached = staticmethod(linked_libraries_search_cached)
    remember_linked_library = staticmethod(remember_linked_library)
    forget_linked_library = staticmethod(forget_linked_library)
    remove_loaded_material_library = staticmethod(remove_loaded_material_library)
    remove_loaded_asset_library = staticmethod(remove_loaded_asset_library)


def _remove_loaded_library_datablocks(lib_path: str, datablocks: t.Iterable[t.Any]) -> None:
    import bpy  # pylint: disable=import-outside-toplevel

    normalized_path = os.path.normcase(os.path.abspath(lib_path))
    for data_block in list(datablocks):
        library = getattr(data_block, "library", None)
        if library is None:
            continue
        library_path = os.path.normcase(os.path.abspath(bpy.path.abspath(library.filepath)))
        if library_path == normalized_path:
            datablocks.remove(data_block, do_unlink=True)


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
    if source is None:
        try:
            from . import preferences  # pylint: disable=import-outside-toplevel

            source = preferences.get_addon_preferences()
        except Exception:
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


def validate_import_inputs(*paths: str) -> tuple[str, ...]:
    return tuple(path for path in paths if path and not os.path.exists(path))


def validate_import_result(
    scene: t.Any,
    settings: ImportValidationSettings | None = None,
    log_text: str | None = None,
) -> ImportValidationResult:
    settings = settings or get_import_validation_settings()
    counts = _count_import_result(scene)
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.enable_import_validation:
        return ImportValidationResult(True, counts, (), ())

    if counts["mesh_count"] < settings.min_mesh_count:
        errors.append(f"Mesh count {counts['mesh_count']} is below required minimum {settings.min_mesh_count}.")

    if counts["light_count"] < settings.min_light_count:
        errors.append(f"Light count {counts['light_count']} is below required minimum {settings.min_light_count}.")

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

    import bpy  # pylint: disable=import-outside-toplevel

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
    from . import localization  # pylint: disable=import-outside-toplevel

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
        operator.report({"WARNING"}, localization.t_report("Import finished with validation warnings. Check console for details."))

    return {"FINISHED"}


def _count_import_result(scene: t.Any) -> dict[str, int]:
    import bpy  # pylint: disable=import-outside-toplevel

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
    import bpy  # pylint: disable=import-outside-toplevel

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


def normalize_token(value: t.Any) -> str:
    return str(value).strip().lower()


def normalize_texture_name(tex_short_name: str) -> str:
    return normalize_token(os.path.basename(tex_short_name).lstrip("."))


def is_diffuse_texture_path(tex_path: str) -> bool:
    stem = os.path.splitext(os.path.basename(tex_path))[0].lower()
    return stem.endswith(("_d", "_d2", "_bc", "_basecolor", "_basecolour", "_diffuse", "_albedo"))


def texture_suffix(normalized_tex_name: str) -> str:
    return normalized_tex_name.rsplit("_", maxsplit=1)[-1]


def matches_texture_suffix(tex_short_name: str, suffixes: frozenset[str]) -> bool:
    normalized_name = normalize_texture_name(tex_short_name)
    if texture_suffix(normalized_name) in suffixes:
        return True

    return any(
        normalized_name == suffix or normalized_name.endswith(f"_{suffix}")
        for suffix in suffixes
        if "_" in suffix
    )


def matches_aware_name(normalized_tex_name: str,
                       basename_globs: tuple[str, ...],
                       basename_regexes: tuple[str, ...]) -> bool:
    if any(fnmatch.fnmatchcase(normalized_tex_name, pattern) for pattern in basename_globs):
        return True

    return any(
        re.search(pattern, normalized_tex_name, flags=re.IGNORECASE) is not None
        for pattern in basename_regexes
    )
