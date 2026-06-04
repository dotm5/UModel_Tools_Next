"""Unit tests that verify pure-Python modules never import bpy or heavy dependencies."""

import importlib
import os
import sys
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")


def _import_module_in_isolation(dotted_name: str) -> None:
    """Import *dotted_name* under a fake umodel_tools package, no bpy mock."""
    original_package = sys.modules.pop("umodel_tools", None)
    original_bpy = sys.modules.pop("bpy", None)
    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = fake_package
    try:
        importlib.import_module(dotted_name)
    finally:
        # Clean up everything under umodel_tools to leave a fresh state.
        for module_name in list(sys.modules):
            if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
                del sys.modules[module_name]
        if original_package is not None:
            sys.modules["umodel_tools"] = original_package
        if original_bpy is not None:
            sys.modules["bpy"] = original_bpy


def _assert_bpy_not_loaded(module_dotted_name: str) -> None:
    """Import *module_dotted_name* and fail if bpy enters sys.modules."""
    _import_module_in_isolation(module_dotted_name)
    if "bpy" in sys.modules:
        raise AssertionError(f"{module_dotted_name} import loaded bpy into sys.modules.")


def _assert_no_heavy_deps(module_dotted_name: str) -> None:
    """Import *module_dotted_name* and fail if PIL, sqlite3, or magick deps appear."""
    _import_module_in_isolation(module_dotted_name)
    heavy = []
    for mod_name in sorted(sys.modules):
        lower = mod_name.lower()
        if (
            lower == "pil"
            or lower.startswith("pil.")
            or lower == "image"
            or lower.startswith("image.")
            or lower == "sqlite3"
            or "magick" in lower
            or "wand" in lower
        ):
            heavy.append(mod_name)
    if heavy:
        raise AssertionError(
            f"{module_dotted_name} import pulled in heavy dependencies: {heavy!r}"
        )


# ── bpy boundary tests ──────────────────────────────────────────────────────

def test_ueformat_reader_no_bpy():
    _assert_bpy_not_loaded("umodel_tools.ueformat.reader")


def test_ueformat_model_no_bpy():
    _assert_bpy_not_loaded("umodel_tools.ueformat.model")


def test_mesh_backend_base_no_bpy():
    _assert_bpy_not_loaded("umodel_tools.mesh_backends.base")


def test_mesh_backend_registry_no_bpy():
    _assert_bpy_not_loaded("umodel_tools.mesh_backends.registry")


# ── default import hot-path heavy dep tests ──────────────────────────────────

def test_material_decision_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.material_decision")


def test_material_rules_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.material_rules")


def test_texture_path_utils_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.texture_path_utils")


def test_material_shader_hints_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.material_shader_hints")


# ── runner ───────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("ueformat.reader no bpy", test_ueformat_reader_no_bpy),
        ("ueformat.model no bpy", test_ueformat_model_no_bpy),
        ("mesh_backends.base no bpy", test_mesh_backend_base_no_bpy),
        ("mesh_backends.registry no bpy", test_mesh_backend_registry_no_bpy),
        ("material_decision no heavy deps", test_material_decision_no_heavy_deps),
        ("material_rules no heavy deps", test_material_rules_no_heavy_deps),
        ("texture_path_utils no heavy deps", test_texture_path_utils_no_heavy_deps),
        ("material_shader_hints no heavy deps", test_material_shader_hints_no_heavy_deps),
    ]
    passed = 0
    for label, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            print(f"FAIL: {label}: {exc}", file=sys.stderr)
    if passed != len(tests):
        raise SystemExit(f"{passed}/{len(tests)} boundary tests passed.")
    print("TEST_IMPORT_BOUNDARIES_OK")


if __name__ == "__main__":
    main()
