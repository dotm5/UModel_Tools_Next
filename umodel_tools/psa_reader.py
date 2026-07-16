"""Small dependency-free reader for the PSA animation data used by map previews."""

from __future__ import annotations

import dataclasses
import struct


_CHUNK_HEADER = struct.Struct("<20s3i")
_ANIM_INFO = struct.Struct("<64s64s4i3f3i")
_ANIM_KEY = struct.Struct("<3f4f4x")
_SCALE_KEY = struct.Struct("<3f4x")


def _decode_name(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("windows-1252", errors="replace").rstrip()


@dataclasses.dataclass(frozen=True)
class PsaBone:
    name: str


@dataclasses.dataclass(frozen=True)
class PsaSequence:
    name: str
    group: str
    bone_count: int
    fps: float
    first_raw_frame: int
    frame_count: int


@dataclasses.dataclass(frozen=True)
class PsaKey:
    location: tuple[float, float, float]
    rotation: tuple[float, float, float, float]


@dataclasses.dataclass(frozen=True)
class PsaScaleKey:
    scale: tuple[float, float, float]


@dataclasses.dataclass(frozen=True)
class PsaFile:
    bones: tuple[PsaBone, ...]
    sequences: tuple[PsaSequence, ...]
    keys: tuple[PsaKey, ...]
    scale_keys: tuple[PsaScaleKey, ...]

    def find_sequence(self, preferred_name: str = "") -> PsaSequence:
        if not self.sequences:
            raise ValueError("PSA file contains no animation sequences.")

        normalized = preferred_name.strip().casefold()
        if normalized:
            for sequence in self.sequences:
                if sequence.name.casefold() == normalized:
                    return sequence
        return self.sequences[0]

    def sequence_keys(self, sequence: PsaSequence) -> tuple[PsaKey, ...]:
        start = sequence.first_raw_frame * sequence.bone_count
        end = start + sequence.frame_count * sequence.bone_count
        if start < 0 or end > len(self.keys):
            raise ValueError(
                f'PSA sequence "{sequence.name}" references keys outside the ANIMKEYS chunk '
                f"({start}:{end} of {len(self.keys)})."
            )
        return self.keys[start:end]

    def sequence_scale_keys(self, sequence: PsaSequence) -> tuple[PsaScaleKey, ...]:
        if not self.scale_keys:
            return ()
        start = sequence.first_raw_frame * sequence.bone_count
        end = start + sequence.frame_count * sequence.bone_count
        if start < 0 or end > len(self.scale_keys):
            raise ValueError(
                f'PSA sequence "{sequence.name}" references scale keys outside the SCALEKEYS chunk '
                f"({start}:{end} of {len(self.scale_keys)})."
            )
        return self.scale_keys[start:end]


def load_psa(filepath: str) -> PsaFile:
    """Read bones, sequences, transform keys, and optional scale keys from one PSA file."""

    chunks = _read_chunks(filepath)
    if "BONENAMES" not in chunks or "ANIMINFO" not in chunks or "ANIMKEYS" not in chunks:
        raise ValueError("PSA file is missing BONENAMES, ANIMINFO, or ANIMKEYS data.")

    bone_size, bone_count, bone_data = chunks["BONENAMES"]
    if bone_size < 64:
        raise ValueError(f"Unsupported PSA bone record size: {bone_size}.")
    if bone_count <= 0:
        raise ValueError("PSA file contains no bones.")
    bones = tuple(
        PsaBone(_decode_name(bone_data[index * bone_size:index * bone_size + 64]))
        for index in range(bone_count)
    )

    sequence_size, sequence_count, sequence_data = chunks["ANIMINFO"]
    if sequence_size < _ANIM_INFO.size:
        raise ValueError(f"Unsupported PSA sequence record size: {sequence_size}.")
    sequences = []
    for index in range(sequence_count):
        offset = index * sequence_size
        values = _ANIM_INFO.unpack_from(sequence_data, offset)
        sequence_bone_count = int(values[2])
        if sequence_bone_count != len(bones):
            raise ValueError(
                f'PSA sequence "{_decode_name(values[0])}" has unsupported bone count '
                f"{sequence_bone_count}; file contains {len(bones)} bones."
            )
        if int(values[11]) <= 0:
            raise ValueError(f'PSA sequence "{_decode_name(values[0])}" contains no frames.')
        sequences.append(
            PsaSequence(
                name=_decode_name(values[0]),
                group=_decode_name(values[1]),
                bone_count=sequence_bone_count,
                fps=float(values[8]) if float(values[8]) > 0.0 else 30.0,
                first_raw_frame=int(values[10]),
                frame_count=int(values[11]),
            )
        )

    key_size, key_count, key_data = chunks["ANIMKEYS"]
    if key_size < _ANIM_KEY.size:
        raise ValueError(f"Unsupported PSA animation key size: {key_size}.")
    keys = []
    for index in range(key_count):
        values = _ANIM_KEY.unpack_from(key_data, index * key_size)
        keys.append(
            PsaKey(
                location=(values[0], values[1], values[2]),
                rotation=(values[6], values[3], values[4], values[5]),
            )
        )

    scale_keys = []
    if "SCALEKEYS" in chunks:
        scale_size, scale_count, scale_data = chunks["SCALEKEYS"]
        if scale_size < _SCALE_KEY.size:
            raise ValueError(f"Unsupported PSA scale key size: {scale_size}.")
        for index in range(scale_count):
            values = _SCALE_KEY.unpack_from(scale_data, index * scale_size)
            scale_keys.append(PsaScaleKey(scale=(values[0], values[1], values[2])))

    return PsaFile(
        bones=bones,
        sequences=tuple(sequences),
        keys=tuple(keys),
        scale_keys=tuple(scale_keys),
    )


def _read_chunks(filepath: str) -> dict[str, tuple[int, int, bytes]]:
    chunks: dict[str, tuple[int, int, bytes]] = {}
    with open(filepath, "rb") as stream:
        while True:
            header = stream.read(_CHUNK_HEADER.size)
            if not header:
                break
            if len(header) != _CHUNK_HEADER.size:
                raise ValueError("PSA file ends inside a chunk header.")

            chunk_id_raw, _type_flag, data_size, data_count = _CHUNK_HEADER.unpack(header)
            chunk_id = _decode_name(chunk_id_raw)
            if data_size < 0 or data_count < 0:
                raise ValueError(f'PSA chunk "{chunk_id}" has a negative size or count.')
            payload_size = data_size * data_count
            payload = stream.read(payload_size)
            if len(payload) != payload_size:
                raise ValueError(f'PSA chunk "{chunk_id}" is truncated.')
            chunks[chunk_id] = (data_size, data_count, payload)

    if "ANIMHEAD" not in chunks:
        raise ValueError("Not a PSA file: ANIMHEAD chunk was not found.")
    return chunks


__all__ = (
    "PsaBone",
    "PsaFile",
    "PsaKey",
    "PsaScaleKey",
    "PsaSequence",
    "load_psa",
)
