import importlib
import os
import sys
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "umodel_tools")


def test_mesh_backend_registry_defaults():
    original_package = sys.modules.pop("umodel_tools", None)
    original_bpy = sys.modules.pop("bpy", None)
    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [PACKAGE_ROOT]
    sys.modules["umodel_tools"] = fake_package
    try:
        backends = importlib.import_module("umodel_tools.mesh_backends.backends")

        if "bpy" in sys.modules:
            raise AssertionError("Registry import should not import bpy.")

        registered_backends = backends.list_mesh_backends()
        backend_ids = [backend.id for backend in registered_backends]
        if "PSK" not in backend_ids:
            raise AssertionError(f"PSK backend was not registered: {backend_ids!r}")

        extensions = backends.get_supported_mesh_extensions()
        if ".pskx" not in extensions or ".psk" not in extensions:
            raise AssertionError(f"Missing PSK extensions: {extensions!r}")
        if ".uemodel" not in extensions:
            raise AssertionError(f".uemodel should be exposed by default: {extensions!r}")
        if extensions.index(".pskx") > extensions.index(".psk"):
            raise AssertionError(f".pskx should be preferred before .psk: {extensions!r}")

        for filename in ("Example.pskx", "Example.psk"):
            backend = backends.get_mesh_backend_for_file(filename)
            if backend is None or backend.id != "PSK":
                raise AssertionError(f"Expected PSK backend for {filename!r}, got {backend!r}")

        uemodel_backend = backends.get_mesh_backend_for_file("Example.uemodel")
        if uemodel_backend is None or uemodel_backend.id != "UEMODEL":
            raise AssertionError(f"Expected UEMODEL backend for .uemodel, got {uemodel_backend!r}")

        if backends.get_mesh_backend_for_file("Example.pskx", preferred_backend="PSK").id != "PSK":
            raise AssertionError("Preferred PSK backend selection failed.")
        if backends.get_mesh_backend_for_file("Example.pskx", preferred_backend="UEMODEL") is not None:
            raise AssertionError("Preferred UEMODEL should not import PSK files.")

        print("TEST_MESH_BACKEND_REGISTRY_OK")
    finally:
        for module_name in list(sys.modules):
            if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
                del sys.modules[module_name]
        if original_package is not None:
            sys.modules["umodel_tools"] = original_package
        if original_bpy is not None:
            sys.modules["bpy"] = original_bpy


def main():
    test_mesh_backend_registry_defaults()


if __name__ == "__main__":
    main()
