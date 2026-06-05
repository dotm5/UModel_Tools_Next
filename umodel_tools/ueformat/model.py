"""UEFormat .uemodel parser.

The parser mirrors the public UEFormat Blender add-on's model sections while
keeping the data plain-Python for fast unit testing outside Blender.
"""

from __future__ import annotations

import dataclasses
import enum
import gzip
import typing as t

from .reader import ArchiveReader


MAGIC = "UEFORMAT"
MODEL_IDENTIFIER = "UEMODEL"


class UEFormatError(RuntimeError):
    """Raised when a UEFormat file cannot be parsed or is unsupported."""


class UEFormatVersion(enum.IntEnum):
    BeforeCustomVersionWasAdded = 0
    SerializeBinormalSign = 1
    AddMultipleVertexColors = 2
    AddConvexCollisionGeom = 3
    LevelOfDetailFormatRestructure = 4
    SerializeVirtualBones = 5
    SerializeMaterialPath = 6
    SerializeAssetMetadata = 7
    PreserveOriginalTransforms = 8
    AddPoseExport = 9


@dataclasses.dataclass(slots=True)
class VertexColor:
    name: str
    colors: list[tuple[float, float, float, float]]


@dataclasses.dataclass(slots=True)
class Material:
    material_name: str
    material_path: str
    first_index: int
    num_faces: int


@dataclasses.dataclass(slots=True)
class Weight:
    bone_index: int
    vertex_index: int
    weight: float


@dataclasses.dataclass(slots=True)
class MorphDelta:
    position: tuple[float, float, float]
    normal: tuple[float, float, float]
    vertex_index: int


@dataclasses.dataclass(slots=True)
class MorphTarget:
    name: str
    deltas: list[MorphDelta]


@dataclasses.dataclass(slots=True)
class Bone:
    name: str
    parent_index: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]


@dataclasses.dataclass(slots=True)
class Socket:
    name: str
    parent_name: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]


@dataclasses.dataclass(slots=True)
class VirtualBone:
    source_name: str
    target_name: str
    virtual_name: str


@dataclasses.dataclass(slots=True)
class Skeleton:
    skeleton_path: str = ""
    bones: list[Bone] = dataclasses.field(default_factory=list)
    sockets: list[Socket] = dataclasses.field(default_factory=list)
    virtual_bones: list[VirtualBone] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class LOD:
    name: str
    vertices: list[tuple[float, float, float]] = dataclasses.field(default_factory=list)
    indices: list[tuple[int, int, int]] = dataclasses.field(default_factory=list)
    normals: list[tuple[float, float, float]] = dataclasses.field(default_factory=list)
    colors: list[VertexColor] = dataclasses.field(default_factory=list)
    uvs: list[list[tuple[float, float]]] = dataclasses.field(default_factory=list)
    materials: list[Material] = dataclasses.field(default_factory=list)
    weights: list[Weight] = dataclasses.field(default_factory=list)
    morphs: list[MorphTarget] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class UEModel:
    name: str
    version: int
    lods: list[LOD] = dataclasses.field(default_factory=list)
    skeleton: Skeleton | None = None


def load_uemodel(filepath: str, scale: float = 0.01) -> UEModel:
    with open(filepath, "rb") as handle:
        return parse_uemodel(handle.read(), scale=scale)


def parse_uemodel(data: bytes, scale: float = 0.01) -> UEModel:
    ar = ArchiveReader(data)
    if ar.read_string(len(MAGIC)) != MAGIC:
        raise UEFormatError("Invalid UEFormat magic.")

    identifier = ar.read_fstring()
    if identifier != MODEL_IDENTIFIER:
        raise UEFormatError(f"Unsupported UEFormat identifier {identifier!r}.")

    file_version = ar.read_byte()
    if file_version > int(UEFormatVersion.AddPoseExport):
        raise UEFormatError(f"Unsupported UEFormat version {file_version}.")

    object_name = ar.read_fstring()
    read_archive = ar
    if ar.read_bool():
        compression_type = ar.read_fstring()
        uncompressed_size = ar.read_int()
        _compressed_size = ar.read_int()
        compressed = ar.read_to_end()
        if compression_type != "GZIP":
            raise UEFormatError(f"Unsupported UEFormat compression {compression_type!r}.")
        decompressed = gzip.decompress(compressed)
        if len(decompressed) != uncompressed_size:
            raise UEFormatError("UEFormat decompressed size mismatch.")
        read_archive = ArchiveReader(decompressed)

    read_archive.file_version = file_version
    read_archive.metadata["scale"] = scale

    if file_version >= int(UEFormatVersion.LevelOfDetailFormatRestructure):
        return _read_model(read_archive, object_name, file_version)

    return _read_classic_model(read_archive, object_name, file_version)


