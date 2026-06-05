import importlib
import os
import sys
import tempfile
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, ADDON_ROOT)
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")
RULE_MODULE_NAME = "umodel_tools.materials.rules"


def load_rule_module_module():
    package = types.ModuleType("umodel_tools")
    package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = package
    return importlib.import_module(RULE_MODULE_NAME)


def main():
    rule_module = load_rule_module_module()

    if rule_module.RULE_FILE_EXTENSIONS != frozenset({".toml"}):
        raise AssertionError(f"Only TOML should be accepted: {rule_module.RULE_FILE_EXTENSIONS!r}")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as rule_file:
        rule_file.write("name = \"Unsupported\"\ntexture_rules = []\n")
        unsupported_rule_path = rule_file.name

    try:
        try:
            rule_module.load_rule_set(unsupported_rule_path)
        except RuntimeError as exc:
            if "Unsupported material rule file extension" not in str(exc):
                raise AssertionError(f"Unexpected rejection message: {exc}") from exc
        else:
            raise AssertionError("Non-TOML material rule files should be rejected at runtime.")
    finally:
        os.remove(unsupported_rule_path)

    print("TEST_rule_module_UNSUPPORTED_FORMAT_REJECTED_OK")


if __name__ == "__main__":
    main()
