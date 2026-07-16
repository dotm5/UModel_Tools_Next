import importlib.util
import os
import sys
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "import_support.py")


def load_module():
    spec = importlib.util.spec_from_file_location("import_support_hotpaths_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_path_cache_key_memoizes_realpath(tmp_path):
    module = load_module()
    path = str(tmp_path / "asset.blend")
    module.path_cache_key.cache_clear()

    first = module.path_cache_key(path)
    second = module.path_cache_key(path)

    assert first == second
    assert module.path_cache_key.cache_info().hits == 1


def test_linked_library_index_seeds_lookup_without_rescan(tmp_path):
    module = load_module()

    class Object:
        def __init__(self, name):
            self.name = name

    class Material:
        def __init__(self, name):
            self.name = name

    filepath = str(tmp_path / "library.blend")
    linked_object = Object("Mesh")
    linked_material = Material("Material")
    fake_bpy = types.SimpleNamespace(
        data=types.SimpleNamespace(
            libraries=[types.SimpleNamespace(filepath=filepath, users_id=[linked_object, linked_material])]
        ),
        path=types.SimpleNamespace(abspath=lambda path: path),
    )
    original_bpy = sys.modules.get("bpy")
    sys.modules["bpy"] = fake_bpy
    try:
        module.path_cache_key.cache_clear()
        cache = module.index_linked_libraries()
        assert module.linked_libraries_search_cached(cache, filepath, Object) is linked_object
        assert module.linked_libraries_search_cached(cache, filepath, Material) is linked_material
        assert module.linked_libraries_search_cached(cache, str(tmp_path / "missing.blend"), Object) is None
    finally:
        if original_bpy is None:
            sys.modules.pop("bpy", None)
        else:
            sys.modules["bpy"] = original_bpy


def test_dead_cached_datablock_is_evicted(tmp_path):
    module = load_module()

    class DeadObject:
        @property
        def name(self):
            raise ReferenceError("removed")

    filepath = str(tmp_path / "library.blend")
    key = module.linked_library_cache_key(filepath, DeadObject)
    cache = {key: DeadObject()}

    assert module.linked_libraries_search_cached(cache, filepath, DeadObject) is None
    assert key not in cache
