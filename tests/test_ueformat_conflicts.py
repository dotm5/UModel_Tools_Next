import json
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _is_umodel_tools_module(module_name):
    return module_name == "umodel_tools" or module_name.startswith("umodel_tools.")


@contextmanager
def _scoped_umodel_tools_package():
    saved_modules = {
        module_name: module
        for module_name, module in sys.modules.items()
        if _is_umodel_tools_module(module_name)
    }
    for module_name in list(saved_modules):
        sys.modules.pop(module_name, None)

    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools")]
    sys.modules["umodel_tools"] = fake_package
    try:
        yield
    finally:
        for module_name in list(sys.modules):
            if _is_umodel_tools_module(module_name):
                sys.modules.pop(module_name, None)
        sys.modules.update(saved_modules)


def _load_conflicts_module():
    with _scoped_umodel_tools_package():
        from umodel_tools.ueformat import conflicts

        return conflicts


conflicts = _load_conflicts_module()


def test_conflict_store_round_trips_project_local_override(tmp_path):
    cache_dir = tmp_path / "asset_cache"
    store = conflicts.UEFormatConflictStore(str(cache_dir))
    key = conflicts.ConflictKey(
        kind="material_json",
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        material_slot="MI_Body",
        parameter_name="",
        original_reference="/Game/A/MI_Body.MI_Body",
    )

    store.set_override(key, "PM/Content/A/MI_Body.json")
    store.save()

    loaded = conflicts.UEFormatConflictStore(str(cache_dir))
    assert loaded.get_override(key) == "PM/Content/A/MI_Body.json"
    assert Path(loaded.path).name == "umodel_tools_conflict_overrides.json"


def test_conflict_store_saves_candidates_without_override(tmp_path):
    store = conflicts.UEFormatConflictStore(str(tmp_path))
    key = conflicts.ConflictKey(
        kind="texture",
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        material_slot="MI_Body",
        parameter_name="BaseMap",
        original_reference="PM/Content/A/T_Body.T_Body",
    )

    store.record_conflict(
        key,
        status="ambiguous",
        candidates=["PM/Content/A/T_Body.png", "PM/Content/B/T_Body.png"],
    )
    store.save()

    payload = json.loads(Path(store.path).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["conflicts"][0]["status"] == "ambiguous"
    assert payload["conflicts"][0]["candidates"] == [
        "PM/Content/A/T_Body.png",
        "PM/Content/B/T_Body.png",
    ]


def test_conflict_store_preserves_override_when_conflict_refreshes(tmp_path):
    store = conflicts.UEFormatConflictStore(str(tmp_path))
    key = conflicts.ConflictKey(
        kind="texture",
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        material_slot="MI_Body",
        parameter_name="BaseMap",
        original_reference="PM/Content/A/T_Body.T_Body",
    )

    store.set_override(key, "PM/Content/A/T_Body.png")
    store.record_conflict(
        key,
        status="ambiguous",
        candidates=["PM/Content/A/T_Body.png", "PM/Content/B/T_Body.png"],
    )
    store.save()

    loaded = conflicts.UEFormatConflictStore(str(tmp_path))
    assert loaded.get_override(key) == "PM/Content/A/T_Body.png"
