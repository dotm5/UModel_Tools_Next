"""Resolve UEFormat material slot references to exported material JSON files."""

from __future__ import annotations

import dataclasses
import os
import typing as t

from .. import fmodel_material_json
from .. import umodel_path_resolver


RESOLVED = "resolved"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"


@dataclasses.dataclass
class MaterialSlotReference:
    slot_index: int
    material_name: str
    material_path: str
    first_index: int
    num_faces: int


@dataclasses.dataclass
class ResolvedMaterialDescriptor:
    slot_index: int
    material_name: str
    material_path: str
    descriptor_path: str
    json_path: str
    status: str
    candidates: list[str]
    first_index: int
    num_faces: int

    def to_backend_dict(self) -> dict[str, t.Any]:
        return {
            "material_name": self.material_name,
            "material_path": self.material_path,
            "descriptor_path": self.descriptor_path,
            "first_index": self.first_index,
            "num_faces": self.num_faces,
            "slot_index": self.slot_index,
            "status": self.status,
            "candidates": list(self.candidates),
            "json_path": self.json_path,
        }


def resolve_material_descriptors(
    slots: t.Iterable[t.Any],
    uemodel_filepath: str,
    export_root: str = "",
    settings: umodel_path_resolver.UModelPathInferenceSettings | None = None,
    overrides: t.Mapping[t.Any, t.Any] | None = None,
) -> list[ResolvedMaterialDescriptor]:
    settings = settings or umodel_path_resolver.UModelPathInferenceSettings()
    uemodel_dir = os.path.dirname(os.path.abspath(uemodel_filepath))
    export_root_abs = os.path.abspath(export_root) if export_root else ""
    descriptors: list[ResolvedMaterialDescriptor] = []

    for fallback_index, slot_like in enumerate(slots):
        slot = _slot_reference_from_any(slot_like, fallback_index)
        descriptor = _resolve_override(slot, uemodel_dir, export_root_abs, overrides)
        if descriptor is None:
            descriptor = _resolve_slot(slot, uemodel_dir, export_root_abs, settings)
        descriptors.append(descriptor)

    return descriptors


def _slot_reference_from_any(slot_like: t.Any, fallback_index: int) -> MaterialSlotReference:
    slot_index = getattr(slot_like, "slot_index", fallback_index)
    if slot_index is None:
        slot_index = fallback_index

    return MaterialSlotReference(
        slot_index=int(slot_index),
        material_name=str(getattr(slot_like, "material_name", "") or ""),
        material_path=str(getattr(slot_like, "material_path", "") or ""),
        first_index=int(getattr(slot_like, "first_index", 0) or 0),
        num_faces=int(getattr(slot_like, "num_faces", 0) or 0),
    )


def _resolve_slot(
    slot: MaterialSlotReference,
    uemodel_dir: str,
    export_root: str,
    settings: umodel_path_resolver.UModelPathInferenceSettings,
) -> ResolvedMaterialDescriptor:
    direct_candidates: list[str] = []

    if slot.material_path:
        direct_candidates.append(
            fmodel_material_json.json_path_from_material_reference(slot.material_path)
        )

    json_path = _find_existing_material_json(
        direct_candidates,
        uemodel_dir,
        export_root,
        prefer_export_root=True,
    )
    if json_path:
        return _descriptor_from_json(slot, json_path, uemodel_dir, export_root, [json_path])

    safe_name = slot.material_name.strip()
    name_candidates = [
        f"{safe_name}.json",
        os.path.join("Materials", f"{safe_name}.json"),
        os.path.join(safe_name, f"{safe_name}.json"),
    ]
    json_path = _find_existing_material_json_in_dir(name_candidates, uemodel_dir)
    if json_path:
        return _descriptor_from_json(slot, json_path, uemodel_dir, export_root, [json_path])

    inferred = _resolve_by_umodel_path_inference(slot, uemodel_dir, export_root, settings)
    if inferred is not None:
        return inferred

    return _fallback_descriptor(slot, UNRESOLVED)


