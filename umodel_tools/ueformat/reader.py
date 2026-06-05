"""Minimal UEFormat archive reader.

Derived from the public UEFormat Blender importer data layout.  This module has
no Blender dependency so tests can parse .uemodel fixtures without bpy.
"""

from __future__ import annotations

import io
import struct
import typing as t


class ArchiveReader:
    def __init__(self, data: bytes) -> None:
        self.data = io.BytesIO(data)
        self.size = len(data)
        self.file_version = 0
        self.metadata: dict[str, t.Any] = {}

    def eof(self) -> bool:
        return self.data.tell() >= self.size

    def tell(self) -> int:
        return self.data.tell()

    def read(self, size: int) -> bytes:
        value = self.data.read(size)
        if len(value) != size:
            raise EOFError(f"Expected {size} bytes, got {len(value)}.")
        return value

    def read_to_end(self) -> bytes:
        return self.data.read(self.size - self.data.tell())

    def skip(self, size: int) -> None:
        self.data.seek(size, io.SEEK_CUR)

    def seek(self, pos: int) -> None:
        self.data.seek(pos, io.SEEK_SET)

    def chunk(self, size: int) -> "ArchiveReader":
        child = ArchiveReader(self.read(size))
        child.file_version = self.file_version
        child.metadata = dict(self.metadata)
        return child

    def read_bool(self) -> bool:
        return struct.unpack("?", self.read(1))[0]

    def read_byte(self) -> int:
        return self.read(1)[0]

    def read_short(self) -> int:
        return struct.unpack("<h", self.read(2))[0]

    def read_int(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def read_float(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def read_string(self, size: int) -> str:
        return self.read(size).rstrip(b"\x00").decode("utf-8", "replace")

    def read_fstring(self) -> str:
        size = self.read_int()
        if size < 0:
            raw = self.read(abs(size) * 2)
            return raw.decode("utf-16-le", "replace").rstrip("\x00")
        return self.read(size).rstrip(b"\x00").decode("utf-8", "replace")

    def read_int_vector(self, size: int) -> tuple[int, ...]:
        if size <= 0:
            return ()
        return struct.unpack(f"<{size}I", self.read(size * 4))

    def read_byte_vector(self, size: int) -> tuple[int, ...]:
        if size <= 0:
            return ()
        return struct.unpack(f"<{size}B", self.read(size))

    def read_float_vector(self, size: int) -> tuple[float, ...]:
        if size <= 0:
            return ()
        return struct.unpack(f"<{size}f", self.read(size * 4))

    def read_array(self, count: int, predicate: t.Callable[["ArchiveReader"], t.Any]) -> list[t.Any]:
        return [predicate(self) for _ in range(count)]

    def read_serialized_array(self, predicate: t.Callable[["ArchiveReader"], t.Any]) -> list[t.Any]:
        return self.read_array(self.read_int(), predicate)
