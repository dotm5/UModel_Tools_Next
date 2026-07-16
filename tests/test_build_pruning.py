from pathlib import Path

from build import prune_third_party


def test_prune_third_party_removes_generated_and_non_runtime_payloads(tmp_path: Path):
    third_party = tmp_path / "third_party"
    keep_file = third_party / "networkx" / "module.py"
    cache_file = third_party / "networkx" / "__pycache__" / "module.cpython-313.pyc"
    loose_bytecode = third_party / "networkx" / "legacy.pyo"
    test_file = third_party / "networkx" / "tests" / "test_module.py"
    metadata_file = third_party / "networkx-3.4.2.dist-info" / "METADATA"
    cli_file = third_party / "bin" / "networkx"

    for path in (keep_file, cache_file, loose_bytecode, test_file, metadata_file, cli_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")

    prune_third_party(str(third_party))

    assert keep_file.is_file()
    assert not cache_file.parent.exists()
    assert not loose_bytecode.exists()
    assert not test_file.parent.exists()
    assert not metadata_file.parent.exists()
    assert not cli_file.parent.exists()
