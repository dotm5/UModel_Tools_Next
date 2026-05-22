import importlib.util
import os
import sys


ADDON_ROOT = r"D:\addon"
RULE_MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "material_rules.py")
GENERIC_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "generic.yaml")


def load_material_rules_module():
    spec = importlib.util.spec_from_file_location("material_rules", RULE_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["material_rules"] = module
    spec.loader.exec_module(module)
    return module


def main():
    material_rules = load_material_rules_module()
    rules = material_rules.load_rule_set(GENERIC_RULE_PATH)

    cases = [
        ("D", "T_Example_01", "diffuse"),
        ("BC", "T_Example_01", "diffuse"),
        ("N", "BaseFlattenNormalMap", "normal"),
        ("ORM", "T_Birthdaygiftbox_ORM", "orm"),
        ("ORM", "T_Envi_Umeda_Cherrytree_Trunk_01_RMO", "rmo"),
        ("RM", "T_Evni_Michele_melonpa_RMO", "rmo"),
        ("RM", "T_DefaultWhite_Linear", "rm"),
        ("basecolor_low", "T_Envi_Leisure_pedestal_01b_D", "diffuse"),
        ("alpha", "T_Envi_Wlbl_keyboard_03b_Mask", None),
    ]

    for tex_type, tex_short_name, expected_name in cases:
        rule = rules.resolve(tex_type, tex_short_name)
        actual_name = rule.name if rule is not None else None
        if actual_name != expected_name:
            raise AssertionError(
                f"Unexpected rule for {tex_type!r} / {tex_short_name!r}: "
                f"{actual_name!r}, expected {expected_name!r}"
            )

    print("TEST_MATERIAL_RULES_YAML_OK")


if __name__ == "__main__":
    main()
