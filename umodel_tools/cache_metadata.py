"""Small, Blender-independent sidecars for fast asset-cache validation."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import typing as t


SCHEMA_VERSION = 1
METADATA_SUFFIX = ".umodel-cache.json"


@dataclasses.dataclass(frozen=True)
class FileFingerprint:
    path: str
    size: int
    mtime_ns: int


@dataclasses.dataclass(frozen=True)
class CacheMetadata:
    cache: FileFingerprint
    cache_version: int
    dependencies: tuple[FileFingerprint, ...]
    dependencies_complete: bool


def metadata_path(cache_path: str) -> str:
    return cache_path + METADATA_SUFFIX


def load_current_metadata(cache_path: str, cache_version: int) -> CacheMetadata | None:
    """Return metadata only when it matches the current cache file and format."""

    try:
        with open(metadata_path(cache_path), mode="r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
            return None
        if int(payload.get("cache_version", -1)) != cache_version:
            return None

        cache = _fingerprint_from_payload(payload.get("cache"))
        current_cache = fingerprint(cache_path)
        if cache is None or current_cache is None or cache != current_cache:
            return None

        dependencies = tuple(
            dependency
            for item in payload.get("dependencies", ())
            if (dependency := _fingerprint_from_payload(item)) is not None
        )
        if len(dependencies) != len(payload.get("dependencies", ())):
            return None
        return CacheMetadata(
            cache=cache,
            cache_version=cache_version,
            dependencies=dependencies,
            dependencies_complete=bool(payload.get("dependencies_complete", False)),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def dependencies_changed(metadata: CacheMetadata) -> bool | None:
    """Return None when the dependency snapshot is intentionally incomplete."""

    if not metadata.dependencies_complete:
        return None
    return any(fingerprint(item.path) != item for item in metadata.dependencies)


def write_metadata(
    cache_path: str,
    cache_version: int,
    source_paths: t.Iterable[str],
    dependencies_complete: bool,
) -> None:
    """Atomically write a cache and source fingerprint sidecar."""

    cache = fingerprint(cache_path)
    if cache is None:
        raise FileNotFoundError(cache_path)

    dependencies: list[FileFingerprint] = []
    seen: set[str] = set()
    for source_path in source_paths:
        normalized = os.path.normcase(os.path.abspath(source_path))
        if normalized in seen:
            continue
        seen.add(normalized)
        source = fingerprint(source_path)
        if source is None:
            dependencies_complete = False
            continue
        dependencies.append(source)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "cache_version": cache_version,
        "cache": dataclasses.asdict(cache),
        "dependencies_complete": dependencies_complete,
        "dependencies": [dataclasses.asdict(item) for item in dependencies],
    }
    destination = metadata_path(cache_path)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=os.path.basename(destination) + ".",
        suffix=".tmp",
        dir=os.path.dirname(destination),
        text=True,
    )
    try:
        with os.fdopen(descriptor, mode="w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def remove_metadata(cache_path: str) -> None:
    try:
        os.remove(metadata_path(cache_path))
    except FileNotFoundError:
        pass


def fingerprint(path: str) -> FileFingerprint | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return FileFingerprint(
        path=os.path.normcase(os.path.abspath(path)),
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
    )


def _fingerprint_from_payload(payload: t.Any) -> FileFingerprint | None:
    if not isinstance(payload, dict):
        return None
    try:
        return FileFingerprint(
            path=os.path.normcase(os.path.abspath(str(payload["path"]))),
            size=int(payload["size"]),
            mtime_ns=int(payload["mtime_ns"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


__all__ = (
    "CacheMetadata",
    "FileFingerprint",
    "METADATA_SUFFIX",
    "dependencies_changed",
    "fingerprint",
    "load_current_metadata",
    "metadata_path",
    "remove_metadata",
    "write_metadata",
)
