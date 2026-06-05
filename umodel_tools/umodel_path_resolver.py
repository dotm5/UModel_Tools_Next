import dataclasses
import os
import typing as t


BASIC_DEFAULT = "BASIC_DEFAULT"
STRICT_EXACT = "STRICT_EXACT"
AGGRESSIVE = "AGGRESSIVE"

_EXPORT_INDEX_CACHE: dict[tuple[str, tuple[str, ...]], dict[str, list[str]]] = {}
_RESOLVE_CACHE: dict[tuple[str, str, tuple[str, ...], bool, str, bool], "ResolvedUModelPath"] = {}


@dataclasses.dataclass(frozen=True)
class UModelPathInferenceSettings:
    enable_umodel_path_inference: bool = True
    path_inference_mode: str = BASIC_DEFAULT
    enable_suffix_index: bool = True


@dataclasses.dataclass
class UModelPathResolveStats:
    exact_resolved_count: int = 0
    inferred_resolved_count: int = 0
    suffix_resolved_count: int = 0
    unresolved_count: int = 0
    ambiguous_count: int = 0

    def reset(self) -> None:
        self.exact_resolved_count = 0
        self.inferred_resolved_count = 0
        self.suffix_resolved_count = 0
        self.unresolved_count = 0
        self.ambiguous_count = 0

    def as_dict(self) -> dict[str, int]:
        return dataclasses.asdict(self)

    def summary(self) -> str:
        return (
            "UModel path resolution stats: "
            f"exact={self.exact_resolved_count}, "
            f"inferred={self.inferred_resolved_count}, "
            f"suffix={self.suffix_resolved_count}, "
            f"unresolved={self.unresolved_count}, "
            f"ambiguous={self.ambiguous_count}"
        )


@dataclasses.dataclass(frozen=True)
class ResolvedUModelPath:
    path: str | None
    relative_path: str | None
    status: t.Literal["exact", "inferred", "suffix", "unresolved", "ambiguous"]
    warnings: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()
    normalized_asset_path: str = ""
    attempted_extensions: tuple[str, ...] = ()
    expected_path: str = ""
    resolved_candidate_count: int = 0

    @property
    def found(self) -> bool:
        return self.path is not None and self.status not in {"unresolved", "ambiguous"}


def normalize_unreal_asset_path(asset_path: str) -> str:
    """Normalize UE-style asset paths into a portable relative filesystem path."""
    path = asset_path.replace("\\", "/").strip()

    while path.startswith("/"):
        path = path[1:]

    lower_path = path.lower()
    for suffix in (".props.txt", ".uasset", ".umap", ".uemodel", ".json", ".pskx", ".psk", ".png", ".dds", ".tga"):
        if lower_path.endswith(suffix):
            path = path[:-len(suffix)]
            break

    return os.path.normpath(path)


def infer_umodel_mount_aliases(asset_path: str) -> list[str]:
    """Build common UModel export aliases for paths with cooked mount roots."""
    norm = normalize_unreal_asset_path(asset_path)
    parts = [part for part in norm.replace("\\", "/").split("/") if part]
    aliases: list[str] = []

    def add_alias(alias_parts: list[str]) -> None:
        if alias_parts and alias_parts != parts:
            alias = os.path.normpath("/".join(alias_parts))
            if alias not in aliases:
                aliases.append(alias)

    for idx, part in enumerate(parts[:-1]):
        if part.lower() != "content":
            continue

        # <Project>/Content/<MountRoot>/A/B/C/Asset -> Content/<MountRoot>/A/B/C/Asset
        if idx > 0:
            add_alias(parts[idx:])

        # <Project>/Content/<MountRoot>/A/B/C/Asset -> <MountRoot>/A/B/C/Asset
        add_alias(parts[idx + 1:])

        # Engine/Content/BasicShapes/Cube -> Engine/BasicShapes/Cube
        if idx > 0 and parts[idx - 1].lower() == "engine":
            add_alias([parts[idx - 1], *parts[idx + 1:]])

    if parts and parts[0].lower() == "game":
        # /Game/A/B/Asset is commonly exported under Content/A/B/Asset.
        add_alias(["Content", *parts[1:]])
        add_alias(parts[1:])

    return aliases


