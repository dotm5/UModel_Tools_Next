import os
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
EXPORT_DIR = os.path.abspath(
    os.environ.get("UMODEL_TEST_EXPORT_DIR", os.path.join(ADDON_ROOT, os.pardir, "UmodelExport"))
)
TEST_ROOT = os.path.join(ADDON_ROOT, "test_runtime_material_nodes")
GLASS_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_PM_Glass_03b.props.txt"
)
WATER_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Water_01.props.txt"
)
WATER_02_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Water_02.props.txt"
)
MOUSE_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Mouse_02a.props.txt"
)
DESK_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Desk_03.props.txt"
)
CHAIR_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Chair_02a.props.txt"
)
KEYBOARD_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_keyboard_03c.props.txt"
)
SCREEN_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Screen_01a.props.txt"
)
CLOUDS_H_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Clouds_03.props.txt"
)
CLOUDS_I_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Clouds_02.props.txt"
)
RMO_MATERIAL = (
    r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Evni_Michele_melonpa.props.txt"
)


class MaterialNodeImporter:
    pass


def main():
    _enable_source_addon()

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
            material_name="MI_Envi_Wlbl_Water_02",
            material_path_local=WATER_02_MATERIAL,
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
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Chair_02a",
            material_path_local=CHAIR_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_keyboard_03c",
            material_path_local=KEYBOARD_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Screen_01a",
            material_path_local=SCREEN_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Clouds_03",
            material_path_local=CLOUDS_H_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Envi_Wlbl_Clouds_02",
            material_path_local=CLOUDS_I_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )
        importer._import_material_to_library(
            material_name="MI_Evni_Michele_melonpa",
            material_path_local=RMO_MATERIAL,
            db=db,
            umodel_export_dir=EXPORT_DIR,
            asset_library_dir=TEST_ROOT,
            game_profile="generic",
        )

        glass = _load_material(os.path.join(TEST_ROOT, GLASS_MATERIAL[:-len(".props.txt")] + ".blend"))
        water = _load_material(os.path.join(TEST_ROOT, WATER_MATERIAL[:-len(".props.txt")] + ".blend"))
        water_02 = _load_material(os.path.join(TEST_ROOT, WATER_02_MATERIAL[:-len(".props.txt")] + ".blend"))
        mouse = _load_material(os.path.join(TEST_ROOT, MOUSE_MATERIAL[:-len(".props.txt")] + ".blend"))
        desk = _load_material(os.path.join(TEST_ROOT, DESK_MATERIAL[:-len(".props.txt")] + ".blend"))
        chair = _load_material(os.path.join(TEST_ROOT, CHAIR_MATERIAL[:-len(".props.txt")] + ".blend"))
        keyboard = _load_material(os.path.join(TEST_ROOT, KEYBOARD_MATERIAL[:-len(".props.txt")] + ".blend"))
        screen = _load_material(os.path.join(TEST_ROOT, SCREEN_MATERIAL[:-len(".props.txt")] + ".blend"))
        clouds_h = _load_material(os.path.join(TEST_ROOT, CLOUDS_H_MATERIAL[:-len(".props.txt")] + ".blend"))
        clouds_i = _load_material(os.path.join(TEST_ROOT, CLOUDS_I_MATERIAL[:-len(".props.txt")] + ".blend"))
        rmo = _load_material(os.path.join(TEST_ROOT, RMO_MATERIAL[:-len(".props.txt")] + ".blend"))

        _assert_glass_material(glass, expected_mix=True)
        _assert_glass_material(water, expected_mix=False)
        _assert_glass_material(water_02, expected_mix=True)
        _assert_no_texture_rule_nodes_after_shader_hint(water_02)
        _assert_opaque_diffuse_alpha_ignored(mouse)
        _assert_opaque_diffuse_alpha_ignored(desk)
        _assert_opaque_diffuse_alpha_ignored(chair, expect_emission=False)
        _assert_opaque_diffuse_alpha_ignored(keyboard)
        _assert_screen_static_switches_respected(screen)
        _assert_cloud_material(clouds_h)
        _assert_cloud_material(clouds_i)
        _assert_rmo_channel_mapping(rmo)

        print("TEST_BLENDER_MATERIAL_NODES_OK")
    finally:
        try:
            bpy.ops.preferences.addon_disable(module="umodel_tools")
        finally:
            if os.path.isdir(TEST_ROOT):
                shutil.rmtree(TEST_ROOT)


def _enable_source_addon():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")


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


def _assert_no_texture_rule_nodes_after_shader_hint(material):
    forbidden_types = {
        "ShaderNodeBsdfPrincipled",
        "ShaderNodeTexImage",
        "ShaderNodeSeparateColor",
        "ShaderNodeNormalMap",
    }
    actual_types = {node.bl_idname for node in material.node_tree.nodes}
    extra = forbidden_types.intersection(actual_types)
    if extra:
        raise AssertionError(f"{material.name} shader hint should not keep texture-rule nodes: {extra}")


