from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parents[1] / "umodel_tools"
MAP_ASSET_CACHE_SOURCE = ADDON_ROOT / "map_asset_cache.py"
OLD_ASSET_IMPORTER_SOURCE = ADDON_ROOT / "asset_importer.py"


def _map_asset_cache_source() -> str:
    return MAP_ASSET_CACHE_SOURCE.read_text(encoding="utf-8")


def test_map_asset_cache_has_no_model_asset_storage_compatibility():
    # Source scan keeps this host-Python test independent from Blender's bpy module.
    source = _map_asset_cache_source()
    forbidden = (
        "_load_asset_as_local",
        "class AssetImporter",
        "APPEND_AS_LOCAL",
        "LOCAL_SINGLE_FILE",
        "append imported assets as editable",
        "Import Storage Mode",
    )
    hits = [token for token in forbidden if token in source]
    if hits:
        raise AssertionError(f"Model-asset compatibility helpers remain: {hits!r}")
    if "class MapAssetCache" not in source:
        raise AssertionError("MapAssetCache API is required for map import.")


def test_old_asset_importer_module_is_removed():
    if OLD_ASSET_IMPORTER_SOURCE.exists():
        raise AssertionError("Old asset_importer.py module should be removed after map-cache split.")
