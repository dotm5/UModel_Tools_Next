import importlib.util
import os
import sys


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
AUDIT_MODULE_PATH = os.path.join(ADDON_ROOT, "scripts", "maintenance", "audit_repo_layout.py")


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_repo_layout", AUDIT_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_repo_layout"] = module
    spec.loader.exec_module(module)
    return module


def test_forbidden_tracked_artifacts_are_reported():
    audit = load_audit_module()
    issues = audit.audit_tracked_paths([
        "dist/umodel_tools_next.zip",
        "tests/runtime/out.json",
        "tools/fmodel/FModel.exe",
        "tools/umodel_win32/umodel.exe",
        "reference/upstream.zip",
        "scene.blend",
        "texture_analysis.sqlite",
        "umodel_tools/__init__.py",
    ])
    paths = {issue.path for issue in issues}
    expected = {
        "dist/umodel_tools_next.zip",
        "tests/runtime/out.json",
        "tools/fmodel/FModel.exe",
        "tools/umodel_win32/umodel.exe",
        "reference/upstream.zip",
        "scene.blend",
        "texture_analysis.sqlite",
    }
    if paths != expected:
        raise AssertionError(f"Unexpected tracked artifact audit result: {paths!r}")
    for issue in issues:
        if issue.suggestion is None or not issue.suggestion.startswith("git rm --cached "):
            raise AssertionError(f"Tracked issue lacked git rm --cached suggestion: {issue!r}")


def test_root_local_artifacts_are_reported():
    audit = load_audit_module()
    issues = audit.audit_root_entries([
        "test_runtime_abc",
        "asset_cache",
        "asset_cache_v2",
        "toTest",
        "fmodel",
        "umodel_win32",
        "umodel_tools",
    ])
    paths = {issue.path for issue in issues}
    expected = {
        "test_runtime_abc",
        "asset_cache",
        "asset_cache_v2",
        "toTest",
        "fmodel",
        "umodel_win32",
    }
    if paths != expected:
        raise AssertionError(f"Unexpected root artifact audit result: {paths!r}")


def test_current_tracked_files_stay_inside_package_boundaries():
    audit = load_audit_module()
    git_listing_path = os.path.join(ADDON_ROOT, ".git")
    if not os.path.isdir(git_listing_path):
        return
    tracked_paths = audit.get_git_tracked_paths(audit.Path(ADDON_ROOT))
    issues = audit.audit_tracked_paths(tracked_paths)
    if issues:
        details = "\n".join(
            f"{issue.message}\nSuggested: {issue.suggestion}" for issue in issues
        )
        raise AssertionError(details)


def main():
    tests = [
        test_forbidden_tracked_artifacts_are_reported,
        test_root_local_artifacts_are_reported,
        test_current_tracked_files_stay_inside_package_boundaries,
    ]
    passed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            print(f"FAIL: {test_fn.__name__}: {exc}", file=sys.stderr)
    if passed != len(tests):
        raise SystemExit(f"{passed}/{len(tests)} package boundary tests passed.")
    print("TEST_PACKAGE_BOUNDARIES_OK")


if __name__ == "__main__":
    main()
