"""Small progress helpers without third-party runtime dependencies."""

from __future__ import annotations

import typing as t


class ProgressReporter:
    """Use Blender window-manager progress when available, otherwise no-op."""

    def __init__(self, context: t.Any = None, total: int = 0, desc: str = "") -> None:
        self.context = context
        self.total = max(int(total or 0), 0)
        self.desc = desc
        self.current = 0
        self._owner = getattr(context, "window_manager", None) if context is not None else None

    def __enter__(self) -> "ProgressReporter":
        if self.desc:
            print(self.desc)
        if self._owner is not None:
            self._owner.progress_begin(0, self.total)
        return self

    def __exit__(self, exc_type: t.Any, exc: t.Any, tb: t.Any) -> None:
        if self._owner is not None:
            self._owner.progress_end()

    def update(self, amount: int = 1) -> None:
        self.current += amount
        if self._owner is not None:
            self._owner.progress_update(min(self.current, self.total) if self.total else self.current)


def iter_progress(iterable: t.Iterable[t.Any],
                  context: t.Any = None,
                  total: int | None = None,
                  desc: str = "") -> t.Iterator[t.Any]:
    items_total = total if total is not None else _try_len(iterable)
    with ProgressReporter(context=context, total=items_total or 0, desc=desc) as reporter:
        for item in iterable:
            yield item
            reporter.update(1)


def _try_len(value: t.Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None
