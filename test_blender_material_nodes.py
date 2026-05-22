import os
import shutil
import sys

import bpy


ADDON_ROOT = r"D:\addon"
EXPORT_DIR = r"D:\UmodelExport"
TEST_ROOT = os.path.join(ADDON_ROOT, "test_runtime_material_nodes")
GLASS_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_PM_Glass_03b.props.txt"
)
WATER_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Water_01.props.txt"
)
MOUSE_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Mouse_02a.props.txt"
)
DESK_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Desk_03.props.txt"
)


class MaterialNodeImporter:
    pass


def main():
    sys.path.insert(0, ADDON_ROOT)

    bpy.ops.preferences.addon_enable(module="umodel_tools")

    import umodel_tools  # pylint: disable=import-error,import-outside-toplevel
    from umodel_tools import asset_db, asset_importer, umodel_path_resolver  # pylint: disable=import-error,import-outside-toplevel

    try:
        if os.path.isdir(TEST_ROOT):
            shutil.rmtree(TEST_ROOT)
        os.makedirs(TEST_ROOT, exist_ok=True)

        importer = MaterialNodeImporter()
        importer.__class__ = type("MaterialNodeImporter", (asset_importer.AssetImporter,), {})
        importer.load_pbr_maps = True
        importer.import_backface_culling = False
        importer.texture_format = ".png"
        importer.enable_umodel_path_inference = True
        importer.path_inference_mode = umodel_path_resolver.AGGRESSIVE
        importer.enable_suffix_index = True
        importer._reset_import_runtime_state()

        db = asset_db.AssetDB(TEST_ROOT)
        importer._import_material_to_library(
            material_name="MI_PM_Glass_03b",
            material_path_local=GLASS_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Water_01",
            material_path_local=WATER_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Mouse_02a",
            material_path_local=MOUSE_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Desk_03",
            material_path_local=DESK_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )

        glass = _load_material(os.path.join(TEST_ROOT, GLASS_MATERIAL[:-len(".props.txt")] + ".blend"))
        water = _load_material(os.path.join(TEST_ROOT, WATER_MATERIAL[:-len(".props.txt")] + ".blend"))
        mouse = _load_material(os.path.join(TEST_ROOT, MOUSE_MATERIAL[:-len(".props.txt")] + ".blend"))
        desk = _load_material(os.path.join(TEST_ROOT, DESK_MATERIAL[:-len(".props.txt")] + ".blend"))

        _assert_glass_material(glass, expected_mix=True)
        _assert_glass_material(water, expected_mix=False)
        _assert_opaque_diffuse_alpha_ignored(mouse)
        _assert_opaque_diffuse_alpha_ignored(desk)

        print("TEST_BLENDER_MATERIAL_NODES_OK")
    finally:
        try:
            bpy.ops.preferences.addon_disable(module="umodel_tools")
        finally:
            if os.path.isdir(TEST_ROOT):
                shutil.rmtree(TEST_ROOT)


def _load_material(path):
    with bpy.data.libraries.load(filepath=path, link=False) as (data_from, data_to):
        data_to.materials = list(data_from.materials)

    if not data_to.materials:
        raise AssertionError(f"No material found in {path}")
    return data_to.materials[0]


def _assert_glass_material(material, expected_mix):
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    if "ShaderNodeBsdfGlass" not in node_types:
        raise AssertionError(f"{material.name} missing Glass BSDF: {node_types}")
    if "ShaderNodeBsdfPrincipled" in node_types:
        raise AssertionError(f"{material.name} should not keep Principled BSDF.")
    if "ShaderNodeMix" in node_types:
        raise AssertionError(f"{material.name} should not keep AO multiply node.")
    if material.surface_render_method != "DITHERED":
        raise AssertionError(f"{material.name} should use DITHERED surface render method.")
    if material.blend_method != "HASHED":
        raise AssertionError(f"{material.name} should use HASHED blend method.")
    if not material.use_transparency_overlap:
        raise AssertionError(f"{material.name} should keep transparency overlap enabled.")
    if not material.use_transparent_shadow:
        raise AssertionError(f"{material.name} should keep transparent shadows enabled.")

    has_mix_shader = "ShaderNodeMixShader" in node_types
    if has_mix_shader != expected_mix:
        raise AssertionError(f"{material.name} mix shader={has_mix_shader}, expected {expected_mix}.")

    output = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial")
    if not output.inputs["Surface"].is_linked:
        raise AssertionError(f"{material.name} output surface is not linked.")


def _assert_opaque_diffuse_alpha_ignored(material):
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    if "ShaderNodeBsdfPrincipled" not in node_types:
        raise AssertionError(f"{material.name} should keep a Principled BSDF.")
    if "ShaderNodeMix" not in node_types:
        raise AssertionError(f"{material.name} should keep AO multiply when ORM provides AO.")

    bsdf = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    alpha_input = bsdf.inputs.get("Alpha")
    if alpha_input is not None and alpha_input.is_linked:
        raise AssertionError(f"{material.name} opaque diffuse alpha should not feed BSDF alpha.")


if __name__ == "__main__":
    if not os.path.exists(os.path.join(EXPORT_DIR, GLASS_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, GLASS_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, WATER_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, WATER_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, MOUSE_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, MOUSE_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, DESK_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, DESK_MATERIAL)}")
    main()