def build_umodel_asset_path_candidates(
    asset_path: str,
    extensions: t.Sequence[str],
    settings: UModelPathInferenceSettings | None = None,
) -> list[str]:
    """Return relative file candidates in lookup order."""
    settings = settings or UModelPathInferenceSettings()
    norm = normalize_unreal_asset_path(asset_path)
    bases = [norm]

    if settings.enable_umodel_path_inference and settings.path_inference_mode != STRICT_EXACT:
        bases.extend(infer_umodel_mount_aliases(norm))

    candidates: list[str] = []
    for base in bases:
        for ext in extensions:
            candidate = os.path.normpath(base + ext)
            if candidate not in candidates:
                candidates.append(candidate)

    return candidates


def build_export_asset_index(export_dir: str, extensions: t.Sequence[str]) -> dict[str, list[str]]:
    """Build a cached suffix lookup index for exported UModel files."""
    root = os.path.normpath(export_dir)
    normalized_exts = tuple(sorted(ext.lower() for ext in extensions))
    cache_key = (os.path.realpath(root), normalized_exts)

    if cache_key in _EXPORT_INDEX_CACHE:
        return _EXPORT_INDEX_CACHE[cache_key]

    index: dict[str, list[str]] = {}
    if not os.path.isdir(root):
        _EXPORT_INDEX_CACHE[cache_key] = index
        return index

    for walk_root, _, files in os.walk(root):
        for file in files:
            _, ext = os.path.splitext(file)
            if ext.lower() not in normalized_exts:
                continue

            abs_path = os.path.join(walk_root, file)
            rel_path = os.path.normpath(os.path.relpath(abs_path, root))
            parts = rel_path.replace("\\", "/").split("/")

            for start in range(len(parts)):
                suffix = os.path.normpath("/".join(parts[start:])).lower()
                index.setdefault(suffix, []).append(rel_path)

    _EXPORT_INDEX_CACHE[cache_key] = index
    return index


def _suffixes_for_lookup(asset_path: str, extensions: t.Sequence[str]) -> list[str]:
    norm = normalize_unreal_asset_path(asset_path)
    bases = [norm, *infer_umodel_mount_aliases(norm)]
    suffixes: list[str] = []

    for base in bases:
        parts = base.replace("\\", "/").split("/")
        for start in range(len(parts)):
            for ext in extensions:
                suffix = os.path.normpath("/".join(parts[start:]) + ext).lower()
                if suffix not in suffixes:
                    suffixes.append(suffix)

    suffixes.sort(key=lambda item: item.count(os.sep), reverse=True)
    return suffixes


def find_asset_by_suffix(
    export_dir: str,
    asset_path: str,
    extensions: t.Sequence[str],
) -> ResolvedUModelPath:
    """Find a file by longest non-ambiguous suffix match."""
    index = build_export_asset_index(export_dir, extensions)
    normalized_asset_path = normalize_unreal_asset_path(asset_path)

    for suffix in _suffixes_for_lookup(asset_path, extensions):
        matches = index.get(suffix, [])
        if not matches:
            continue

        matches = sorted(set(matches))
        if len(matches) > 1:
            warning = (
                f"Ambiguous UModel suffix match for {asset_path!r}: "
                f"{matches[:5]!r}"
            )
            return ResolvedUModelPath(
                path=None,
                relative_path=None,
                status="ambiguous",
                warnings=(warning,),
                candidates=tuple(matches),
                normalized_asset_path=normalized_asset_path,
                attempted_extensions=tuple(extensions),
                expected_path=_expected_path_with_extension(normalized_asset_path, extensions),
                resolved_candidate_count=len(matches),
            )

        rel_path = matches[0]
        return ResolvedUModelPath(
            path=os.path.join(export_dir, rel_path),
            relative_path=rel_path,
            status="suffix",
            normalized_asset_path=normalized_asset_path,
            attempted_extensions=tuple(extensions),
            expected_path=_expected_path_with_extension(normalized_asset_path, extensions),
            resolved_candidate_count=1,
        )

    return ResolvedUModelPath(
        path=None,
        relative_path=None,
        status="unresolved",
        normalized_asset_path=normalized_asset_path,
        attempted_extensions=tuple(extensions),
        expected_path=_expected_path_with_extension(normalized_asset_path, extensions),
        resolved_candidate_count=0,
    )


