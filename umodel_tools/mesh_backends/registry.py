"""Registry for pluggable mesh import backends.

This module must stay free of Blender imports; concrete backends should delay
Blender-specific imports until import time.
"""

from __future__ import annotations

import os

from .base import MeshImportBackend, MeshImportContext
from .psk_backend import PskMeshBackend
from .uemodel_backend import UModelMeshBackend


_BACKENDS: dict[str, MeshImportBackend] = {}


def _normalize_backend_id(backend_id: str) -> str:
    normalized = backend_id.strip().upper()
    if normalized in {"PSK/PSKX", "PSKX"}:
        return "PSK"
    return normalized


def register_mesh_backend(backend: MeshImportBackend) -> None:
    _BACKENDS[_normalize_backend_id(backend.id)] = backend


def unregister_mesh_backend(backend_id: str) -> None:
    _BACKENDS.pop(_normalize_backend_id(backend_id), None)


def list_mesh_backends() -> list[MeshImportBackend]:
    return sorted(_BACKENDS.values(), key=lambda backend: (-backend.priority, backend.id))


def get_supported_mesh_extensions() -> tuple[str, ...]:
    extensions: list[str] = []
    for backend in list_mesh_backends():
        for ext in backend.supported_extensions:
            ext = ext.lower()
            if ext not in extensions:
                extensions.append(ext)
    return tuple(extensions)


def get_mesh_backend_for_file(
    filepath: str,
    context: MeshImportContext | None = None,
    preferred_backend: str = "AUTO",
) -> MeshImportBackend | None:
    ext = os.path.splitext(filepath)[1].lower()
    preferred_backend = _normalize_backend_id(preferred_backend or "AUTO")

    candidates = list_mesh_backends()
    if preferred_backend != "AUTO":
        backend = _BACKENDS.get(preferred_backend)
        candidates = [backend] if backend is not None else []

    for backend in candidates:
        if ext not in backend.supported_extensions:
            continue
        if backend.can_import(filepath, context):
            return backend
    return None


def get_default_mesh_backend() -> MeshImportBackend | None:
    backends = list_mesh_backends()
    return backends[0] if backends else None


def register_experimental_mesh_backends() -> None:
    """Register disabled experimental backends for explicit developer testing."""
    register_mesh_backend(UModelMeshBackend())


register_mesh_backend(PskMeshBackend())
