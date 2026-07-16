import importlib.util
import os
import sys


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "cache_metadata.py")


def load_module():
    spec = importlib.util.spec_from_file_location("cache_metadata_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cache_metadata = load_module()


def test_metadata_roundtrip_and_dependency_change(tmp_path):
    cache = tmp_path / "asset.blend"
    source = tmp_path / "asset.pskx"
    cache.write_bytes(b"cache-v1")
    source.write_bytes(b"source-v1")

    cache_metadata.write_metadata(str(cache), 5, [str(source), str(source)], True)
    metadata = cache_metadata.load_current_metadata(str(cache), 5)

    assert metadata is not None
    assert len(metadata.dependencies) == 1
    assert cache_metadata.dependencies_changed(metadata) is False

    source.write_bytes(b"source-version-two")
    assert cache_metadata.dependencies_changed(metadata) is True


def test_incomplete_dependencies_keep_version_fast_path_only(tmp_path):
    cache = tmp_path / "asset.blend"
    cache.write_bytes(b"cache")
    cache_metadata.write_metadata(str(cache), 5, [], False)

    metadata = cache_metadata.load_current_metadata(str(cache), 5)
    assert metadata is not None
    assert cache_metadata.dependencies_changed(metadata) is None


def test_cache_or_schema_change_invalidates_metadata(tmp_path):
    cache = tmp_path / "asset.blend"
    source = tmp_path / "asset.psk"
    cache.write_bytes(b"cache")
    source.write_bytes(b"source")
    cache_metadata.write_metadata(str(cache), 5, [str(source)], True)

    assert cache_metadata.load_current_metadata(str(cache), 6) is None
    cache.write_bytes(b"changed-cache")
    assert cache_metadata.load_current_metadata(str(cache), 5) is None


def test_remove_metadata_is_idempotent(tmp_path):
    cache = tmp_path / "asset.blend"
    cache.write_bytes(b"cache")
    cache_metadata.write_metadata(str(cache), 5, [], True)

    cache_metadata.remove_metadata(str(cache))
    cache_metadata.remove_metadata(str(cache))
    assert not os.path.exists(cache_metadata.metadata_path(str(cache)))
