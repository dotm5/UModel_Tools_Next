#!/usr/bin/env python
"""Report repository layout boundary issues without modifying files."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


FORBIDDEN_TRACKED_EXTENSIONS = frozenset({
    ".exe",
    ".dll",
    ".zip",
    ".blend",
    ".sqlite",
})

FORBIDDEN_TRACKED_PREFIXES = (
    "dist/",
    "tests/runtime/",
    "tools/fmodel/",
    "tools/umodel_win32/",
)

FORBIDDEN_ROOT_NAMES = frozenset({
    "toTest",
    "fmodel",
    "umodel_win32",
})

FORBIDDEN_ROOT_PREFIXES = (
    "test_runtime_",
    "asset_cache",
)


@dataclass(frozen=True)
class LayoutIssue:
    code: str
    path: str
    message: str
    suggestion: str | None = None


def normalize_git_path(path: str) -> str:
    """Return a stable Git-style path for matching and display."""
    return path.replace("\\", "/").strip("/")


def is_forbidden_tracked_path(path: str) -> bool:
    normalized = normalize_git_path(path)
    lower = normalized.lower()
    suffix = Path(lower).suffix
    if suffix in FORBIDDEN_TRACKED_EXTENSIONS:
        return True
    return lower.startswith(FORBIDDEN_TRACKED_PREFIXES)


def audit_tracked_paths(paths: Iterable[str]) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    for raw_path in paths:
        path = normalize_git_path(raw_path)
        if not path or not is_forbidden_tracked_path(path):
            continue
        issues.append(
            LayoutIssue(
                code="tracked-forbidden-artifact",
                path=path,
                message=f"Forbidden artifact is tracked by Git: {path}",
                suggestion=f"git rm --cached {quote_git_path(path)}",
            )
        )
    return issues


def is_forbidden_root_entry(name: str) -> bool:
    if name in FORBIDDEN_ROOT_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in FORBIDDEN_ROOT_PREFIXES)


def audit_root_entries(names: Iterable[str]) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    for name in names:
        if not name or not is_forbidden_root_entry(name):
            continue
        issues.append(
            LayoutIssue(
                code="root-local-artifact",
                path=name,
                message=f"Local artifact should not live at repository root: {name}",
            )
        )
    return issues


def audit_layout(tracked_paths: Iterable[str], root_entries: Iterable[str]) -> list[LayoutIssue]:
    return audit_tracked_paths(tracked_paths) + audit_root_entries(root_entries)


def quote_git_path(path: str) -> str:
    if any(ch.isspace() for ch in path):
        return f'"{path}"'
    return path


def get_git_tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo_root),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line]


def get_root_entries(repo_root: Path) -> list[str]:
    return [entry.name for entry in repo_root.iterdir()]


def print_issues(issues: Sequence[LayoutIssue]) -> None:
    if not issues:
        print("Repository layout audit passed.")
        return

    print("Repository layout audit found issues:", file=sys.stderr)
    for issue in issues:
        print(f"- [{issue.code}] {issue.message}", file=sys.stderr)
        if issue.suggestion:
            print(f"  suggested command: {issue.suggestion}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=os.getcwd(),
        help="Repository root to audit. Defaults to the current working directory.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    tracked_paths = get_git_tracked_paths(repo_root)
    root_entries = get_root_entries(repo_root)
    issues = audit_layout(tracked_paths, root_entries)
    print_issues(issues)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
