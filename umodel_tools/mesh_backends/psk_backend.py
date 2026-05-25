"""PSK/PSKX mesh backend."""

from __future__ import annotations

import contextlib
import io
import os

from .base import FAILED, IMPORTED, MISSING, MeshImportBackend, MeshImportContext, MeshImportResult


class PskMeshBackend(MeshImportBackend):
    id = "PSK"
    label = "PSK/PSKX"
    supported_extensions = (".pskx", ".psk")
    priority = 100
    supports_static_mesh = True
    supports_skeletal_mesh = False
    supports_armature = False
    supports_morph_targets = False
    supports_animation = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        return os.path.splitext(filepath)[1].lower() in self.supported_extensions

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        if not os.path.isfile(filepath):
            return MeshImportResult(
                status=MISSING,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=[f"Mesh file does not exist: {filepath}"],
            )

        blender_context = context.blender_context
        before_objects = set(getattr(getattr(blender_context, "scene", None), "objects", ()))

        from .. import psk_importer  # Imported lazily to keep registry importable without bpy.

        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            imported = psk_importer.import_psk_mesh(
                filepath=filepath,
                context=blender_context,
                import_bones=False,
            )

        main_object = getattr(blender_context, "object", None)
        scene_objects = getattr(getattr(blender_context, "scene", None), "objects", ())
        objects = [obj for obj in scene_objects if obj not in before_objects]
        if main_object is not None and main_object not in objects:
            objects.append(main_object)

        if not imported or main_object is None:
            return MeshImportResult(
                status=FAILED,
                objects=objects,
                main_object=main_object,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=["PSK importer returned no active object."],
                metadata={"importer_output": captured_stdout.getvalue()},
            )

        return MeshImportResult(
            status=IMPORTED,
            objects=objects,
            main_object=main_object,
            mesh_data=getattr(main_object, "data", None),
            source_filepath=filepath,
            backend_id=self.id,
            metadata={
                "animated_material_layout": filepath.lower().endswith(".psk"),
                "importer_output": captured_stdout.getvalue(),
            },
        )
