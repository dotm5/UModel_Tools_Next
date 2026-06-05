import importlib
import os
import sys
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")
RULE_MODULE_NAME = "umodel_tools.materials.rules"
RULE_DIR = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules")


COMBINED_CASES = [
    ("D", "T_Example_01", "diffuse"),
    ("Maintex", "T_Noise_0023", "diffuse"),
    ("RMO", "T_Example_RMO", "rmo"),
    ("Mask1", "T_Kanmami_Body_Mask1_Map", "ww_mask1"),
    ("MatCapTexture", "MatCap_Toon9", "ww_matcap"),
]


def load_rule_module_module():
    package = types.ModuleType("umodel_tools")
    package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = package
    return importlib.import_module(RULE_MODULE_NAME)


def main():
    rule_module = load_rule_module_module()

    non_toml_rule_files = [
        name for name in os.listdir(RULE_DIR)
        if os.path.isfile(os.path.join(RULE_DIR, name)) and not name.endswith(".toml")
    ]
    if non_toml_rule_files:
        raise AssertionError(f"Rule directory should contain only TOML files: {non_toml_rule_files!r}")

    combined = rule_module.load_rule_sets([
        _rule_path("generic"),
        _rule_path("calabiyau_game"),
        _rule_path("wuthering_waves"),
    ])
    for tex_type, tex_short_name, expected in COMBINED_CASES:
        rule = combined.resolve(tex_type, tex_short_name)
        actual = rule.name if rule is not None else None
        if actual != expected:
            raise AssertionError(
                f"Unexpected combined rule for {tex_type!r}/{tex_short_name!r}: "
                f"{actual!r}, expected {expected!r}"
            )

    generic_only = rule_module.load_rule_set(_rule_path("generic"))
    if generic_only.resolve("Mask1", "T_Kanmami_Body_Mask1_Map") is not None:
        raise AssertionError("generic.toml should not match Wuthering Waves character Mask1 rules.")
    if generic_only.resolve("Maintex", "T_Noise_0023") is not None:
        raise AssertionError("generic.toml should not match CalabiyauGame Maintex rules.")

    print("TEST_rule_module_TOML_ONLY_OK")


def _rule_path(rule_name):
    return os.path.join(RULE_DIR, f"{rule_name}.toml")


if __name__ == "__main__":
    main()
