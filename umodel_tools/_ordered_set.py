"""Small ordered set implementation for registration ordering."""

from __future__ import annotations

import collections.abc as cabc
import typing as t


class OrderedSet(cabc.MutableSet):
    def __init__(self, values: t.Iterable[t.Any] = ()) -> None:
        self._items: dict[t.Any, None] = {}
        for value in values:
            self.add(value)

    def __contains__(self, value: object) -> bool:
        return value in self._items

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self._items)!r})"

    def __sub__(self, other: t.Iterable[t.Any]):
        other_values = set(other)
        return type(self)(value for value in self if value not in other_values)

    def add(self, value: t.Any) -> None:
        self._items[value] = None

    def discard(self, value: t.Any) -> None:
        self._items.pop(value, None)
