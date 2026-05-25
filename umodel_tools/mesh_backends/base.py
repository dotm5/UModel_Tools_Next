"""Lightweight mesh backend interfaces.

This module intentionally has no Blender dependency so backend selection can be
tested with normal Python.
"""

from __future__ import annotations

import dataclasses
import typing as t


IMPORTED = "imported"
MISSING = "missing"
UNSUPPORTED = "unsupported"
FAILED = "failed"


@dataclasses.dataclass
class MeshImportContext:
    blender_context: t.Any = None
    asset_path: str = ""
    asset_name: str = ""
    source_filepath: str = ""
    asset_library_dir: str = ""
    umodel_export_dir: str = ""
    import_storage_mode: str = ""
    game_profile: str = ""
    import_report: t.Any = None
    options: dict[str, t.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class MeshImportResult:
    status: str
    objects: list[t.Any] = dataclasses.field(default_factory=list)
    main_object: t.Any = None
    mesh_data: t.Any = None
    source_filepath: str = ""
    backend_id: str = ""
    warnings: list[str] = dataclasses.field(default_factory=list)
    metadata: dict[str, t.Any] = dataclasses.field(default_factory=dict)


class MeshImportBackend:
    id: str = ""
    label: str = ""
    supported_extensions: tuple[str, ...] = ()
    priority: int = 0
    supports_static_mesh: bool = True
    supports_skeletal_mesh: bool = False
    supports_armature: bool = False
    supports_morph_targets: bool = False
    supports_animation: bool = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        return filepath.lower().endswith(self.supported_extensions)

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        raise NotImplementedError
