"""Map import progress message helpers."""

from __future__ import annotations

import time


def should_print_static_mesh_progress(static_mesh_seen: int,
                                      last_progress_print: float,
                                      interval_seconds: float = 30.0) -> bool:
    return static_mesh_seen % 100 == 0 or time.monotonic() - last_progress_print >= interval_seconds


def format_static_mesh_progress(entity_index: int,
                                total_entities: int,
                                static_mesh_seen: int,
                                imported_instances: int,
                                missing_mesh: int) -> str:
    return (
        "Map import progress: "
        f"entity={entity_index}/{total_entities}, "
        f"static_mesh={static_mesh_seen}, "
        f"imported_instances={imported_instances}, "
        f"missing_mesh={missing_mesh}"
    )
