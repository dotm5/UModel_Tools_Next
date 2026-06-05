import contextlib
import io
import json
import os
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
REFERENCE_ROOT = os.path.join(ADDON_ROOT, "reference", "my real project", "model unpack")
REFERENCE_UEMODEL = os.path.join(
    REFERENCE_ROOT,
    "PM",
    "Content",
    "PaperMan",
    "SkinAssets",
    "Characters",
    "Kanami",
    "S103",
    "Mesh3D",
    "Kanami_Mesh_103.uemodel",
)
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "ueformat_pipeline")


class Tee(io.StringIO):
    def __init__(self, target):
        super().__init__()
        self.target = target

    def write(self, text):
        self.target.write(text)
        return super().write(text)

    def flush(self):
        self.target.flush()
        return super().flush()

    def fileno(self):
        return self.target.fileno()


def main():
    _clean_test_root()
    os.makedirs(TEST_ROOT, exist_ok=True)
    _enable_addon()
    try:
        test_backend_registration_and_reference_import()
        if os.path.isfile(REFERENCE_UEMODEL):
            test_direct_import_operator()
            test_map_static_fallback()
        else:
            print("TEST_UEFORMAT_REFERENCE_SKIPPED missing reference project")
        print("TEST_UEFORMAT_BLENDER_PIPELINE_OK")
    finally:
        _clear_scene()
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        _clean_test_root()


def test_backend_registration_and_reference_import():
    from umodel_tools.mesh_backends import backends  # pylint: disable=import-error,import-outside-toplevel

    invalid_path = os.path.join(TEST_ROOT, "synthetic_static.uemodel")
    with open(invalid_path, "wb") as file:
        file.write(b"UEFORMAT placeholder")

    backend = backends.get_mesh_backend_for_file(invalid_path)
    if backend is None or backend.id != "UEMODEL":
        raise AssertionError(f".uemodel backend should be registered by default, got {backend!r}")

    result = backend.import_mesh(
        invalid_path,
        backends.MeshImportContext(
            blender_context=bpy.context,
            source_filepath=invalid_path,
            options={"preferred_backend": "AUTO"},
        ),
    )
    if result.status != backends.FAILED:
        raise AssertionError(f"Expected failed status for invalid fixture, got {result.status!r}: {result.warnings!r}")

    if not os.path.isfile(REFERENCE_UEMODEL):
        return

    _clear_scene()
    reference_result = backend.import_mesh(
        REFERENCE_UEMODEL,
        backends.MeshImportContext(
            blender_context=bpy.context,
            source_filepath=REFERENCE_UEMODEL,
            options={
                "preferred_backend": "UEMODEL",
                "import_skeleton": True,
                "import_morph_targets": True,
            },
        ),
    )
    if reference_result.status != backends.IMPORTED:
        raise AssertionError(f"Expected reference import to succeed: {reference_result.warnings!r}")
    mesh_obj = reference_result.main_object
    _assert_kanami_mesh(mesh_obj, expect_shape_keys=True)
    armatures = [obj for obj in reference_result.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1 or len(armatures[0].data.bones) != 194:
        raise AssertionError("Expected one 194-bone Kanami armature.")
    _clear_scene()


def test_direct_import_operator():
    direct_root = os.path.join(TEST_ROOT, "direct_import")
    os.makedirs(direct_root, exist_ok=True)

    result = bpy.ops.umodel_tools.import_ueformat_model(
        filepath=REFERENCE_UEMODEL,
        umodel_export_dir=REFERENCE_ROOT,
        asset_cache_dir=direct_root,
    )
    if result != {"FINISHED"}:
        raise AssertionError(f"Expected UEFormat direct import to finish, got {result!r}")

    mesh_obj = _main_mesh_object()
    _assert_kanami_mesh(mesh_obj, expect_shape_keys=True)
    _assert_ueformat_asset_context(mesh_obj, direct_root)
    if not all(material is not None for material in mesh_obj.data.materials):
        raise AssertionError("Expected all Kanami material slots to be populated.")
    if not any(material and material.node_tree is not None for material in mesh_obj.data.materials):
        raise AssertionError("Expected imported Kanami materials to use node trees.")

    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1 or len(armatures[0].data.bones) != 194:
        raise AssertionError("Expected one 194-bone Kanami armature.")

    expected_cache = os.path.join(
        direct_root,
        "PM",
        "Content",
        "PaperMan",
        "SkinAssets",
        "Characters",
        "Kanami",
        "S103",
        "Mesh3D",
        "Kanami_Mesh_103.blend",
    )
    if not os.path.isfile(expected_cache):
        raise AssertionError(f"Expected asset cache file: {expected_cache}")

    rebuild_result = bpy.ops.umodel_tools.rebuild_ueformat_asset_materials()
    if rebuild_result != {"FINISHED"}:
        raise AssertionError(f"Expected UEFormat material rebuild to finish, got {rebuild_result!r}")
    if not all(material is not None for material in mesh_obj.data.materials):
        raise AssertionError("Expected rebuilt Kanami material slots to stay populated.")
    _clear_scene()


def test_map_static_fallback():
    map_root = os.path.join(TEST_ROOT, "map_static_fallback")
    os.makedirs(map_root, exist_ok=True)
    map_path = os.path.join(map_root, "kanami_skeletal_fallback_map.json")
    _write_map(map_path)

    stdout_capture = Tee(sys.stdout)
    stderr_capture = Tee(sys.stderr)
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            umodel_export_dir=REFERENCE_ROOT,
            asset_cache_dir=os.path.join(map_root, "asset_cache"),
            game_profile="generic",
            import_storage_mode="LINKED_ASSET_LIBRARY",
            missing_mesh_policy="WARN_SKIP",
            missing_material_policy="USE_PLACEHOLDER",
            missing_texture_policy="USE_PLACEHOLDER",
            validation_preset="CUSTOM",
            enable_import_validation=True,
            min_mesh_count=1,
            min_light_count=0,
            min_material_count=0,
            save_missing_asset_report=False,
            print_missing_asset_summary=True,
        )
        print(f"RESULT {result}")

    output = stdout_capture.getvalue() + stderr_capture.getvalue()
    if result != {"FINISHED"}:
        raise AssertionError(f"Map import failed:\n{output}")
    _assert_no_traceback_markers(output)
    if "static_fallback_skeletal_mesh_count=1" not in output:
        raise AssertionError(f"Expected one skeletal static fallback in summary:\n{output}")

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise AssertionError(f"Expected one placed static mesh instance, got {len(meshes)}")
    if meshes[0].data.shape_keys is not None:
        raise AssertionError("Map static fallback should not import UEFormat morph targets.")
    if [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]:
        raise AssertionError("Map static fallback should not import UEFormat armatures.")
    _clear_scene()


