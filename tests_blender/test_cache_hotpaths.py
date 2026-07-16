import os
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "cache_hotpaths")
VERSION_KEY = "umodel_tools_asset_cache_version"


def main():
    _clean_test_root()
    os.makedirs(TEST_ROOT, exist_ok=True)
    _enable_addon()
    try:
        test_asset_cache_version_probe_cleanup()
        test_preloaded_library_index()
        print("TEST_CACHE_HOTPATHS_OK")
    finally:
        _clear_data()
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        _clean_test_root()


def test_asset_cache_version_probe_cleanup():
    from umodel_tools import import_support  # pylint: disable=import-error,import-outside-toplevel

    filepath = os.path.join(TEST_ROOT, "versioned_asset.blend")
    _write_versioned_asset(filepath)

    if not import_support.asset_cache_is_current(filepath, VERSION_KEY, 5):
        raise AssertionError("Current cache version was rejected after probe cleanup.")
    if import_support.asset_cache_is_current(filepath, VERSION_KEY, 6):
        raise AssertionError("Mismatched cache version was accepted.")
    print("TEST_ASSET_CACHE_VERSION_PROBE_OK")


def test_preloaded_library_index():
    from umodel_tools import import_support  # pylint: disable=import-error,import-outside-toplevel

    filepath = os.path.join(TEST_ROOT, "linked_asset.blend")
    _write_versioned_asset(filepath)
    with bpy.data.libraries.load(filepath=filepath, link=True) as (data_from, data_to):
        data_to.objects = [data_from.objects[0]]
    linked_object = data_to.objects[0]

    import_support.path_cache_key.cache_clear()
    cache = import_support.index_linked_libraries()
    found = import_support.linked_libraries_search_cached(cache, filepath, bpy.types.Object)
    if found != linked_object:
        raise AssertionError("Preloaded linked object was not found in the one-time library index.")
    print("TEST_PRELOADED_LIBRARY_INDEX_OK")


def _write_versioned_asset(filepath):
    mesh = bpy.data.meshes.new("CacheHotpathMesh")
    material = bpy.data.materials.new("CacheHotpathMaterial")
    mesh.materials.append(material)
    obj = bpy.data.objects.new("CacheHotpathObject", mesh)
    obj[VERSION_KEY] = 5
    bpy.context.scene.collection.objects.link(obj)
    bpy.data.libraries.write(filepath, {obj}, fake_user=True)
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh, do_unlink=True)
    try:
        if material.users == 0:
            bpy.data.materials.remove(material, do_unlink=True)
    except ReferenceError:
        pass


def _enable_addon():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")


def _clear_data():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh, do_unlink=True)
    for material in list(bpy.data.materials):
        if material.users == 0:
            bpy.data.materials.remove(material, do_unlink=True)


def _clean_test_root():
    resolved = os.path.abspath(TEST_ROOT)
    if os.path.isdir(resolved) and resolved.startswith(os.path.abspath(ADDON_ROOT)):
        shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
