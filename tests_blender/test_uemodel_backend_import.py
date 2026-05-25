import os
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TEST_ROOT = os.path.join(ADDON_ROOT, "test_runtime_uemodel_backend")


def main():
    sys.path.insert(0, ADDON_ROOT)
    os.makedirs(TEST_ROOT, exist_ok=True)
    uemodel_path = os.path.join(TEST_ROOT, "synthetic_static.uemodel")
    with open(uemodel_path, "wb") as file:
        file.write(b"UEFORMAT placeholder")

    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        from umodel_tools.mesh_backends import base, registry  # pylint: disable=import-error,import-outside-toplevel
        from umodel_tools.mesh_backends.uemodel_backend import UModelMeshBackend

        backend = registry.get_mesh_backend_for_file(uemodel_path)
        if backend is not None:
            raise AssertionError(f".uemodel backend should not be registered by default, got {backend!r}")

        experimental_backend = UModelMeshBackend()
        result = experimental_backend.import_mesh(
            uemodel_path,
            base.MeshImportContext(
                blender_context=bpy.context,
                source_filepath=uemodel_path,
                options={"enable_experimental_uemodel_backend": True},
            ),
        )
        if result.status != base.UNSUPPORTED:
            raise AssertionError(f"Expected unsupported status, got {result.status!r}: {result.warnings!r}")

        print("TEST_UEMODEL_BACKEND_STUB_OK")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")


if __name__ == "__main__":
    main()
