import os
import sys
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)


def main():
    package = types.ModuleType("umodel_tools")
    package.__path__ = [MODULE_ROOT]
    sys.modules["umodel_tools"] = package
    from umodel_tools import import_support  # pylint: disable=import-outside-toplevel
    from umodel_tools.materials import rules as rule_module  # pylint: disable=import-outside-toplevel

    diffuse = rule_module.TextureRule(
        name="diffuse",
        diffuse=True,
        prefer_suffix=False,
        param_names=frozenset({"d"}),
        suffixes=frozenset({"d"}),
        nodes=(),
        connections=(),
    )
    orm = rule_module.TextureRule(
        name="orm",
        diffuse=False,
        prefer_suffix=True,
        param_names=frozenset({"orm"}),
        suffixes=frozenset({"orm", "ao_r_m_mask"}),
        nodes=(),
        connections=(),
    )
    rules = rule_module.MaterialRuleSet([diffuse, orm])

    if rules.resolve("D", "T_Example_ORM").name != "orm":
        raise AssertionError("prefer_suffix should win before parameter-name matching.")
    if rules.resolve("D", "T_Example_D").name != "diffuse":
        raise AssertionError("parameter-name matching should preserve current diffuse behavior.")
    if rules.resolve("Unknown", "T_Example_AO_R_M_MASK").name != "orm":
        raise AssertionError("compound suffix fallback should preserve current behavior.")
    if rules.resolve("Unknown", "T_Example_BaseColor") is not None:
        raise AssertionError("unknown texture should not resolve without matching rule data.")

    if import_support.normalize_texture_name("/Game/Textures/T_Example_D") != "t_example_d":
        raise AssertionError("texture basename normalization changed.")
    if not import_support.matches_texture_suffix("T_Example_AO_R_M_MASK", frozenset({"ao_r_m_mask"})):
        raise AssertionError("compound suffix matching changed.")

    _test_generic_skip_when_rule_semantics(rule_module)

    print("TEST_MATERIAL_DECISION_OK")


def _test_generic_skip_when_rule_semantics(rule_module):
    generic = _load_generic_profile_for_unit_test()
    skip_matcap_rule = rule_module.TextureRule(
        name="ww_matcap",
        diffuse=False,
        prefer_suffix=False,
        param_names=frozenset({"matcaptexture"}),
        suffixes=frozenset({"matcap"}),
        nodes=(),
        connections=(),
        skip_when=frozenset({("needmatcap", False)}),
    )

    disabled_ctx = generic.MaterialContext(
        bsdf_node=None,
        desc_ast=None,
        use_pbr=True,
        blend_mode=None,
        scalar_parameters={},
        vector_parameters={},
        static_switch_parameters={"Need MatCap": False},
    )
    if not generic._should_skip_rule(disabled_ctx, skip_matcap_rule):
        raise AssertionError("skip_when should skip when the present static switch equals the expected value.")

    enabled_ctx = generic.MaterialContext(
        bsdf_node=None,
        desc_ast=None,
        use_pbr=True,
        blend_mode=None,
        scalar_parameters={},
        vector_parameters={},
        static_switch_parameters={"needmatcap": True},
    )
    if generic._should_skip_rule(enabled_ctx, skip_matcap_rule):
        raise AssertionError("skip_when should not skip when the static switch value differs.")

    absent_ctx = generic.MaterialContext(
        bsdf_node=None,
        desc_ast=None,
        use_pbr=True,
        blend_mode=None,
        scalar_parameters={},
        vector_parameters={},
        static_switch_parameters={},
    )
    if generic._should_skip_rule(absent_ctx, skip_matcap_rule):
        raise AssertionError("skip_when should not skip when the static switch is absent.")


def _load_generic_profile_for_unit_test():
    addon_root = os.path.join(ADDON_ROOT, "umodel_tools")
    package = types.ModuleType("umodel_tools")
    package.__path__ = [addon_root]
    profiles_package = types.ModuleType("umodel_tools.game_profiles")
    profiles_package.__path__ = [os.path.join(addon_root, "game_profiles")]

    fake_bpy = types.ModuleType("bpy")
    fake_bpy.types = types.SimpleNamespace(
        Material=type("Material", (), {}),
        ShaderNodeBsdfPrincipled=type("ShaderNodeBsdfPrincipled", (), {}),
        ShaderNodeBsdfDiffuse=type("ShaderNodeBsdfDiffuse", (), {}),
        ShaderNodeTexImage=type("ShaderNodeTexImage", (), {}),
        ShaderNodeMix=type("ShaderNodeMix", (), {}),
        ShaderNodeOutputMaterial=type("ShaderNodeOutputMaterial", (), {}),
        Node=type("Node", (), {}),
    )
    fake_utils = types.ModuleType("umodel_tools.utils")
    fake_props = types.ModuleType("umodel_tools.props_txt_parser")
    fake_props.Color = tuple

    previous_modules = {
        name: sys.modules.get(name)
        for name in (
            "bpy",
            "umodel_tools",
            "umodel_tools.game_profiles",
            "umodel_tools.utils",
            "umodel_tools.props_txt_parser",
        )
    }
    try:
        sys.modules["bpy"] = fake_bpy
        sys.modules["umodel_tools"] = package
        sys.modules["umodel_tools.game_profiles"] = profiles_package
        sys.modules["umodel_tools.utils"] = fake_utils
        sys.modules["umodel_tools.props_txt_parser"] = fake_props

        import importlib

        importlib.import_module("umodel_tools.import_support")
        importlib.import_module("umodel_tools.materials.rules")
        return importlib.import_module("umodel_tools.game_profiles.generic")
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


if __name__ == "__main__":
    main()
