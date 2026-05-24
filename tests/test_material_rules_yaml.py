import importlib.util
import os
import sys


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RULE_MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "material_rules.py")
GENERIC_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "generic.yaml")
CALABIYAU_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "calabiyau_game.yaml")


def load_material_rules_module():
    spec = importlib.util.spec_from_file_location("material_rules", RULE_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["material_rules"] = module
    spec.loader.exec_module(module)
    return module


def main():
    material_rules = load_material_rules_module()
    generic_rules = material_rules.load_rule_set(GENERIC_RULE_PATH)
    calabiyau_rules = material_rules.load_rule_sets([GENERIC_RULE_PATH, CALABIYAU_RULE_PATH])
    fallback_rules = material_rules.load_rule_sets([os.path.join(ADDON_ROOT, "missing_rules.yaml")])
    fallback_rule = fallback_rules.resolve("D", "T_Example_01")
    if fallback_rule is None or fallback_rule.name != "diffuse":
        raise AssertionError("Missing rule datasets should fall back to generic diffuse rules.")

    generic_cases = [
        ("D", "T_Example_01", "diffuse"),
        ("BC", "T_Example_01", "diffuse"),
        ("N", "BaseFlattenNormalMap", "normal"),
        ("ORM", "T_Birthdaygiftbox_ORM", "orm"),
        ("AO_R_M_MASK", "T_Envi_Olgk_Pier_01c_AO_R_M_MASK", "orm"),
        ("RM", "T_DefaultWhite_Linear", "rm"),
        ("OcclusionRoughnessMetallic", "T_Test_01", "orm"),
        ("Alpha Mask", "T_Test_Alpha", "alpha_mask"),
        ("Glass", "T_Test_Glass", "glass"),
        ("Translucent", "T_Test_Translucent", "translucent"),
        ("Emissive", "T_Test_Emissive", "emissive"),
        ("DiffuseAndAlpha", "T_Envi_Fyz_Wall_01c_D2", "diffuse"),
        ("alpha", "T_Envi_Wlbl_keyboard_03b_Mask", "alpha_mask"),
        ("D", "T_Unexpected_M", "diffuse"),
        ("roughness", "T_Test_Rough", "roughness"),
        ("metallic", "T_Test_Metal", "metallic"),
        ("specular", "T_Test_Spec", "specular"),
        ("ambient occlusion", "T_Test_AO", "ao"),
    ]

    calabiyau_cases = [
        ("ORM", "T_Envi_Umeda_Cherrytree_Trunk_01_RMO", "rmo"),
        ("Blend_AO_R_M_MASK", "T_Envi_Fyz_Blend_AO_R_M_MASK", "orm"),
        ("RM", "T_Evni_Michele_melonpa_RMO", "rmo"),
        ("RoughnessMetallicOcclusion", "T_Test_02", "rmo"),
        ("basecolor_low", "T_Envi_Leisure_pedestal_01b_D", "diffuse"),
        ("Maintex", "T_Noise_0023", "diffuse"),
        ("SurfaceTex", "T_Noise_0012", "diffuse"),
        ("InsideTex", "T_Noise_0021", "diffuse"),
        ("MatCapTex", "T_Character_MatCap", "diffuse"),
        ("ContentTexture", "T_Envi_Dirac_Decal_06f", "diffuse"),
        ("jingti_Map", "T_DefaultWhite_Gamma", "diffuse"),
        ("CloudTex", "T_Envi_Wlbl_Clouds_01", "diffuse"),
        ("Cloud Texture", "T_Envi_Wlbl_Clouds_01", "diffuse"),
        ("Alpha", "T_Envi_Fyz_Wall_01a_M", "alpha_mask"),
        ("DissolveMap", "T_Noise_0009", "alpha_mask"),
        ("DissolveMask", "T_Mask_2000_2", "alpha_mask"),
        ("DissolveTex", "T_Noise_5055_2", "alpha_mask"),
        ("Noise Tex", "T_Noise_0001", "alpha_mask"),
        ("MainTexUVNoise_Tex", "T_Noise_8005", "alpha_mask"),
        ("vertex Noise", "T_tra_0001", "alpha_mask"),
        ("MaskRG", "T_Wall_Mask_04", "alpha_mask"),
        ("AlphaMaskA_Tex", "T_Mask_LKL_011", "alpha_mask"),
        ("Alpha Mask A", "T_Mask_5004_1", "alpha_mask"),
        ("EdgeHighLightMask", "T_Mask_NB_005", "alpha_mask"),
        ("shazi", "T_Envi_Ksmt_Sand01_M", "alpha_mask"),
        ("T_LEDTex", "T_Envi_Dirac_Decal_06g", "emissive"),
    ]

    for tex_type, tex_short_name, expected_name in generic_cases:
        rule = generic_rules.resolve(tex_type, tex_short_name)
        actual_name = rule.name if rule is not None else None
        if actual_name != expected_name:
            raise AssertionError(
                f"Unexpected Generic rule for {tex_type!r} / {tex_short_name!r}: "
                f"{actual_name!r}, expected {expected_name!r}"
            )

    generic_negative_cases = [
        ("Maintex", "T_Noise_0023"),
        ("CloudTex", "T_Envi_Wlbl_Clouds_01"),
        ("DissolveMap", "T_Noise_0009"),
        ("RMO", "T_Example_RMO"),
        ("T_LEDTex", "T_Envi_Dirac_Decal_06g"),
    ]
    for tex_type, tex_short_name in generic_negative_cases:
        rule = generic_rules.resolve(tex_type, tex_short_name)
        if rule is not None:
            raise AssertionError(
                f"Generic rules should not include CalabiyauGame mapping for "
                f"{tex_type!r} / {tex_short_name!r}: {rule.name!r}"
            )

    for tex_type, tex_short_name, expected_name in calabiyau_cases:
        rule = calabiyau_rules.resolve(tex_type, tex_short_name)
        actual_name = rule.name if rule is not None else None
        if actual_name != expected_name:
            raise AssertionError(
                f"Unexpected combined CalabiyauGame rule for {tex_type!r} / {tex_short_name!r}: "
                f"{actual_name!r}, expected {expected_name!r}"
            )

    normal_rule = generic_rules.resolve("N", "T_Example_N")
    normal_connections = {(connection.source, connection.target) for connection in normal_rule.connections}
    expected_normal_connections = {
        ("image.Color", "split.Color"),
        ("split.Red", "combine.Red"),
        ("split.Green", "invert_green.Color"),
        ("invert_green.Color", "combine.Green"),
        ("split.Blue", "combine.Blue"),
        ("combine.Color", "normal_map.Color"),
        ("normal_map.Normal", "bsdf.Normal"),
    }
    if normal_connections != expected_normal_connections:
        raise AssertionError(f"Unexpected DirectX normal conversion graph: {normal_connections!r}")

    rmo_rule = calabiyau_rules.resolve("RMO", "T_Example_RMO")
    rmo_connections = {(connection.source, connection.target) for connection in rmo_rule.connections}
    expected_rmo_connections = {
        ("image.Color", "split.Color"),
        ("split.Red", "ao_mix.Color2"),
        ("split.Green", "bsdf.Roughness"),
        ("split.Blue", "bsdf.Metallic"),
        ("image.Alpha", "displacement.Height"),
        ("displacement.Displacement", "output.Displacement"),
    }
    if rmo_connections != expected_rmo_connections:
        raise AssertionError(f"Unexpected RMO channel graph: {rmo_connections!r}")

    print("TEST_MATERIAL_RULES_YAML_OK")


if __name__ == "__main__":
    main()
