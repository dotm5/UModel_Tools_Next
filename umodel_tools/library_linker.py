"""Linked Blender library datablock lookup and invalidation helpers."""

from __future__ import annotations

import os
import typing as t

import bpy

from . import import_cache
from . import utils


def linked_library_cache_key(lib_filepath: str, dtype: type[bpy.types.ID]) -> tuple[str, str]:
    return (import_cache.path_cache_key(lib_filepath), dtype.__name__)


def linked_libraries_search_cached(
    cache: dict[tuple[str, str], bpy.types.ID],
    lib_filepath: str,
    dtype: type[bpy.types.ID],
) -> bpy.types.ID | None:
    key = linked_library_cache_key(lib_filepath, dtype)
    cached = cache.get(key)
    if cached is not None:
        try:
            _ = cached.name
            return cached
        except ReferenceError:
            cache.pop(key, None)

    data_block = utils.linked_libraries_search(lib_filepath, dtype)
    if data_block is not None:
        cache[key] = data_block
    return data_block


def remember_linked_library(
    cache: dict[tuple[str, str], bpy.types.ID],
    lib_filepath: str,
    data_block: bpy.types.ID | None,
) -> None:
    if data_block is None:
        return
    cache[linked_library_cache_key(lib_filepath, type(data_block))] = data_block


def forget_linked_library(cache: dict[tuple[str, str], bpy.types.ID], lib_filepath: str) -> None:
    path_key = import_cache.path_cache_key(lib_filepath)
    for key in [cache_key for cache_key in cache if cache_key[0] == path_key]:
        cache.pop(key, None)


def remove_loaded_material_library(material_lib_path: str) -> None:
    _remove_loaded_library_datablocks(material_lib_path, bpy.data.materials)


def remove_loaded_asset_library(asset_lib_path: str) -> None:
    _remove_loaded_library_datablocks(asset_lib_path, bpy.data.objects)


def _remove_loaded_library_datablocks(lib_path: str, datablocks: t.Iterable[bpy.types.ID]) -> None:
    normalized_path = os.path.normcase(os.path.abspath(lib_path))
    for data_block in list(datablocks):
        library = getattr(data_block, "library", None)
        if library is None:
            continue
        library_path = os.path.normcase(os.path.abspath(bpy.path.abspath(library.filepath)))
        if library_path == normalized_path:
            datablocks.remove(data_block, do_unlink=True)
