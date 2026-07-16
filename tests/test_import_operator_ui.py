import json
import os
import sys
import types

try:
    import addon_utils
    import bpy
except ModuleNotFoundError:
    import pytest
    pytest.skip("Blender-only test; run with blender --background --python", allow_module_level=True)


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


class FakeLayout:
    def __init__(self):
        self.calls = []

    def label(self, **kwargs):
        self.calls.append(("label", kwargs))

    def prop(self, _obj, name, **kwargs):
        self.calls.append(("prop", name, kwargs))

    def box(self):
        self.calls.append(("box",))
        return self

    def column(self):
        self.calls.append(("column",))
        return self

    @property
    def enabled(self):
        return True

    @enabled.setter
    def enabled(self, value):
        self.calls.append(("enabled", value))


def main():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        from umodel_tools import operators  # pylint: disable=import-error,import-outside-toplevel
        from umodel_tools.materials import rules as rule_module  # pylint: disable=import-error,import-outside-toplevel

        rna = bpy.ops.umodel_tools.import_unreal_map.get_rna_type()
        selector_rna = bpy.ops.umodel_tools.select_unreal_map_json.get_rna_type()
        selector_prop_names = set(selector_rna.properties.keys())
        selector_required = {
            "filepath",
            "filter_glob",
            "files",
            "directory",
        }
        selector_missing = sorted(selector_required - selector_prop_names)
        if selector_missing:
            raise AssertionError(f"JSON selector operator is missing properties: {selector_missing!r}")

        prop_names = set(rna.properties.keys())
        required = {
            "map_paths",
            "filepath",
            "umodel_export_dir",
            "game_profile",
            "load_pbr_maps",
            "texture_format",
            "import_backface_culling",
            "import_skeletal_mesh_with_armature",
            "import_psa_animations",
            "path_inference_mode",
            "missing_mesh_policy",
            "missing_material_policy",
            "missing_texture_policy",
            "validation_preset",
            "show_advanced_import_settings",
            "enable_umodel_path_inference",
            "enable_suffix_index",
            "report_path_resolution_stats",
            "enable_import_validation",
            "min_mesh_count",
            "min_light_count",
            "min_material_count",
            "save_missing_asset_report",
            "missing_asset_report_format",
            "max_missing_assets_printed_to_console",
            "deduplicate_missing_assets",
            "missing_asset_report_directory_mode",
            "custom_missing_asset_report_directory",
            "include_actor_context_in_missing_report",
        }
        missing = sorted(required - prop_names)
        if missing:
            raise AssertionError(f"Import operator is missing properties: {missing!r}")
        for opt_in_property in ("import_skeletal_mesh_with_armature", "import_psa_animations"):
            if rna.properties[opt_in_property].default is not False:
                raise AssertionError(f"Experimental option must default off: {opt_in_property}")

        removed_operator_ids = (
            "recover_unreal_asset",
            "import_unreal_assets",
            "select_ueformat_model",
            "import_ueformat_model",
            "apply_ueformat_conflict_choice",
            "rebuild_ueformat_asset_materials",
            "realign_asset",
        )
        def operator_is_registered(operator_id):
            try:
                getattr(bpy.ops.umodel_tools, operator_id).get_rna_type()
            except KeyError:
                return False
            return True

        for operator_id in removed_operator_ids:
            if operator_is_registered(operator_id):
                raise AssertionError(f"Removed non-map operator is still registered: {operator_id}")

        removed_operator_classes = (
            "UMODELTOOLS_OT_recover_unreal_asset",
            "UMODELTOOLS_OT_import_unreal_assets",
            "UMODELTOOLS_OT_select_ueformat_model",
            "UMODELTOOLS_OT_import_ueformat_model",
            "UMODELTOOLS_OT_apply_ueformat_conflict_choice",
            "UMODELTOOLS_OT_rebuild_ueformat_asset_materials",
            "UMODELTOOLS_OT_realign_asset",
        )
        for class_name in removed_operator_classes:
            if hasattr(operators, class_name):
                raise AssertionError(f"Removed non-map operator class is still present: {class_name}")

        prefs = bpy.context.preferences.addons["umodel_tools"].preferences
        for preference_name in (
            "default_import_skeletal_mesh_with_armature",
            "default_import_psa_animations",
        ):
            if prefs.bl_rna.properties[preference_name].default is not False:
                raise AssertionError(f"Experimental preference must default off: {preference_name}")
        while len(prefs.material_rule_datasets):
            prefs.material_rule_datasets.remove(0)
        prefs.ensure_material_rule_datasets()
        if len(prefs.material_rule_datasets) != 2:
            raise AssertionError("Expected bundled material rule datasets to be restored.")

        generic_dataset = prefs.material_rule_datasets[0]
        normalized_generic_path = os.path.normcase(os.path.abspath(generic_dataset.path))
        if os.path.normcase(os.path.abspath(rule_module.default_rule_path("generic"))) == normalized_generic_path:
            raise AssertionError("Generic material rules should be copied to the user UTM rule directory.")
        if not normalized_generic_path.endswith(os.path.normcase(os.path.join("UTM", "rules", "generic.toml"))):
            raise AssertionError(f"Unexpected Generic material rule path: {generic_dataset.path}")

        calabiyau_dataset = prefs.material_rule_datasets[1]
        normalized_calabiyau_path = os.path.normcase(os.path.abspath(calabiyau_dataset.path))
        if not normalized_calabiyau_path.endswith(
            os.path.normcase(os.path.join("UTM", "rules", "calabiyau_game.toml"))
        ):
            raise AssertionError(f"Unexpected CalabiyauGame material rule path: {calabiyau_dataset.path}")
        if calabiyau_dataset.enabled:
            raise AssertionError("CalabiyauGame material rules should be available but disabled by default.")

        generic_dataset.enabled = False
        fallback_paths = prefs.get_active_material_rule_dataset_paths()
        if not fallback_paths or not os.path.isfile(fallback_paths[0]):
            raise AssertionError(f"Expected Generic fallback rule path, got {fallback_paths!r}")

        fake = types.SimpleNamespace(
            layout=FakeLayout(),
            filepath=os.path.join(ADDON_ROOT, "sample_maps", "Envi_Wlbl.json"),
            umodel_export_dir=os.path.join(ADDON_ROOT, "tests", "fixtures", "sample_export"),
            game_profile="generic",
            load_pbr_maps=True,
            texture_format=".png",
            import_backface_culling=False,
            import_skeletal_mesh_as_static_fallback=True,
            import_skeletal_mesh_with_armature=False,
            import_psa_animations=False,
            path_inference_mode="BASIC_DEFAULT",
            missing_mesh_policy="WARN_SKIP",
            missing_material_policy="USE_PLACEHOLDER",
            missing_texture_policy="USE_PLACEHOLDER",
            validation_preset="BASIC_DEFAULT",
            show_advanced_import_settings=True,
            enable_umodel_path_inference=True,
            enable_suffix_index=True,
            report_path_resolution_stats=True,
            enable_import_validation=True,
            min_mesh_count=1,
            min_light_count=0,
            min_material_count=0,
            require_any_material_assigned=False,
            reject_dict_like_names=True,
            allow_missing_placeholder_materials=True,
            max_missing_asset_warnings_in_console=50,
            print_missing_asset_summary=True,
            save_missing_asset_report=True,
            missing_asset_report_format="CSV",
            max_missing_assets_printed_to_console=30,
            deduplicate_missing_assets=True,
            missing_asset_report_directory_mode="UMODEL_EXPORT",
            custom_missing_asset_report_directory="",
            include_actor_context_in_missing_report=True,
            save_paths_as_recent=True,
        )
        operators.UMODELTOOLS_OT_import_unreal_map.draw(fake, bpy.context)

        drawn_props = [call[1] for call in fake.layout.calls if call[0] == "prop"]
        for required_draw_prop in (
            "umodel_export_dir",
            "game_profile",
            "load_pbr_maps",
            "texture_format",
            "path_inference_mode",
            "missing_mesh_policy",
            "missing_material_policy",
            "missing_texture_policy",
            "validation_preset",
            "enable_umodel_path_inference",
            "enable_suffix_index",
            "report_path_resolution_stats",
            "import_backface_culling",
            "import_skeletal_mesh_as_static_fallback",
            "import_skeletal_mesh_with_armature",
            "import_psa_animations",
            "save_missing_asset_report",
            "missing_asset_report_format",
            "max_missing_assets_printed_to_console",
            "deduplicate_missing_assets",
            "missing_asset_report_directory_mode",
            "include_actor_context_in_missing_report",
        ):
            if required_draw_prop not in drawn_props:
                raise AssertionError(f"draw() did not expose {required_draw_prop!r}")

        for removed_draw_prop in ("import_storage_mode",):
            if removed_draw_prop in drawn_props:
                raise AssertionError(f"Map-only UI still exposes removed property: {removed_draw_prop}")

        print(json.dumps({
            "operator_property_count": len(prop_names),
            "drawn_props": drawn_props,
            "removed_operator_ids": removed_operator_ids,
        }, indent=2))
        print("TEST_IMPORT_OPERATOR_UI_OK")
    finally:
        try:
            prefs = bpy.context.preferences.addons["umodel_tools"].preferences
            prefs.ensure_material_rule_datasets()
            if len(prefs.material_rule_datasets):
                prefs.material_rule_datasets[0].enabled = True
        except Exception:  # pragma: no cover - best-effort cleanup for Blender prefs.
            pass
        bpy.ops.preferences.addon_disable(module="umodel_tools")


if __name__ == "__main__":
    main()