def resolve_umodel_export_asset_path(
    export_dir: str,
    asset_path: str,
    extensions: t.Sequence[str],
    settings: UModelPathInferenceSettings | None = None,
    stats: UModelPathResolveStats | None = None,
) -> ResolvedUModelPath:
    """Resolve an Unreal asset reference to a UModel-exported file."""
    settings = settings or UModelPathInferenceSettings()
    normalized_extensions = tuple(extensions)
    normalized_asset_path = normalize_unreal_asset_path(asset_path)
    cache_key = (
        os.path.realpath(os.path.normpath(export_dir)),
        normalized_asset_path,
        normalized_extensions,
        settings.enable_umodel_path_inference,
        settings.path_inference_mode,
        settings.enable_suffix_index,
    )

    if cache_key in _RESOLVE_CACHE:
        resolved = _RESOLVE_CACHE[cache_key]
        _count_result(resolved, stats)
        return resolved

    candidates = build_umodel_asset_path_candidates(asset_path, extensions, settings)
    expected_path = candidates[0] if candidates else normalized_asset_path
    exact_candidates = set(candidates[:len(extensions)])

    for candidate in candidates:
        abs_candidate = os.path.join(export_dir, candidate)
        if os.path.isfile(abs_candidate):
            status = "exact" if candidate in exact_candidates else "inferred"
            resolved = ResolvedUModelPath(
                path=abs_candidate,
                relative_path=candidate,
                status=status,
                normalized_asset_path=normalized_asset_path,
                attempted_extensions=normalized_extensions,
                expected_path=expected_path,
                resolved_candidate_count=1,
            )
            _RESOLVE_CACHE[cache_key] = resolved
            _count_result(resolved, stats)
            return resolved

    if (
        settings.enable_umodel_path_inference
        and settings.path_inference_mode == AGGRESSIVE
        and settings.enable_suffix_index
    ):
        resolved = find_asset_by_suffix(export_dir, asset_path, extensions)
        if resolved.found or resolved.status == "ambiguous":
            _RESOLVE_CACHE[cache_key] = resolved
            _count_result(resolved, stats)
            return resolved

    resolved = ResolvedUModelPath(
        path=None,
        relative_path=None,
        status="unresolved",
        normalized_asset_path=normalized_asset_path,
        attempted_extensions=normalized_extensions,
        expected_path=expected_path,
        resolved_candidate_count=0,
    )
    _RESOLVE_CACHE[cache_key] = resolved
    _count_result(resolved, stats)
    return resolved


def _count_result(resolved: ResolvedUModelPath, stats: UModelPathResolveStats | None) -> None:
    if stats is None:
        return

    if resolved.status == "exact":
        stats.exact_resolved_count += 1
    elif resolved.status == "inferred":
        stats.inferred_resolved_count += 1
    elif resolved.status == "suffix":
        stats.suffix_resolved_count += 1
    elif resolved.status == "ambiguous":
        stats.ambiguous_count += 1
    else:
        stats.unresolved_count += 1


def _expected_path_with_extension(normalized_asset_path: str, extensions: t.Sequence[str]) -> str:
    return os.path.normpath(normalized_asset_path + extensions[0]) if extensions else normalized_asset_path