def _read_model(ar: ArchiveReader, name: str, version: int) -> UEModel:
    model = UEModel(name=name, version=version)
    while not ar.eof():
        section_name = ar.read_fstring()
        count = ar.read_int()
        byte_size = ar.read_int()
        pos = ar.tell()
        if section_name == "LODS":
            model.lods = ar.read_array(count, _read_lod)
        elif section_name == "SKELETON":
            model.skeleton = _read_skeleton(ar.chunk(byte_size))
        else:
            ar.skip(byte_size)
        ar.seek(pos + byte_size)
    return model


def _read_classic_model(ar: ArchiveReader, name: str, version: int) -> UEModel:
    model = UEModel(name=name, version=version, skeleton=Skeleton())
    lod = LOD(name="LOD0")
    while not ar.eof():
        header_name = ar.read_fstring()
        count = ar.read_int()
        byte_size = ar.read_int()
        pos = ar.tell()
        _read_lod_section(ar, lod, header_name, count, byte_size)
        if header_name == "BONES":
            model.skeleton.bones = ar.read_array(count, _read_bone)
        elif header_name == "SOCKETS":
            model.skeleton.sockets = ar.read_array(count, _read_socket)
        ar.seek(pos + byte_size)
    model.lods.append(lod)
    return model


def _read_lod(ar: ArchiveReader) -> LOD:
    lod = LOD(name=ar.read_fstring())
    lod_ar = ar.chunk(ar.read_int())
    while not lod_ar.eof():
        section_name = lod_ar.read_fstring()
        count = lod_ar.read_int()
        byte_size = lod_ar.read_int()
        pos = lod_ar.tell()
        _read_lod_section(lod_ar, lod, section_name, count, byte_size)
        lod_ar.seek(pos + byte_size)
    return lod


def _read_lod_section(ar: ArchiveReader, lod: LOD, section_name: str, count: int, byte_size: int) -> None:
    version = ar.file_version
    scale = float(ar.metadata.get("scale", 1.0))
    preserve = version >= int(UEFormatVersion.PreserveOriginalTransforms)

    if section_name == "VERTICES":
        values = ar.read_float_vector(count * 3)
        lod.vertices = [
            _mirror_xyz((values[i] * scale, values[i + 1] * scale, values[i + 2] * scale), preserve)
            for i in range(0, len(values), 3)
        ]
    elif section_name == "INDICES":
        values = ar.read_int_vector(count)
        lod.indices = [(values[i], values[i + 1], values[i + 2]) for i in range(0, len(values), 3)]
    elif section_name == "NORMALS":
        if version >= int(UEFormatVersion.SerializeBinormalSign):
            values = ar.read_float_vector(count * 4)
            lod.normals = [
                _mirror_xyz((values[i + 1], values[i + 2], values[i + 3]), preserve)
                for i in range(0, len(values), 4)
            ]
        else:
            values = ar.read_float_vector(count * 3)
            lod.normals = [
                _mirror_xyz((values[i], values[i + 1], values[i + 2]), preserve)
                for i in range(0, len(values), 3)
            ]
    elif section_name == "TANGENTS":
        ar.skip(byte_size)
    elif section_name == "VERTEXCOLORS":
        if version >= int(UEFormatVersion.AddMultipleVertexColors):
            lod.colors = ar.read_array(count, _read_vertex_color)
        else:
            values = ar.read_byte_vector(count * 4)
            lod.colors = [VertexColor("COL0", _rgba_byte_rows(values))]
    elif section_name == "TEXCOORDS":
        lod.uvs = []
        for _ in range(count):
            uv_count = ar.read_int()
            values = ar.read_float_vector(uv_count * 2)
            layer = []
            for i in range(0, len(values), 2):
                uv = (values[i], values[i + 1])
                if preserve:
                    uv = (uv[0], 1.0 - uv[1])
                layer.append(uv)
            lod.uvs.append(layer)
    elif section_name == "MATERIALS":
        lod.materials = ar.read_array(count, _read_material)
    elif section_name == "WEIGHTS":
        lod.weights = ar.read_array(count, _read_weight)
    elif section_name == "MORPHTARGETS":
        lod.morphs = ar.read_array(count, _read_morph_target)
    else:
        ar.skip(byte_size)