def _enable_addon():
    addon_utils.disable("umodel_tools", default_set=False)
    for module_name in list(sys.modules):
        if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
            del sys.modules[module_name]
    if ADDON_ROOT in sys.path:
        sys.path.remove(ADDON_ROOT)
    sys.path.insert(0, ADDON_ROOT)
    addon_utils.modules_refresh()
    bpy.ops.preferences.addon_enable(module="umodel_tools")


def _assert_kanami_mesh(mesh_obj, expect_shape_keys):
    if mesh_obj is None or mesh_obj.type != "MESH":
        raise AssertionError(f"Expected a main mesh object, got {mesh_obj!r}")
    if len(mesh_obj.data.vertices) != 27694:
        raise AssertionError(f"Unexpected Kanami vertex count: {len(mesh_obj.data.vertices)}")
    if len(mesh_obj.data.materials) != 7:
        raise AssertionError(f"Unexpected Kanami material slot count: {len(mesh_obj.data.materials)}")
    if len(mesh_obj.vertex_groups) != 194:
        raise AssertionError(f"Unexpected Kanami vertex group count: {len(mesh_obj.vertex_groups)}")
    shape_keys = mesh_obj.data.shape_keys
    if expect_shape_keys and (shape_keys is None or len(shape_keys.key_blocks) != 97):
        raise AssertionError("Expected Basis plus 96 Kanami shape keys.")
    if not expect_shape_keys and shape_keys is not None:
        raise AssertionError("Did not expect Kanami shape keys.")


def _main_mesh_object():
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj.get("umodel_tools_main_asset_object"):
            return obj
    raise AssertionError("Could not find imported UEFormat main mesh object.")


def _assert_ueformat_asset_context(mesh_obj, asset_cache_dir):
    from umodel_tools import panels  # pylint: disable=import-error,import-outside-toplevel

    props = mesh_obj.umodel_tools_asset
    if not props.enabled or not props.is_ueformat_asset:
        raise AssertionError("Expected imported object to be marked as a UEFormat asset.")
    if not props.ueformat_conflict_store_path.endswith("umodel_tools_conflict_overrides.json"):
        raise AssertionError(f"Unexpected conflict store path: {props.ueformat_conflict_store_path!r}")
    if not panels.UMODELTOOLS_PT_ueformat_asset_tools.poll(bpy.context):
        raise AssertionError("Expected UEFormat N-panel to poll true for the imported asset.")

    context_payload = json.loads(props.ueformat_context_json)
    if context_payload["uemodel_asset_path"] != os.path.relpath(REFERENCE_UEMODEL, REFERENCE_ROOT):
        raise AssertionError(f"Unexpected UEFormat asset path context: {context_payload!r}")
    if os.path.normcase(context_payload["asset_cache_dir"]) != os.path.normcase(asset_cache_dir):
        raise AssertionError(f"Unexpected asset cache dir in context: {context_payload!r}")
    if context_payload["game_profile"] != "generic":
        raise AssertionError(f"Unexpected game profile in context: {context_payload!r}")
    if len(context_payload["material_slots"]) != 7:
        raise AssertionError(f"Expected seven material slot descriptors, got {context_payload['material_slots']!r}")


def _write_map(map_path):
    object_path = (
        "/PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh3D/"
        "Kanami_Mesh_103.Kanami_Mesh_103"
    )
    with open(map_path, "w", encoding="utf-8") as file:
        json.dump(
            [
                {
                    "Type": "SkeletalMeshComponent",
                    "Name": "Kanami_Skeletal_Fallback",
                    "Outer": "Kanami_Skeletal_Fallback",
                    "ObjectPath": "/Game/Test/Kanami_Skeletal_Fallback.Kanami_Skeletal_Fallback",
                    "Properties": {
                        "SkeletalMesh": {"ObjectPath": object_path},
                        "RelativeLocation": {"X": 0, "Y": 0, "Z": 0},
                        "RelativeRotation": {"Roll": 0, "Pitch": 0, "Yaw": 0},
                        "RelativeScale3D": {"X": 1, "Y": 1, "Z": 1},
                        "bVisible": True,
                    },
                }
            ],
            file,
        )


def _clear_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _assert_no_traceback_markers(output):
    markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
    found = [marker for marker in markers if marker in output]
    if found:
        raise AssertionError(f"Import output contained traceback-like markers: {found!r}")


def _clean_test_root():
    resolved = os.path.abspath(TEST_ROOT)
    if os.path.isdir(resolved) and resolved.startswith(os.path.abspath(ADDON_ROOT)):
        shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
