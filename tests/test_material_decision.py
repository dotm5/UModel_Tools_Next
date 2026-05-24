import os
import sys


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")


def main():
    sys.path.insert(0, MODULE_ROOT)
    import material_decision  # pylint: disable=import-outside-toplevel
    import texture_path_utils  # pylint: disable=import-outside-toplevel

    diffuse = material_decision.TextureRule(
        name="diffuse",
        diffuse=True,
        prefer_suffix=False,
        param_names=frozenset({"d"}),
        suffixes=frozenset({"d"}),
        nodes=(),
        connections=(),
    )
    orm = material_decision.TextureRule(
        name="orm",
        diffuse=False,
        prefer_suffix=True,
        param_names=frozenset({"orm"}),
        suffixes=frozenset({"orm", "ao_r_m_mask"}),
        nodes=(),
        connections=(),
    )
    rules = material_decision.MaterialRuleSet([diffuse, orm])

    if rules.resolve("D", "T_Example_ORM").name != "orm":
        raise AssertionError("prefer_suffix should win before parameter-name matching.")
    if rules.resolve("D", "T_Example_D").name != "diffuse":
        raise AssertionError("parameter-name matching should preserve current diffuse behavior.")
    if rules.resolve("Unknown", "T_Example_AO_R_M_MASK").name != "orm":
        raise AssertionError("compound suffix fallback should preserve current behavior.")
    if rules.resolve("Unknown", "T_Example_BaseColor") is not None:
        raise AssertionError("unknown texture should not resolve without matching rule data.")

    if texture_path_utils.normalize_texture_name("/Game/Textures/T_Example_D") != "t_example_d":
        raise AssertionError("texture basename normalization changed.")
    if not texture_path_utils.matches_texture_suffix("T_Example_AO_R_M_MASK", frozenset({"ao_r_m_mask"})):
        raise AssertionError("compound suffix matching changed.")

    print("TEST_MATERIAL_DECISION_OK")


if __name__ == "__main__":
    main()