def _resolve_by_umodel_path_inference(
    slot: MaterialSlotReference,
    uemodel_dir: str,
    export_root: str,
    settings: umodel_path_resolver.UModelPathInferenceSettings,
) -> ResolvedMaterialDescriptor | None:
    if not export_root or not settings.enable_umodel_path_inference:
        return None

    asset_reference = _asset_reference_for_inference(slot)
    if not asset_reference:
        return None

    resolved = umodel_path_resolver.resolve_umodel_export_asset_path(
        export_root,
        asset_reference,
        (".json",),
        settings=settings,
    )
    if resolved.found and resolved.path:
        return _descriptor_from_json(slot, resolved.path, uemodel_dir, export_root, [resolved.path])

    if resolved.status == "ambiguous":
        candidates = _ambiguous_suffix_candidates(export_root, asset_reference, (".json",), settings)
        return _fallback_descriptor(slot, AMBIGUOUS, candidates=candidates)

    return None


def _asset_reference_for_inference(slot: MaterialSlotReference) -> str:
    if slot.material_path:
        return fmodel_material_json.json_path_from_material_reference(slot.material_path)
    if slot.material_name:
        return slot.material_name
    return ""


def _resolve_override(
    slot: MaterialSlotReference,
    uemodel_dir: str,
    export_root: str,
    overrides: t.Mapping[t.Any, t.Any] | None,
) -> ResolvedMaterialDescriptor | None:
    if not overrides:
        return None

    override = _lookup_override(slot, overrides)
    if override in (None, ""):
        return None

    if isinstance(override, dict):
        json_path = str(override.get("json_path", "") or override.get("path", "") or "")
        descriptor_path = str(override.get("descriptor_path", "") or "")
        if json_path and not os.path.isabs(json_path):
            json_path = os.path.join(export_root or uemodel_dir, json_path)
        if json_path and not descriptor_path:
            descriptor_path = _descriptor_reference_from_json(json_path, slot.material_name, uemodel_dir, export_root)
        if descriptor_path:
            return ResolvedMaterialDescriptor(
                slot_index=slot.slot_index,
                material_name=slot.material_name,
                material_path=slot.material_path,
                descriptor_path=os.path.normpath(descriptor_path),
                json_path=os.path.normpath(json_path) if json_path else "",
                status=str(override.get("status", RESOLVED) or RESOLVED),
                candidates=_json_safe_candidates([json_path] if json_path else [], export_root, uemodel_dir),
                first_index=slot.first_index,
                num_faces=slot.num_faces,
            )
        return None

    override_path = str(override)
    json_path = override_path
    if not os.path.isabs(json_path):
        json_path = os.path.join(export_root or uemodel_dir, json_path)

    if override_path.lower().endswith(".json") or os.path.isfile(json_path):
        return _descriptor_from_json(slot, json_path, uemodel_dir, export_root, [json_path])

    return ResolvedMaterialDescriptor(
        slot_index=slot.slot_index,
        material_name=slot.material_name,
        material_path=slot.material_path,
        descriptor_path=os.path.normpath(override_path),
        json_path="",
        status=RESOLVED,
        candidates=[],
        first_index=slot.first_index,
        num_faces=slot.num_faces,
    )


def _lookup_override(slot: MaterialSlotReference, overrides: t.Mapping[t.Any, t.Any]) -> t.Any:
    keys = (
        slot.slot_index,
        str(slot.slot_index),
        slot.material_path,
        slot.material_name,
        (slot.slot_index, slot.material_path),
        (slot.slot_index, slot.material_name),
    )
    for key in keys:
        if key in overrides:
            return overrides[key]
    return None


def _descriptor_from_json(
    slot: MaterialSlotReference,
    json_path: str,
    uemodel_dir: str,
    export_root: str,
    candidates: t.Iterable[str],
) -> ResolvedMaterialDescriptor:
    json_path = os.path.normpath(json_path)
    return ResolvedMaterialDescriptor(
        slot_index=slot.slot_index,
        material_name=slot.material_name,
        material_path=slot.material_path,
        descriptor_path=_descriptor_reference_from_json(json_path, slot.material_name, uemodel_dir, export_root),
        json_path=json_path,
        status=RESOLVED,
        candidates=_json_safe_candidates(candidates, export_root, uemodel_dir),
        first_index=slot.first_index,
        num_faces=slot.num_faces,
    )


