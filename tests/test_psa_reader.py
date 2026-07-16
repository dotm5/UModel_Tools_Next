import importlib.util
import os
import struct
import sys

import pytest


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "psa_reader.py")


def _load_psa_reader():
    spec = importlib.util.spec_from_file_location("psa_reader_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


psa_reader = _load_psa_reader()


CHUNK_HEADER = struct.Struct("<20s3i")


def _chunk(name, data_size, records):
    payload = b"".join(records)
    return CHUNK_HEADER.pack(name.encode("ascii").ljust(20, b"\0"), 0, data_size, len(records)) + payload


def _name(value, size=64):
    return value.encode("windows-1252").ljust(size, b"\0")


def test_load_psa_reads_one_sequence_with_scale_keys(tmp_path):
    anim_info = struct.Struct("<64s64s4i3f3i")
    anim_key = struct.Struct("<3f4f4x")
    scale_key = struct.Struct("<3f4x")
    data = b"".join((
        _chunk("ANIMHEAD", 0, []),
        _chunk("BONENAMES", 120, [_name("Root", 120), _name("Fin", 120)]),
        _chunk(
            "ANIMINFO",
            anim_info.size,
            [anim_info.pack(_name("Swim"), _name("None"), 2, 0, 0, 0, 0.0, 2.0, 30.0, 0, 0, 2)],
        ),
        _chunk(
            "ANIMKEYS",
            anim_key.size,
            [
                anim_key.pack(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
                anim_key.pack(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0),
                anim_key.pack(4.0, 5.0, 6.0, 0.0, 0.0, 0.0, 1.0),
                anim_key.pack(7.0, 8.0, 9.0, 0.0, 0.0, 0.0, 1.0),
            ],
        ),
        _chunk(
            "SCALEKEYS",
            scale_key.size,
            [scale_key.pack(1.0, 1.0, 1.0) for _index in range(4)],
        ),
    ))
    filepath = tmp_path / "swim.psa"
    filepath.write_bytes(data)

    psa = psa_reader.load_psa(str(filepath))
    sequence = psa.find_sequence("swim")

    assert [bone.name for bone in psa.bones] == ["Root", "Fin"]
    assert sequence.name == "Swim"
    assert sequence.frame_count == 2
    assert sequence.fps == 30.0
    assert len(psa.sequence_keys(sequence)) == 4
    assert psa.sequence_keys(sequence)[1].location == pytest.approx((1.0, 2.0, 3.0))
    assert psa.sequence_keys(sequence)[1].rotation == pytest.approx((1.0, 0.0, 0.0, 0.0))
    assert psa.sequence_scale_keys(sequence)[-1].scale == pytest.approx((1.0, 1.0, 1.0))


def test_load_psa_rejects_missing_animation_chunks(tmp_path):
    filepath = tmp_path / "broken.psa"
    filepath.write_bytes(_chunk("ANIMHEAD", 0, []))

    with pytest.raises(ValueError, match="missing BONENAMES"):
        psa_reader.load_psa(str(filepath))
