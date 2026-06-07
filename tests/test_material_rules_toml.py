import importlib
import os
import sys
import tempfile
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")
GENERIC_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "generic.toml")
CALABIYAU_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "calabiyau_game.toml")


def load_rule_module_module():
    package = types.ModuleType("umodel_tools")
    package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = package
    return importlib.import_module("umodel_tools.materials.rules")


def main():
    _test_rule_module_import_avoids_removed_packages()

    rule_module = load_rule_module_module()
    if os.path.normcase(os.path.abspath(rule_module.default_rule_path("generic"))) != os.path.normcase(GENERIC_RULE_PATH):
        raise AssertionError(f"Expected TOML default rule path, got {rule_module.default_rule_path('generic')!r}")

    generic_rules = rule_module.load_rule_set(GENERIC_RULE_PATH)
    calabiyau_rules = rule_module.load_rule_sets([GENERIC_RULE_PATH, CALABIYAU_RULE_PATH])
    fallback_rules = rule_module.load_rule_sets([os.path.join(ADDON_ROOT, "missing_rules.toml")])
    fallback_rule = fallback_rules.resolve("D", "T_Example_01")
    if fallback_rule is None or fallback_rule.name != "diffuse":
        raise AssertionError("Missing rule datasets should fall back to generic diffuse rules.")

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as rule_file:
        rule_file.write(
            "\n".join([
                'name = "SkipWhenProbe"',
                "",
                "[[texture_rules]]",
                'name = "matcap_probe"',
                "[texture_rules.match]",
                'param_names = ["matcaptexture"]',
                "[texture_rules.skip_when]",
                "NeedMatCap = false",
            ])
        )
        skip_when_rule_path = rule_file.name

    try:
        skip_when_rule = rule_module.load_rule_set(skip_when_rule_path).resolve("MatCapTexture", "MatCap_Toon9")
    finally:
        os.remove(skip_when_rule_path)
    if skip_when_rule is None or skip_when_rule.skip_when != frozenset({("needmatcap", False)}):
        raise AssertionError(f"Unexpected skip_when parsing result: {skip_when_rule!r}")

    generic_cases = [
        ("D", "T_Example_01", "diffuse"),
        ("BC", "T_Example_01", "diffuse"),
        ("BaseMap", "T_Chiyo_Body_D_S102", "diffuse"),
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
        _assert_resolves(generic_rules, tex_type, tex_short_name, expected_name)

    generic_negative_cases = [
        ("Maintex", "T_Noise_0023"),
        ("CloudTex", "T_Envi_Wlbl_Clouds_01"),
        ("DissolveMap", "T_Noise_0009"),
        ("RMO", "T_Example_RMO"),
        ("T_LEDTex", "T_Envi_Dirac_Decal_06g"),
        ("Mask1", "T_Kanmami_Body_Mask1_Map"),
        ("MatCapTexture", "MatCap_Toon9"),
    ]
    for tex_type, tex_short_name in generic_negative_cases:
        rule = generic_rules.resolve(tex_type, tex_short_name)
        if rule is not None:
            raise AssertionError(
                f"Generic rules should not include game or character mapping for "
                f"{tex_type!r} / {tex_short_name!r}: {rule.name!r}"
            )

    for tex_type, tex_short_name, expected_name in calabiyau_cases:
        _assert_resolves(calabiyau_rules, tex_type, tex_short_name, expected_name)

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

    print("TEST_rule_module_TOML_OK")


def _assert_resolves(rule_set, tex_type, tex_short_name, expected_name):
    rule = rule_set.resolve(tex_type, tex_short_name)
    actual_name = rule.name if rule is not None else None
    if actual_name != expected_name:
        raise AssertionError(
            f"Unexpected rule for {tex_type!r} / {tex_short_name!r}: "
            f"{actual_name!r}, expected {expected_name!r}"
        )


def _test_rule_module_import_avoids_removed_packages():
    removed_roots = {"".join(parts) for parts in (("ya", "ml"), ("_ya", "ml"), ("la", "rk"))}
    original_modules = {
        name: sys.modules.get(name)
        for name in list(sys.modules)
        if name.split(".", 1)[0].lower() in removed_roots
    }
    original_package = sys.modules.pop("umodel_tools", None)
    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools")]
    sys.modules["umodel_tools"] = fake_package
    for name in original_modules:
        sys.modules.pop(name, None)
    try:
        importlib.import_module("umodel_tools.materials.rules")
        loaded_removed = [
            name for name in sys.modules
            if name.split(".", 1)[0].lower() in removed_roots
        ]
        if loaded_removed:
            raise AssertionError(f"Importing material rules loaded removed parser modules: {loaded_removed!r}")
    finally:
        for module_name in list(sys.modules):
            if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
                del sys.modules[module_name]
        if original_package is not None:
            sys.modules["umodel_tools"] = original_package
        for name, module in original_modules.items():
            if module is not None:
                sys.modules[name] = module


if __name__ == "__main__":
    main()