def _fallback_descriptor(
    slot: MaterialSlotReference,
    status: str,
    candidates: t.Iterable[str] = (),
) -> ResolvedMaterialDescriptor:
    descriptor_path = slot.material_path or f"{slot.material_name}.{slot.material_name}"
    return ResolvedMaterialDescriptor(
        slot_index=slot.slot_index,
        material_name=slot.material_name,
        material_path=slot.material_path,
        descriptor_path=os.path.normpath(descriptor_path),
        json_path="",
        status=status,
        candidates=[os.path.normpath(str(candidate)) for candidate in candidates],
        first_index=slot.first_index,
        num_faces=slot.num_faces,
    )


def _find_existing_material_json(
    candidates: t.Iterable[str],
    uemodel_dir: str,
    export_root: str,
    prefer_export_root: bool,
) -> str:
    for root in _material_json_search_roots(uemodel_dir, export_root, prefer_export_root):
        for candidate in candidates:
            candidate_path = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
            candidate_path = os.path.normpath(candidate_path)
            if os.path.isfile(candidate_path):
                return candidate_path
    return ""


def _find_existing_material_json_in_dir(candidates: t.Iterable[str], directory: str) -> str:
    for candidate in candidates:
        candidate_path = candidate if os.path.isabs(candidate) else os.path.join(directory, candidate)
        candidate_path = os.path.normpath(candidate_path)
        if os.path.isfile(candidate_path):
            return candidate_path
    return ""


def _material_json_search_roots(uemodel_dir: str, export_root: str, prefer_export_root: bool) -> list[str]:
    roots: list[str] = []

    if export_root and prefer_export_root:
        roots.append(export_root)

    search_dir = uemodel_dir
    for _ in range(8):
        roots.append(search_dir)
        if export_root and _same_path(search_dir, export_root):
            break
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

    if export_root and not prefer_export_root:
        roots.append(export_root)

    unique_roots: list[str] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(os.path.abspath(root))
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)
    return unique_roots


def _descriptor_reference_from_json(json_path: str, material_name: str, uemodel_dir: str, export_root: str) -> str:
    json_abs = os.path.abspath(json_path)
    if export_root and _is_relative_to(json_abs, export_root):
        json_rel = os.path.relpath(json_abs, export_root)
    else:
        json_rel = os.path.relpath(json_abs, uemodel_dir)

    path_no_ext = os.path.splitext(os.path.normpath(json_rel))[0]
    return f"{path_no_ext}.{material_name}"


def _ambiguous_suffix_candidates(
    export_root: str,
    asset_reference: str,
    extensions: t.Sequence[str],
    settings: umodel_path_resolver.UModelPathInferenceSettings,
) -> list[str]:
    if (
        not settings.enable_umodel_path_inference
        or settings.path_inference_mode != umodel_path_resolver.AGGRESSIVE
        or not settings.enable_suffix_index
    ):
        return []

    index = umodel_path_resolver.build_export_asset_index(export_root, extensions)
    suffixes = umodel_path_resolver._suffixes_for_lookup(asset_reference, extensions)  # pylint: disable=protected-access
    for suffix in suffixes:
        matches = sorted(set(index.get(suffix, [])))
        if len(matches) > 1:
            return [os.path.normpath(match) for match in matches]
    return []


def _json_safe_candidates(paths: t.Iterable[str], export_root: str, uemodel_dir: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        candidate = _display_path(path, export_root, uemodel_dir)
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _display_path(path: str, export_root: str, uemodel_dir: str) -> str:
    path_abs = os.path.abspath(path)
    if export_root and _is_relative_to(path_abs, export_root):
        return os.path.normpath(os.path.relpath(path_abs, export_root))
    if _is_relative_to(path_abs, uemodel_dir):
        return os.path.normpath(os.path.relpath(path_abs, uemodel_dir))
    return os.path.normpath(path)


def _is_relative_to(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
