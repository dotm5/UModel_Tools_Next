import importlib.util
import os
import sys
import types
from contextlib import contextmanager


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


def _load_asset_context_class():
    with _scoped_umodel_tools_package():
        from umodel_tools.ueformat.asset_context import UEFormatAssetContext

        return UEFormatAssetContext


UEFormatAssetContext = _load_asset_context_class()


def test_scoped_asset_context_import_restores_umodel_tools_modules():
    saved_modules = {
        module_name: module
        for module_name, module in sys.modules.items()
        if _is_umodel_tools_module(module_name)
    }
    for module_name in list(saved_modules):
        sys.modules.pop(module_name, None)

    sentinel_package = types.ModuleType("umodel_tools")
    sentinel_child = types.ModuleType("umodel_tools.existing")
    sys.modules["umodel_tools"] = sentinel_package
    sys.modules["umodel_tools.existing"] = sentinel_child
    try:
        loaded_context = _load_asset_context_class()

        assert loaded_context.__name__ == "UEFormatAssetContext"
        assert sys.modules["umodel_tools"] is sentinel_package
        assert sys.modules["umodel_tools.existing"] is sentinel_child
        assert "umodel_tools.ueformat.asset_context" not in sys.modules
    finally:
        for module_name in list(sys.modules):
            if _is_umodel_tools_module(module_name):
                sys.modules.pop(module_name, None)
        sys.modules.update(saved_modules)


def test_context_round_trips_through_plain_dict():
    context = UEFormatAssetContext(
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        source_filepath="D:/exports/PM/Content/A/Model.uemodel",
        export_root="D:/exports",
        asset_cache_dir="D:/exports/temp-assets",
        game_profile="generic",
        path_inference_mode="BASIC_DEFAULT",
        enable_suffix_index=True,
        material_rule_paths=["D:/rules/generic.toml", "D:/rules/calabiyau_game.toml"],
        conflict_store_path="D:/exports/temp-assets/umodel_tools_conflict_overrides.json",
        material_slots=[
            {"slot_index": 0, "material_name": "MI_Body", "descriptor_ref": "PM/Content/A/MI_Body.MI_Body"},
        ],
    )

    restored = UEFormatAssetContext.from_dict(context.to_dict())
    assert restored == context


def test_from_dict_uses_safe_defaults_for_wrong_types():
    restored = UEFormatAssetContext.from_dict(
        {
            "uemodel_asset_path": 10,
            "source_filepath": None,
            "export_root": ["D:/exports"],
            "asset_cache_dir": {"path": "D:/exports/temp-assets"},
            "game_profile": True,
            "path_inference_mode": object(),
            "enable_suffix_index": "yes",
            "material_rule_paths": "D:/rules/generic.toml",
            "conflict_store_path": 3.14,
            "material_slots": [
                {"slot_index": 0, "material_name": "MI_Body"},
                "not-a-slot",
                ["also", "not", "a", "slot"],
            ],
        }
    )

    assert restored == UEFormatAssetContext(
        uemodel_asset_path="",
        source_filepath="",
        export_root="",
        asset_cache_dir="",
        game_profile="",
        path_inference_mode="",
        enable_suffix_index=False,
        material_rule_paths=[],
        conflict_store_path="",
        material_slots=[{"slot_index": 0, "material_name": "MI_Body"}],
    )


def test_to_dict_copies_mutable_lists():
    context = UEFormatAssetContext(
        uemodel_asset_path="PM/Content/A/Model.uemodel",
        source_filepath="D:/exports/PM/Content/A/Model.uemodel",
        export_root="D:/exports",
        asset_cache_dir="D:/exports/temp-assets",
        game_profile="generic",
        path_inference_mode="BASIC_DEFAULT",
        enable_suffix_index=True,
        material_rule_paths=["D:/rules/generic.toml"],
        conflict_store_path="D:/exports/temp-assets/umodel_tools_conflict_overrides.json",
        material_slots=[{"slot_index": 0, "material_name": "MI_Body"}],
    )

    payload = context.to_dict()
    payload["material_rule_paths"].append("D:/rules/other.toml")
    payload["material_slots"].append({"slot_index": 1, "material_name": "MI_Head"})

    assert context.material_rule_paths == ["D:/rules/generic.toml"]
    assert context.material_slots == [{"slot_index": 0, "material_name": "MI_Body"}]


def test_panel_asset_property_group_declares_ueformat_context_properties():
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(Panel=object, PropertyGroup=object, Menu=object, Context=object)
    bpy.props = types.SimpleNamespace(
        BoolProperty=lambda **kwargs: ("BoolProperty", kwargs),
        StringProperty=lambda **kwargs: ("StringProperty", kwargs),
        PointerProperty=lambda **kwargs: ("PointerProperty", kwargs),
    )

    preferences = types.ModuleType("umodel_tools.preferences")
    preferences.get_addon_preferences = lambda: None
    localization = types.ModuleType("umodel_tools.localization")
    localization.t_iface = lambda value: value

    original_bpy = sys.modules.get("bpy")
    try:
        with _scoped_umodel_tools_package():
            sys.modules["bpy"] = bpy
            sys.modules["umodel_tools.preferences"] = preferences
            sys.modules["umodel_tools.localization"] = localization
            spec = importlib.util.spec_from_file_location(
                "umodel_tools.panels",
                os.path.join(ADDON_ROOT, "umodel_tools", "panels.py"),
            )
            panels = importlib.util.module_from_spec(spec)
            sys.modules["umodel_tools.panels"] = panels
            spec.loader.exec_module(panels)
    finally:
        if original_bpy is None:
            sys.modules.pop("bpy", None)
        else:
            sys.modules["bpy"] = original_bpy

    annotations = panels.UMODELTOOLS_PG_asset.__annotations__
    assert annotations["is_ueformat_asset"] == ("BoolProperty", {"default": False})
    assert annotations["ueformat_context_json"] == ("StringProperty", {"default": ""})
    assert annotations["ueformat_conflict_store_path"] == (
        "StringProperty",
        {"default": "", "subtype": "FILE_PATH"},
    )
