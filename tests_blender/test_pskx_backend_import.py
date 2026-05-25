import os
import sys

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UMODEL_EXPORT_DIR = r"D:\UmodelExport"


def main():
    sys.path.insert(0, ADDON_ROOT)
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        from umodel_tools.mesh_backends import base, registry  # pylint: disable=import-error,import-outside-toplevel

        pskx_path = find_first_pskx(UMODEL_EXPORT_DIR)
        backend = registry.get_mesh_backend_for_file(pskx_path)
        if backend is None or backend.id != "PSK":
            raise AssertionError(f"Expected PSK backend for {pskx_path!r}, got {backend!r}")

        result = backend.import_mesh(
            pskx_path,
            base.MeshImportContext(
                blender_context=bpy.context,
                source_filepath=pskx_path,
                umodel_export_dir=UMODEL_EXPORT_DIR,
                options={"preferred_backend": "AUTO"},
            ),
        )
        if result.status != base.IMPORTED:
            raise AssertionError(f"Expected imported status, got {result.status!r}: {result.warnings!r}")
        if result.main_object is None:
            raise AssertionError("Backend did not return a main object.")
        if result.main_object.type != "MESH":
            raise AssertionError(f"Expected mesh object, got {result.main_object.type!r}")
        if result.main_object.data is None:
            raise AssertionError("Imported mesh object has no mesh data.")

        print(f"TEST_PSKX_BACKEND_IMPORT_OK {pskx_path}")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")


def find_first_pskx(root):
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.lower().endswith(".pskx"):
                return os.path.join(dirpath, filename)
    raise AssertionError(f"No .pskx file found under {root}")


if __name__ == "__main__":
    main()
