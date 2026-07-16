import contextlib
import io
import json
import os
import shutil
import sys

import addon_utils
import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
UMODEL_EXPORT_DIR = os.environ.get("UMODEL_TEST_EXPORT_DIR", r"D:\UmodelExport")
ASSET_PATH = (
    "PM/Content/PaperMan/Environment/Meshes/Maps/Apartment/Envi_Wlbl/"
    "S_Evni_Wlbl_Fish_02/S_Evni_Wlbl_Fish_02_animation"
)
ANIMATION_PATH = (
    "PM/Content/PaperMan/Environment/Meshes/Maps/Apartment/Envi_Wlbl/"
    "S_Evni_Wlbl_Fish_02/S_Evni_Wlbl_Fish_02_animation_Anim"
)
PSK_PATH = os.path.join(UMODEL_EXPORT_DIR, *ASSET_PATH.split("/")) + ".psk"
PSA_PATH = os.path.join(UMODEL_EXPORT_DIR, *ANIMATION_PATH.split("/")) + ".psa"
TEST_ROOT = os.path.join(ADDON_ROOT, "tests", "runtime", "skeletal_psa_preview")
LAST_IMPORT_PARAMS = os.path.join(ADDON_ROOT, "umodel_tools", "last_import_params.json")


class Tee(io.StringIO):
    def __init__(self, target):
        super().__init__()
        self.target = target

    def write(self, text):
        self.target.write(text)
        return super().write(text)

    def flush(self):
        self.target.flush()

    def fileno(self):
        return self.target.fileno()


def main():
    _require_fixture(PSK_PATH)
    _require_fixture(PSA_PATH)
    _clean_test_root()
    os.makedirs(TEST_ROOT, exist_ok=True)
    _enable_addon()
    try:
        test_backend_skeleton_and_psa_action()
        test_map_operator_rigged_psa_preview()
        print("TEST_SKELETAL_PSA_PREVIEW_OK")
    finally:
        _clear_scene()
        bpy.ops.preferences.addon_disable(module="umodel_tools")
        _clean_test_root()
        if os.path.isfile(LAST_IMPORT_PARAMS):
            os.remove(LAST_IMPORT_PARAMS)


