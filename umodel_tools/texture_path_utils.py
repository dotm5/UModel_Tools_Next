"""Pure string helpers for texture rule matching."""

from __future__ import annotations

import fnmatch
import os
import re
import typing as t


def normalize_token(value: t.Any) -> str:
    return str(value).strip().lower()


def normalize_texture_name(tex_short_name: str) -> str:
    return normalize_token(os.path.basename(tex_short_name).lstrip("."))


def is_diffuse_texture_path(tex_path: str) -> bool:
    stem = os.path.splitext(os.path.basename(tex_path))[0].lower()
    return stem.endswith(("_d", "_d2", "_bc", "_basecolor", "_basecolour", "_diffuse", "_albedo"))


def texture_suffix(normalized_tex_name: str) -> str:
    return normalized_tex_name.rsplit("_", maxsplit=1)[-1]


def matches_texture_suffix(tex_short_name: str, suffixes: frozenset[str]) -> bool:
    normalized_name = normalize_texture_name(tex_short_name)
    if texture_suffix(normalized_name) in suffixes:
        return True

    return any(
        normalized_name == suffix or normalized_name.endswith(f"_{suffix}")
        for suffix in suffixes
        if "_" in suffix
    )


def matches_aware_name(normalized_tex_name: str,
                       basename_globs: tuple[str, ...],
                       basename_regexes: tuple[str, ...]) -> bool:
    if any(fnmatch.fnmatchcase(normalized_tex_name, pattern) for pattern in basename_globs):
        return True

    return any(
        re.search(pattern, normalized_tex_name, flags=re.IGNORECASE) is not None
        for pattern in basename_regexes
    )
