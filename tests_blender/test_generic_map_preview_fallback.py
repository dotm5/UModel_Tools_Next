"""Blender-side proof for the FModel-style generic map preview fallbacks."""

import contextlib
import io
import json
import os
import sys
import tempfile

import bpy


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PACKAGE = "Game/Content/Maps/SyntheticPreview"


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


def ref(index, object_type, object_name):
    return {
        "ObjectName": f"{object_type}'SyntheticPreview:PersistentLevel.{object_name}'",
        "ObjectPath": f"{PACKAGE}.{index}",
    }


def mesh_ref(shape):
    return {
        "ObjectName": f"StaticMesh'{shape}'",
        "ObjectPath": f"Engine/Content/BasicShapes/{shape}.2",
    }


def synthetic_map():
    return [
        {
            "Type": "Actor",
            "Name": "Actor0",
            "Properties": {
                "InstanceComponents": [
                    ref(3, "CustomStaticMeshComponent", "TemplateBacked"),
                    ref(4, "StaticMeshComponent", "Cube"),
                    ref(5, "SplineMeshComponent", "Spline"),
                ]
            },
        },
        {
            "Type": "SceneComponent",
            "Name": "Root",
            "Properties": {"RelativeLocation": {"X": 100, "Y": 200, "Z": 300}},
        },
        {
            "Type": "CustomStaticMeshComponent",
            "Name": "Template",
            "Properties": {"StaticMesh": mesh_ref("Sphere")},
        },
        {
            "Type": "CustomStaticMeshComponent",
            "Name": "TemplateBacked",
            "Template": ref(2, "CustomStaticMeshComponent", "Template"),
            "Properties": {"AttachParent": ref(1, "SceneComponent", "Root")},
        },
        {
            "Type": "StaticMeshComponent",
            "Name": "Cube",
            "Properties": {
                "StaticMesh": mesh_ref("Cube"),
                "AttachParent": ref(1, "SceneComponent", "Root"),
                "RelativeLocation": {"X": 100, "Y": 0, "Z": 0},
            },
        },
        {
            "Type": "SplineMeshComponent",
            "Name": "Spline",
            "Properties": {
                "StaticMesh": mesh_ref("Cube"),
                "AttachParent": ref(1, "SceneComponent", "Root"),
                "SplineParams": {
                    "StartPos": {"X": 0, "Y": 0, "Z": 0},
                    "EndPos": {"X": 200, "Y": 0, "Z": 0},
                },
            },
        },
        {"Type": "Level", "Name": "PersistentLevel", "Actors": [ref(0, "Actor", "Actor0")]},
        {
            "Type": "World",
            "Name": "SyntheticPreview",
            "Package": PACKAGE,
            "PersistentLevel": ref(6, "Level", "PersistentLevel"),
            "ExtraReferencedObjects": [],
            "StreamingLevels": [],
        },
    ]


def main():
    sys.path.insert(0, ADDON_ROOT)
    bpy.ops.preferences.addon_enable(module="umodel_tools")
    try:
        clear_scene()
        with tempfile.TemporaryDirectory(prefix="umodel_tools_preview_") as runtime_dir:
            map_path = os.path.join(runtime_dir, "SyntheticPreview.json")
            export_dir = os.path.join(runtime_dir, "empty_export")
            asset_cache_dir = os.path.join(runtime_dir, "asset_cache")
            os.makedirs(export_dir, exist_ok=True)
            os.makedirs(asset_cache_dir, exist_ok=True)
            with open(map_path, mode="w", encoding="utf-8") as file:
                json.dump(synthetic_map(), file)

            stdout_capture = Tee(sys.stdout)
            stderr_capture = Tee(sys.stderr)
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                result = bpy.ops.umodel_tools.import_unreal_map(
                    filepath=map_path,
                    umodel_export_dir=export_dir,
                    asset_cache_dir=asset_cache_dir,
                    game_profile="generic",
                    path_inference_mode="BASIC_DEFAULT",
                    missing_mesh_policy="WARN_SKIP",
                    missing_material_policy="USE_PLACEHOLDER",
                    missing_texture_policy="USE_PLACEHOLDER",
                    enable_import_validation=False,
                    report_path_resolution_stats=True,
                    print_missing_asset_summary=True,
                    save_missing_asset_report=False,
                )
                print(f"RESULT {result}")

            output = stdout_capture.getvalue() + stderr_capture.getvalue()
            if result != {"FINISHED"}:
                raise AssertionError(f"Synthetic preview import failed:\n{output}")
            assert_no_traceback_markers(output)

            meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
            if len(meshes) != 3:
                mesh_names = [obj.name for obj in meshes]
                raise AssertionError(f"Expected 3 fallback meshes, found {len(meshes)}: {mesh_names!r}")
            procedural = [obj for obj in meshes if obj.get("umodel_tools_asset_fallback") == "procedural_basic_shape"]
            if len(procedural) != 3:
                raise AssertionError(f"Expected 3 procedural shapes, found {len(procedural)}")
            spline = next(
                (obj for obj in meshes if obj.get("umodel_tools_geometry_fallback") == "spline_chord_approximation"),
                None,
            )
            template = next(
                (obj for obj in meshes if obj.get("umodel_tools_reference_fallback") == "template_mesh_reference"),
                None,
            )
            if spline is None or template is None:
                raise AssertionError("Spline or template fallback marker was not preserved on imported objects.")

            cube = next(
                obj for obj in procedural
                if obj.data.get("umodel_tools_basic_shape") == "Cube"
                and obj.get("umodel_tools_geometry_fallback") is None
            )
            expected_location = (2.0, -2.0, 3.0)
            if any(abs(actual - expected) > 1e-5 for actual, expected in zip(cube.location, expected_location)):
                raise AssertionError(f"AttachParent transform was not composed: {tuple(cube.location)!r}")
            if "procedural_basic_shape_count=3" not in output:
                raise AssertionError(f"Procedural fallback count missing from output:\n{output}")
            if "template_mesh_fallback_count=1" not in output:
                raise AssertionError(f"Template fallback count missing from output:\n{output}")
            if "approximate_spline_mesh_count=1" not in output:
                raise AssertionError(f"Spline fallback count missing from output:\n{output}")

            print("TEST_GENERIC_MAP_PREVIEW_FALLBACK_OK mesh_count=3 procedural=3 template=1 spline=1")
    finally:
        bpy.ops.preferences.addon_disable(module="umodel_tools")


def clear_scene():
    for obj in list(bpy.context.scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def assert_no_traceback_markers(output):
    markers = ("AttributeError", "TypeError", "KeyError", "Traceback (most recent call last)")
    found = [marker for marker in markers if marker in output]
    if found:
        raise AssertionError(f"Import output contained traceback-like markers: {found!r}")


if __name__ == "__main__":
    main()
