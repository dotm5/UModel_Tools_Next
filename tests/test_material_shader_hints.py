import os
import sys
import importlib.util
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")
EXPORT_DIR = os.path.abspath(
    os.environ.get("UMODEL_TEST_EXPORT_DIR", os.path.join(ADDON_ROOT, os.pardir, "UmodelExport"))
)
GLASS_PROPS = (
    os.path.join(
        EXPORT_DIR,
        "PM",
        "Content",
        "PaperMan",
        "Environment",
        "Materials",
        "Maps",
        "Apartment",
        "Wlbl",
        "MI_PM_Glass_03b.props.txt",
    )
)
WATER_PROPS = (
    os.path.join(
        EXPORT_DIR,
        "PM",
        "Content",
        "PaperMan",
        "Environment",
        "Materials",
        "Maps",
        "Apartment",
        "Wlbl",
        "MI_Envi_Wlbl_Water_01.props.txt",
    )
)
WATER_02_PROPS = (
    os.path.join(
        EXPORT_DIR,
        "PM",
        "Content",
        "PaperMan",
        "Environment",
        "Materials",
        "Maps",
        "Apartment",
        "Wlbl",
        "MI_Envi_Wlbl_Water_02.props.txt",
    )
)
SCREEN_PROPS = (
    os.path.join(
        EXPORT_DIR,
        "PM",
        "Content",
        "PaperMan",
        "Environment",
        "Materials",
        "Maps",
        "Apartment",
        "Wlbl",
        "MI_Envi_Wlbl_Screen_01a.props.txt",
    )
)


def main():
    package = types.ModuleType("umodel_tools")
    package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = package
    props_txt_parser = _load_module(
        "props_txt_parser",
        os.path.join(ADDON_ROOT, "umodel_tools", "props_txt_parser.py"),
    )
    from umodel_tools.materials import rules as rule_module  # pylint: disable=import-outside-toplevel

    glass_ast, _, glass_overrides = props_txt_parser.parse_props_txt(GLASS_PROPS, mode="MATERIAL")
    glass_hint = rule_module.infer_shader_hint(
        material_name="MI_PM_Glass_03b",
        material_path_local=(
            r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl\MI_PM_Glass_03b.props.txt"
        ),
        parent_reference=props_txt_parser.extract_parent_reference(glass_ast),
        scalar_parameters=props_txt_parser.extract_scalar_parameters(glass_ast),
        vector_parameters=props_txt_parser.extract_vector_parameters(glass_ast),
        blend_mode=glass_overrides.get("BlendMode"),
    )

    if glass_hint is None:
        raise AssertionError("Expected MI_PM_Glass_03b to infer a glass shader.")
    if glass_hint.shader != "glass":
        raise AssertionError(f"Unexpected shader: {glass_hint.shader!r}")
    if glass_hint.alpha != 0.2:
        raise AssertionError(f"Unexpected alpha: {glass_hint.alpha!r}")
    if glass_hint.color != (0.135726, 0.398682, 0.447917, 1.0):
        raise AssertionError(f"Unexpected color: {glass_hint.color!r}")
    if glass_hint.roughness != 0.428572:
        raise AssertionError(f"Unexpected roughness: {glass_hint.roughness!r}")

    water_ast, _, water_overrides = props_txt_parser.parse_props_txt(WATER_PROPS, mode="MATERIAL")
    water_hint = rule_module.infer_shader_hint(
        material_name="MI_Envi_Wlbl_Water_01",
        material_path_local=(
            r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl\MI_Envi_Wlbl_Water_01.props.txt"
        ),
        parent_reference=props_txt_parser.extract_parent_reference(water_ast),
        scalar_parameters=props_txt_parser.extract_scalar_parameters(water_ast),
        vector_parameters=props_txt_parser.extract_vector_parameters(water_ast),
        blend_mode=water_overrides.get("BlendMode"),
    )

    if water_hint is None:
        raise AssertionError("Expected MI_Envi_Wlbl_Water_01 to infer a glass shader.")
    if water_hint.shader != "glass":
        raise AssertionError(f"Unexpected water shader: {water_hint.shader!r}")
    if water_hint.alpha != 1.0:
        raise AssertionError(f"Unexpected water alpha: {water_hint.alpha!r}")
    if water_hint.color != (0.254322, 0.377898, 0.65625, 1.0):
        raise AssertionError(f"Unexpected water color: {water_hint.color!r}")

    water_02_ast, _, water_02_overrides = props_txt_parser.parse_props_txt(WATER_02_PROPS, mode="MATERIAL")
    water_02_hint = rule_module.infer_shader_hint(
        material_name="MI_Envi_Wlbl_Water_02",
        material_path_local=(
            r"PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl\MI_Envi_Wlbl_Water_02.props.txt"
        ),
        parent_reference=props_txt_parser.extract_parent_reference(water_02_ast),
        scalar_parameters=props_txt_parser.extract_scalar_parameters(water_02_ast),
        vector_parameters=props_txt_parser.extract_vector_parameters(water_02_ast),
        blend_mode=water_02_overrides.get("BlendMode"),
    )

    if water_02_hint is None:
        raise AssertionError("Expected MI_Envi_Wlbl_Water_02 to infer a water glass shader.")
    if water_02_hint.shader != "glass":
        raise AssertionError(f"Unexpected water 02 shader: {water_02_hint.shader!r}")
    if water_02_hint.alpha != 0.8:
        raise AssertionError(f"Unexpected water 02 alpha: {water_02_hint.alpha!r}")
    if water_02_hint.color != (0.168213, 0.79363, 0.828125, 1.0):
        raise AssertionError(f"Unexpected water 02 color: {water_02_hint.color!r}")

    screen_ast, _, _ = props_txt_parser.parse_props_txt(SCREEN_PROPS, mode="MATERIAL")
    static_switches = props_txt_parser.extract_static_switch_parameters(screen_ast)
    expected_switches = {
        "usenormal": False,
        "useorm": False,
        "alpha is emissive?": True,
    }
    for name, expected in expected_switches.items():
        actual = static_switches.get(name)
        if actual is not expected:
            raise AssertionError(f"Unexpected static switch {name!r}: {actual!r}")

    print("TEST_MATERIAL_SHADER_HINTS_OK")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if not os.path.exists(GLASS_PROPS):
        raise SystemExit(f"Missing test fixture: {GLASS_PROPS}")
    if not os.path.exists(WATER_PROPS):
        raise SystemExit(f"Missing test fixture: {WATER_PROPS}")
    if not os.path.exists(WATER_02_PROPS):
        raise SystemExit(f"Missing test fixture: {WATER_02_PROPS}")
    if not os.path.exists(SCREEN_PROPS):
        raise SystemExit(f"Missing test fixture: {SCREEN_PROPS}")
    main()
