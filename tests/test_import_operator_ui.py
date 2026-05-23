import json
import os
import sys
import types

import bpy


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
    sys.path.insert(0, ADDON_ROOT)
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        from umodel_tools import material_rules, operators  # pylint: disable=import-error,import-outside-toplevel

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
            "import_storage_mode",
            "load_pbr_maps",
            "texture_format",
            "import_backface_culling",
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

        storage_items = [item.identifier for item in rna.properties["import_storage_mode"].enum_items]
        expected_storage_items = ["LINKED_ASSET_LIBRARY", "LOCAL_SINGLE_FILE", "APPEND_AS_LOCAL"]
        if storage_items != expected_storage_items:
            raise AssertionError(f"Unexpected import storage items: {storage_items!r}")

        prefs = bpy.context.preferences.addons["umodel_tools"].preferences
        while len(prefs.material_rule_datasets):
            prefs.material_rule_datasets.remove(0)
        prefs.ensure_material_rule_datasets()
        if len(prefs.material_rule_datasets) != 1:
            raise AssertionError("Expected Generic material rule dataset to be restored.")

        generic_dataset = prefs.material_rule_datasets[0]
        normalized_generic_path = os.path.normcase(os.path.abspath(generic_dataset.path))
        if os.path.normcase(os.path.abspath(material_rules.default_rule_path("generic"))) == normalized_generic_path:
            raise AssertionError("Generic material rules should be copied to the user UTM rule directory.")
        if not normalized_generic_path.endswith(os.path.normcase(os.path.join("UTM", "rules", "generic.yaml"))):
            raise AssertionError(f"Unexpected Generic material rule path: {generic_dataset.path}")

        generic_dataset.enabled = False
        fallback_paths = prefs.get_active_material_rule_dataset_paths()
        if not fallback_paths or not os.path.isfile(fallback_paths[0]):
            raise AssertionError(f"Expected Generic fallback rule path, got {fallback_paths!r}")

        fake = types.SimpleNamespace(
            layout=FakeLayout(),
            filepath=os.path.join(ADDON_ROOT, "sample_maps", "Envi_Wlbl.json"),
            umodel_export_dir=os.path.join(ADDON_ROOT, "sample_export"),
            game_profile="generic",
            import_storage_mode="LINKED_ASSET_LIBRARY",
            load_pbr_maps=True,
            texture_format=".png",
            import_backface_culling=False,
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
            "import_storage_mode",
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
            "save_missing_asset_report",
            "missing_asset_report_format",
            "max_missing_assets_printed_to_console",
            "deduplicate_missing_assets",
            "missing_asset_report_directory_mode",
            "include_actor_context_in_missing_report",
        ):
            if required_draw_prop not in drawn_props:
                raise AssertionError(f"draw() did not expose {required_draw_prop!r}")

        print(json.dumps({
            "operator_property_count": len(prop_names),
            "storage_items": storage_items,
            "drawn_props": drawn_props,
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