def _assert_opaque_diffuse_alpha_ignored(material, expect_emission=True):
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    if "ShaderNodeBsdfPrincipled" not in node_types:
        raise AssertionError(f"{material.name} should keep a Principled BSDF.")
    if "ShaderNodeMix" not in node_types:
        raise AssertionError(f"{material.name} should keep AO multiply when ORM provides AO.")
    if "ShaderNodeMixShader" in node_types or "ShaderNodeBsdfTransparent" in node_types:
        raise AssertionError(f"{material.name} opaque material should not use alpha mask transparency.")

    bsdf = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    alpha_input = bsdf.inputs.get("Alpha")
    if alpha_input is not None and alpha_input.is_linked:
        raise AssertionError(f"{material.name} opaque diffuse alpha should not feed BSDF alpha.")

    diffuse_image_nodes = [
        node for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
        and node.image is not None
        and node.image.name.lower().endswith("_d.png")
    ]
    if not diffuse_image_nodes:
        raise AssertionError(f"{material.name} should keep a diffuse image node.")
    for node in diffuse_image_nodes:
        if node.image.alpha_mode != "CHANNEL_PACKED":
            raise AssertionError(f"{material.name} diffuse alpha should be channel-packed data.")

    emission_strength = bsdf.inputs.get("Emission Strength")
    has_emission = emission_strength is not None and emission_strength.is_linked
    if has_emission != expect_emission:
        raise AssertionError(f"{material.name} emission link={has_emission}, expected {expect_emission}.")
    if expect_emission and "ShaderNodeMath" not in node_types:
        raise AssertionError(f"{material.name} should scale packed alpha by E_Level.")


def _assert_rmo_channel_mapping(material):
    bsdf = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    output = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeOutputMaterial")
    ao_mix = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeMix")
    split = _source_node_for_input(bsdf.inputs["Roughness"])
    if split is None or split.bl_idname != "ShaderNodeSeparateColor":
        raise AssertionError(f"{material.name} RMO roughness should come from Separate Color.")

    expected_links = {
        (split.outputs["Red"], ao_mix.inputs[7]),
        (split.outputs["Green"], bsdf.inputs["Roughness"]),
        (split.outputs["Blue"], bsdf.inputs["Metallic"]),
    }
    actual_links = {(link.from_socket, link.to_socket) for link in material.node_tree.links}
    if not expected_links.issubset(actual_links):
        raise AssertionError(f"{material.name} RMO RGB channels are not mapped as AO/R/M.")

    displacement_link = output.inputs["Displacement"].links
    if not displacement_link or displacement_link[0].from_node.bl_idname != "ShaderNodeDisplacement":
        raise AssertionError(f"{material.name} RMO alpha should feed displacement height.")


def _assert_screen_static_switches_respected(material):
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    if "ShaderNodeSeparateColor" in node_types:
        raise AssertionError(f"{material.name} should not split disabled ORM channels.")
    if "ShaderNodeMix" in node_types:
        raise AssertionError(f"{material.name} should remove AO multiply when UseORM is false.")

    image_names = {
        node.image.name.lower()
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage" and node.image is not None
    }
    if any("storage_01a_orm" in image_name for image_name in image_names):
        raise AssertionError(f"{material.name} should not keep disabled Storage ORM image nodes: {image_names}")

    bsdf = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    if bsdf.inputs["Roughness"].is_linked or bsdf.inputs["Metallic"].is_linked:
        raise AssertionError(f"{material.name} disabled ORM should not drive roughness or metallic.")
    emission_strength = bsdf.inputs.get("Emission Strength")
    if emission_strength is None or not emission_strength.is_linked:
        raise AssertionError(f"{material.name} diffuse alpha should still drive emission strength.")


def _assert_cloud_material(material):
    node_types = {node.bl_idname for node in material.node_tree.nodes}
    if "ShaderNodeBsdfPrincipled" not in node_types:
        raise AssertionError(f"{material.name} should keep a Principled BSDF.")

    cloud_nodes = [
        node for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
        and node.image is not None
        and "clouds_01" in node.image.name.lower()
    ]
    if not cloud_nodes:
        raise AssertionError(f"{material.name} should import the CloudTex image.")

    bsdf = next(node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled")
    base_color = bsdf.inputs.get("Base Color")
    alpha = bsdf.inputs.get("Alpha")
    if base_color is None or not base_color.is_linked:
        raise AssertionError(f"{material.name} CloudTex color should feed base color.")
    if alpha is None or not alpha.is_linked:
        raise AssertionError(f"{material.name} CloudTex alpha should feed translucent alpha.")


def _source_node_for_input(socket):
    if not socket.is_linked:
        return None
    return socket.links[0].from_node


if __name__ == "__main__":
    if not os.path.exists(os.path.join(EXPORT_DIR, GLASS_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, GLASS_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, WATER_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, WATER_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, WATER_02_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, WATER_02_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, MOUSE_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, MOUSE_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, DESK_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, DESK_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, CHAIR_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, CHAIR_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, KEYBOARD_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, KEYBOARD_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, SCREEN_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, SCREEN_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, CLOUDS_H_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, CLOUDS_H_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, CLOUDS_I_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, CLOUDS_I_MATERIAL)}")
    if not os.path.exists(os.path.join(EXPORT_DIR, RMO_MATERIAL)):
        raise SystemExit(f"Missing test fixture: {os.path.join(EXPORT_DIR, RMO_MATERIAL)}")
    main()