def _read_skeleton(ar: ArchiveReader) -> Skeleton:
    skeleton = Skeleton()
    while not ar.eof():
        section_name = ar.read_fstring()
        count = ar.read_int()
        byte_size = ar.read_int()
        pos = ar.tell()
        if section_name == "METADATA":
            skeleton.skeleton_path = ar.read_fstring()
        elif section_name == "BONES":
            skeleton.bones = ar.read_array(count, _read_bone)
        elif section_name == "SOCKETS":
            skeleton.sockets = ar.read_array(count, _read_socket)
        elif section_name == "VIRTUALBONES":
            skeleton.virtual_bones = ar.read_array(count, _read_virtual_bone)
        else:
            ar.skip(byte_size)
        ar.seek(pos + byte_size)
    return skeleton


def _read_vertex_color(ar: ArchiveReader) -> VertexColor:
    name = ar.read_fstring()
    count = ar.read_int()
    return VertexColor(name=name, colors=_rgba_byte_rows(ar.read_byte_vector(count * 4)))


def _read_material(ar: ArchiveReader) -> Material:
    return Material(
        material_name=ar.read_fstring(),
        material_path=ar.read_fstring() if ar.file_version >= int(UEFormatVersion.SerializeMaterialPath) else "",
        first_index=ar.read_int(),
        num_faces=ar.read_int(),
    )


def _read_weight(ar: ArchiveReader) -> Weight:
    return Weight(bone_index=ar.read_short(), vertex_index=ar.read_int(), weight=ar.read_float())


def _read_morph_target(ar: ArchiveReader) -> MorphTarget:
    return MorphTarget(name=ar.read_fstring(), deltas=ar.read_serialized_array(_read_morph_delta))


def _read_morph_delta(ar: ArchiveReader) -> MorphDelta:
    preserve = ar.file_version >= int(UEFormatVersion.PreserveOriginalTransforms)
    scale = float(ar.metadata.get("scale", 1.0))
    pos = ar.read_float_vector(3)
    normal = ar.read_float_vector(3)
    return MorphDelta(
        position=_mirror_xyz((pos[0] * scale, pos[1] * scale, pos[2] * scale), preserve),
        normal=_mirror_xyz(t.cast(tuple[float, float, float], normal), preserve),
        vertex_index=ar.read_int(),
    )


def _read_bone(ar: ArchiveReader) -> Bone:
    preserve = ar.file_version >= int(UEFormatVersion.PreserveOriginalTransforms)
    scale = float(ar.metadata.get("scale", 1.0))
    name = ar.read_fstring()
    parent_index = ar.read_int()
    position = ar.read_float_vector(3)
    rotation = ar.read_float_vector(4)
    return Bone(
        name=name,
        parent_index=parent_index,
        position=_mirror_xyz((position[0] * scale, position[1] * scale, position[2] * scale), preserve),
        rotation=_mirror_quat(t.cast(tuple[float, float, float, float], rotation), preserve),
    )


def _read_socket(ar: ArchiveReader) -> Socket:
    preserve = ar.file_version >= int(UEFormatVersion.PreserveOriginalTransforms)
    scale_factor = float(ar.metadata.get("scale", 1.0))
    name = ar.read_fstring()
    parent_name = ar.read_fstring()
    position = ar.read_float_vector(3)
    rotation = ar.read_float_vector(4)
    scale = ar.read_float_vector(3)
    return Socket(
        name=name,
        parent_name=parent_name,
        position=_mirror_xyz((position[0] * scale_factor, position[1] * scale_factor, position[2] * scale_factor),
                             preserve),
        rotation=_mirror_quat(t.cast(tuple[float, float, float, float], rotation), preserve),
        scale=_mirror_xyz(t.cast(tuple[float, float, float], scale), preserve),
    )


def _read_virtual_bone(ar: ArchiveReader) -> VirtualBone:
    return VirtualBone(source_name=ar.read_fstring(), target_name=ar.read_fstring(), virtual_name=ar.read_fstring())


def _mirror_xyz(value: tuple[float, float, float], enabled: bool) -> tuple[float, float, float]:
    if not enabled:
        return value
    return value[0], -value[1], value[2]


def _mirror_quat(value: tuple[float, float, float, float], enabled: bool) -> tuple[float, float, float, float]:
    if not enabled:
        return value
    return value[0], -value[1], value[2], -value[3]


def _rgba_byte_rows(values: tuple[int, ...]) -> list[tuple[float, float, float, float]]:
    return [
        (values[i] / 255.0, values[i + 1] / 255.0, values[i + 2] / 255.0, values[i + 3] / 255.0)
        for i in range(0, len(values), 4)
    ]