def test_backend_skeleton_and_psa_action():
    from umodel_tools import psa_importer  # pylint: disable=import-error,import-outside-toplevel
    from umodel_tools.mesh_backends import backends  # pylint: disable=import-error,import-outside-toplevel

    _clear_scene()
    backend = backends.get_mesh_backend_for_file(PSK_PATH)
    if backend is None or backend.id != "PSK":
        raise AssertionError(f"Expected PSK backend, got {backend!r}")

    result = backend.import_mesh(
        PSK_PATH,
        backends.MeshImportContext(
            blender_context=bpy.context,
            source_filepath=PSK_PATH,
            umodel_export_dir=UMODEL_EXPORT_DIR,
            options={"preferred_backend": "PSK", "import_skeleton": True},
        ),
    )
    if result.status != backends.IMPORTED:
        raise AssertionError(f"Skeleton import failed: {result.warnings!r}")
    armatures = [obj for obj in result.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1 or len(armatures[0].data.bones) != 11:
        raise AssertionError("Expected one 11-bone Fish_02 armature.")
    mesh = result.main_object
    if mesh is None or mesh.type != "MESH":
        raise AssertionError("PSK backend did not preserve the mesh as main_object.")
    if mesh.data.shape_keys is not None:
        raise AssertionError("Skeletal map preview must not import morph targets.")
    modifiers = [modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"]
    if len(modifiers) != 1 or modifiers[0].object != armatures[0]:
        raise AssertionError("Fish mesh is not bound to the imported armature.")

    animation_result = psa_importer.import_psa_action(
        filepath=PSA_PATH,
        armature_object=armatures[0],
        preferred_sequence_name="S_Evni_Wlbl_Fish_02_animation_Anim",
    )
    if animation_result.sequence.frame_count != 61 or animation_result.sequence.fps != 30.0:
        raise AssertionError(f"Unexpected PSA sequence metadata: {animation_result.sequence!r}")
    if animation_result.matched_bone_count != 11 or animation_result.missing_bone_names:
        raise AssertionError("PSA bones did not map one-to-one to the Fish_02 armature.")
    if animation_result.fcurve_count != 110:
        raise AssertionError(f"Expected 110 PSA f-curves, got {animation_result.fcurve_count}.")
    if armatures[0].animation_data is None or armatures[0].animation_data.action != animation_result.action:
        raise AssertionError("PSA Action was not assigned to the Fish_02 armature.")

    bpy.context.scene.frame_set(0)
    first_matrix = armatures[0].pose.bones["bone02"].matrix.copy()
    bpy.context.scene.frame_set(30)
    middle_matrix = armatures[0].pose.bones["bone02"].matrix.copy()
    matrix_delta = max(
        abs(first_matrix[row][column] - middle_matrix[row][column])
        for row in range(4)
        for column in range(4)
    )
    if matrix_delta <= 1e-5:
        raise AssertionError("Fish_02 pose did not change between PSA frames 0 and 30.")
    print(
        "TEST_PSA_ACTION_DIRECT_OK "
        f"bones={animation_result.matched_bone_count} frames={animation_result.sequence.frame_count} "
        f"fcurves={animation_result.fcurve_count} pose_delta={matrix_delta:.6f}"
    )
    _clear_scene()


def test_map_operator_rigged_psa_preview():
    map_path = os.path.join(TEST_ROOT, "fish_02_skeletal_preview.json")
    _write_map(map_path)

    stdout_capture = Tee(sys.stdout)
    stderr_capture = Tee(sys.stderr)
    with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
        result = bpy.ops.umodel_tools.import_unreal_map(
            filepath=map_path,
            umodel_export_dir=UMODEL_EXPORT_DIR,
            asset_cache_dir=os.path.join(TEST_ROOT, "asset_cache"),
            game_profile="generic",
            import_skeletal_mesh_as_static_fallback=True,
            import_skeletal_mesh_with_armature=True,
            import_psa_animations=True,
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
        raise AssertionError(f"Rigged map preview failed:\n{output}")
    _assert_no_traceback_markers(output)
    for marker in (
        "rigged_skeletal_mesh_count=1",
        "imported_armature_count=1",
        "imported_animation_count=1",
        "local_object_count=1",
        "Basic PSA preview imported",
    ):
        if marker not in output:
            raise AssertionError(f"Missing {marker!r} from map output:\n{output}")

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(meshes) != 1 or len(armatures) != 1:
        raise AssertionError(f"Expected one mesh and one armature, got {len(meshes)} and {len(armatures)}.")
    if meshes[0].data.shape_keys is not None:
        raise AssertionError("Map skeletal preview unexpectedly imported shape keys.")
    if len(armatures[0].data.bones) != 11:
        raise AssertionError("Map skeletal preview did not preserve the 11-bone skeleton.")
    expected_location = (1.0, -2.0, 3.0)
    if any(abs(actual - expected) > 1e-5 for actual, expected in zip(armatures[0].location, expected_location)):
        raise AssertionError(f"Map transform was not applied to the armature root: {tuple(armatures[0].location)!r}")
    if meshes[0].parent != armatures[0]:
        raise AssertionError("Map skeletal mesh is not parented to the transformed armature root.")
    if armatures[0].animation_data is None or armatures[0].animation_data.action is None:
        raise AssertionError("Map skeletal preview did not assign a PSA Action.")
    if armatures[0].get("umodel_tools_preview_fallback") != "rigged_skeletal_preview":
        raise AssertionError("Map skeletal preview provenance marker is missing.")
    print(
        "TEST_MAP_SKELETAL_PSA_PREVIEW_OK "
        f"mesh={len(meshes)} armature={len(armatures)} bones={len(armatures[0].data.bones)} "
        f"action={armatures[0].animation_data.action.name}"
    )
    _clear_scene()


def _write_map(filepath):
    with open(filepath, "w", encoding="utf-8") as stream:
        json.dump(
            [
                {
                    "Type": "SkeletalMeshComponent",
                    "Name": "Fish_02_Skeletal_Preview",
                    "Outer": "Fish_02_Skeletal_Preview",
                    "ObjectPath": "/Game/Test/Fish_02_Skeletal_Preview.Fish_02_Skeletal_Preview",
                    "Properties": {
                        "SkeletalMesh": {
                            "ObjectName": "SkeletalMesh'S_Evni_Wlbl_Fish_02_animation'",
                            "ObjectPath": ASSET_PATH + ".0",
                        },
                        "AnimationData": {
                            "AnimToPlay": {
                                "ObjectName": "AnimSequence'S_Evni_Wlbl_Fish_02_animation_Anim'",
                                "ObjectPath": ANIMATION_PATH + ".0",
                            }
                        },
                        "RelativeLocation": {"X": 100.0, "Y": 200.0, "Z": 300.0},
                        "RelativeRotation": {"Roll": 0.0, "Pitch": 0.0, "Yaw": 90.0},
                        "RelativeScale3D": {"X": 1.0, "Y": 1.0, "Z": 1.0},
                        "bVisible": True,
                    },
                }
            ],
            stream,
        )


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


def _clear_scene():
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)


def _assert_no_traceback_markers(output):
    markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
    found = [marker for marker in markers if marker in output]
    if found:
        raise AssertionError(f"Import output contained traceback-like markers: {found!r}")


def _require_fixture(filepath):
    if not os.path.isfile(filepath):
        raise AssertionError(f"Required skeletal preview fixture is missing: {filepath}")


def _clean_test_root():
    resolved = os.path.abspath(TEST_ROOT)
    if os.path.isdir(resolved) and resolved.startswith(os.path.abspath(ADDON_ROOT)):
        shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
