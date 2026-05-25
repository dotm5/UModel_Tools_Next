"""Experimental .uemodel mesh backend placeholder.

This module is a future extension point for a UEFormat/CUE4Parse-style static
mesh workflow. It is intentionally not registered by default and does not parse
files yet, so the current PSK/PSKX map import path stays unchanged.
"""

from __future__ import annotations

import os

from .base import UNSUPPORTED, MeshImportBackend, MeshImportContext, MeshImportResult


class UModelMeshBackend(MeshImportBackend):
    id = "UEMODEL"
    label = "Experimental .uemodel"
    supported_extensions = (".uemodel",)
    priority = 10
    supports_static_mesh = True
    supports_skeletal_mesh = False
    supports_armature = False
    supports_morph_targets = False
    supports_animation = False
    experimental = True
    enabled = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        if not self.enabled:
            return False
        options = context.options if context is not None else {}
        if not options.get("enable_experimental_uemodel_backend", False):
            return False
        return os.path.splitext(filepath)[1].lower() in self.supported_extensions

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        return MeshImportResult(
            status=UNSUPPORTED,
            source_filepath=filepath,
            backend_id=self.id,
            warnings=[
                ".uemodel mesh import is reserved for a future experimental backend and is not enabled."
            ],
        )
