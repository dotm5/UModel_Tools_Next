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
    """Import *module_dotted_name* and fail if banned default-path dependencies appear."""
    before_import = set(sys.modules)
    _import_module_in_isolation(module_dotted_name)
    banned_roots = {"pil", "image", "sqlite3"}
    banned_roots.update({
        "".join(parts)
        for parts in (
            ("la", "rk"),
            ("ya", "ml"),
            ("_ya", "ml"),
            ("tq", "dm"),
            ("colo", "rama"),
        )
    })
    heavy = []
    for mod_name in sorted(set(sys.modules) - before_import):
        lower = mod_name.lower()
        if (
            lower.split(".", 1)[0] in banned_roots
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


def test_mesh_backends_no_bpy():
    _assert_bpy_not_loaded("umodel_tools.mesh_backends.backends")


# ── default import hot-path heavy dep tests ──────────────────────────────────

def test_rule_module_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.materials.rules")


def test_import_support_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.import_support")


def test_props_txt_parser_no_heavy_deps():
    _assert_no_heavy_deps("umodel_tools.props_txt_parser")


# ── runner ───────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("ueformat.reader no bpy", test_ueformat_reader_no_bpy),
        ("ueformat.model no bpy", test_ueformat_model_no_bpy),
        ("mesh_backends.backends no bpy", test_mesh_backends_no_bpy),
        ("rule_module no heavy deps", test_rule_module_no_heavy_deps),
        ("import_support no heavy deps", test_import_support_no_heavy_deps),
        ("props_txt_parser no heavy deps", test_props_txt_parser_no_heavy_deps),
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
