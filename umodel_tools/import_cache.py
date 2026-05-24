"""Blender asset-library cache checks used during imports."""

from __future__ import annotations

import os

import bpy


def path_cache_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def material_cache_is_current(material_lib_path: str, version_key: str, version: int) -> bool:
    if not os.path.isfile(material_lib_path):
        return False

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
    except Exception:  # pragma: no cover - corrupt cache should be rebuilt during interactive imports.
        return False


def asset_cache_is_current(asset_path_abs: str, version_key: str, version: int) -> bool:
    try:
        with bpy.data.libraries.load(filepath=asset_path_abs, link=False) as (data_from, data_to):
            if not data_from.objects:
                return False
            data_to.objects = [data_from.objects[0]]

        obj = data_to.objects[0]
        mesh = getattr(obj, "data", None)
        materials = list(mesh.materials) if mesh is not None and hasattr(mesh, "materials") else []
        try:
            return int(obj.get(version_key, 0)) == version
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh, do_unlink=True)
            for material in materials:
                if material is not None and material.users == 0:
                    bpy.data.materials.remove(material, do_unlink=True)
    except Exception:  # pragma: no cover - corrupt cache should be rebuilt during interactive imports.
        return False
