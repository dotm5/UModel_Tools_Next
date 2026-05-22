import os
import sys
import importlib.util


ADDON_ROOT = r"D:\addon"
GLASS_PROPS = (
    r"D:\UmodelExport\PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_PM_Glass_03b.props.txt"
)
WATER_PROPS = (
    r"D:\UmodelExport\PM\Content\PaperMan\Environment\Materials\Maps\Apartment\Wlbl"
    r"\MI_Envi_Wlbl_Water_01.props.txt"
)


def main():
    props_txt_parser = _load_module(
        "props_txt_parser",
        os.path.join(ADDON_ROOT, "umodel_tools", "props_txt_parser.py"),
    )
    material_shader_hints = _load_module(
        "material_shader_hints",
        os.path.join(ADDON_ROOT, "umodel_tools", "material_shader_hints.py"),
    )

    glass_ast, _, glass_overrides = props_txt_parser.parse_props_txt(GLASS_PROPS, mode="MATERIAL")
    glass_hint = material_shader_hints.infer_shader_hint(
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
    water_hint = material_shader_hints.infer_shader_hint(
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

    print("TEST_MATERIAL_SHADER_HINTS_OK")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if not os.path.exists(GLASS_PROPS):
        raise SystemExit(f"Missing test fixture: {GLASS_PROPS}")
    if not os.path.exists(WATER_PROPS):
        raise SystemExit(f"Missing test fixture: {WATER_PROPS}")
    main()
