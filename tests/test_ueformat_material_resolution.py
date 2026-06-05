import os
import sys
import types
from contextlib import contextmanager


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _is_umodel_tools_module(module_name):
    return module_name == "umodel_tools" or module_name.startswith("umodel_tools.")


@contextmanager
def _scoped_umodel_tools_package():
    saved_modules = {
        module_name: module
        for module_name, module in sys.modules.items()
        if _is_umodel_tools_module(module_name)
    }
    for module_name in list(saved_modules):
        sys.modules.pop(module_name, None)

    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools")]
    sys.modules["umodel_tools"] = fake_package
    try:
        yield
    finally:
        for module_name in list(sys.modules):
            if _is_umodel_tools_module(module_name):
                sys.modules.pop(module_name, None)
        sys.modules.update(saved_modules)


def test_material_resolution_preserves_backend_descriptor_order_and_paths(tmp_path):
    with _scoped_umodel_tools_package():
        from umodel_tools.mesh_backends import backends
        from umodel_tools.ueformat.material_resolution import MaterialSlotReference, resolve_material_descriptors

        export_root = tmp_path
        uemodel_dir = export_root / "PM" / "Content" / "PaperMan" / "Characters" / "Kanami" / "Mesh3D"
        materials_dir = uemodel_dir / "Materials"
        materials_dir.mkdir(parents=True)
        uemodel_path = uemodel_dir / "Model.uemodel"

        (materials_dir / "MI_ByName.json").write_text("{}", encoding="utf-8")
        (uemodel_dir / "MI_ByPath.json").write_text("{}", encoding="utf-8")

        slots = [
            MaterialSlotReference(
                slot_index=0,
                material_name="MI_ByName",
                material_path="",
                first_index=0,
                num_faces=1,
            ),
            MaterialSlotReference(
                slot_index=1,
                material_name="MI_ByPath",
                material_path="PM/Content/PaperMan/Characters/Kanami/Mesh3D/MI_ByPath.MI_ByPath",
                first_index=3,
                num_faces=2,
            ),
        ]

        descriptors = resolve_material_descriptors(slots, str(uemodel_path), str(export_root))
        backend_descriptors = backends._build_material_descriptors(slots, str(uemodel_path), str(export_root))

    expected_by_name = os.path.normpath(
        "PM/Content/PaperMan/Characters/Kanami/Mesh3D/Materials/MI_ByName.MI_ByName"
    )
    expected_by_path = os.path.normpath(
        "PM/Content/PaperMan/Characters/Kanami/Mesh3D/MI_ByPath.MI_ByPath"
    )

    assert [descriptor.descriptor_path for descriptor in descriptors] == [expected_by_name, expected_by_path]
    assert [descriptor.status for descriptor in descriptors] == ["resolved", "resolved"]
    assert [descriptor["descriptor_path"] for descriptor in backend_descriptors] == [expected_by_name, expected_by_path]
    assert backend_descriptors[0]["json_path"].endswith(os.path.join("Materials", "MI_ByName.json"))
    assert backend_descriptors[1]["slot_index"] == 1


def test_material_resolution_prefers_same_dir_json_before_materials_dir(tmp_path):
    with _scoped_umodel_tools_package():
        from umodel_tools.ueformat.material_resolution import resolve_material_descriptors

        export_root = tmp_path
        uemodel_dir = export_root / "PM" / "Content" / "Game" / "Mesh3D"
        materials_dir = uemodel_dir / "Materials"
        materials_dir.mkdir(parents=True)
        uemodel_path = uemodel_dir / "Model.uemodel"

        (uemodel_dir / "MI_Priority.json").write_text("{}", encoding="utf-8")
        (materials_dir / "MI_Priority.json").write_text("{}", encoding="utf-8")

        descriptors = resolve_material_descriptors(
            [
                types.SimpleNamespace(
                    material_name="MI_Priority",
                    material_path="",
                    first_index=0,
                    num_faces=1,
                )
            ],
            str(uemodel_path),
            str(export_root),
        )

    assert descriptors[0].descriptor_path == os.path.normpath("PM/Content/Game/Mesh3D/MI_Priority.MI_Priority")
    assert descriptors[0].json_path.endswith(os.path.join("Mesh3D", "MI_Priority.json"))


def test_material_resolution_name_lookup_does_not_search_parent_directories(tmp_path):
    with _scoped_umodel_tools_package():
        from umodel_tools.ueformat.material_resolution import MaterialSlotReference, resolve_material_descriptors

        export_root = tmp_path
        parent_dir = export_root / "Root"
        uemodel_dir = parent_dir / "Child"
        uemodel_dir.mkdir(parents=True)
        uemodel_path = uemodel_dir / "Model.uemodel"
        (parent_dir / "MI_Parent.json").write_text("{}", encoding="utf-8")

        descriptors = resolve_material_descriptors(
            [
                MaterialSlotReference(
                    slot_index=0,
                    material_name="MI_Parent",
                    material_path="",
                    first_index=0,
                    num_faces=1,
                )
            ],
            str(uemodel_path),
            str(export_root),
        )

    assert descriptors[0].status == "unresolved"
    assert descriptors[0].json_path == ""
    assert descriptors[0].descriptor_path == "MI_Parent.MI_Parent"


def test_material_resolution_reports_ambiguous_aggressive_suffix_candidates(tmp_path):
    with _scoped_umodel_tools_package():
        from umodel_tools.umodel_path_resolver import AGGRESSIVE, UModelPathInferenceSettings
        from umodel_tools.ueformat.material_resolution import MaterialSlotReference, resolve_material_descriptors

        export_root = tmp_path
        uemodel_dir = export_root / "PM" / "Content" / "Game" / "Mesh3D"
        uemodel_dir.mkdir(parents=True)
        uemodel_path = uemodel_dir / "Model.uemodel"

        (export_root / "AltA").mkdir()
        (export_root / "AltB").mkdir()
        (export_root / "AltA" / "MI_Dupe.json").write_text("{}", encoding="utf-8")
        (export_root / "AltB" / "MI_Dupe.json").write_text("{}", encoding="utf-8")

        settings = UModelPathInferenceSettings(
            enable_umodel_path_inference=True,
            path_inference_mode=AGGRESSIVE,
            enable_suffix_index=True,
        )
        descriptors = resolve_material_descriptors(
            [
                MaterialSlotReference(
                    slot_index=0,
                    material_name="MI_Dupe",
                    material_path="PM/Content/NotHere/Materials/MI_Dupe.MI_Dupe",
                    first_index=0,
                    num_faces=1,
                )
            ],
            str(uemodel_path),
            str(export_root),
            settings=settings,
        )

    assert descriptors[0].status == "ambiguous"
    assert descriptors[0].json_path == ""
    assert descriptors[0].descriptor_path == os.path.normpath(
        "PM/Content/NotHere/Materials/MI_Dupe.MI_Dupe"
    )
    assert sorted(descriptors[0].candidates) == [
        os.path.normpath("AltA/MI_Dupe.json"),
        os.path.normpath("AltB/MI_Dupe.json"),
    ]


def test_material_resolution_unresolved_keeps_compatible_fallback_descriptor(tmp_path):
    with _scoped_umodel_tools_package():
        from umodel_tools.ueformat.material_resolution import MaterialSlotReference, resolve_material_descriptors

        export_root = tmp_path
        uemodel_dir = export_root / "PM" / "Content" / "Game" / "Mesh3D"
        uemodel_dir.mkdir(parents=True)
        uemodel_path = uemodel_dir / "Model.uemodel"

        descriptors = resolve_material_descriptors(
            [
                MaterialSlotReference(
                    slot_index=0,
                    material_name="MI_MissingPath",
                    material_path="PM/Content/Nope/MI_MissingPath.MI_MissingPath",
                    first_index=3,
                    num_faces=2,
                ),
                MaterialSlotReference(
                    slot_index=1,
                    material_name="MI_MissingName",
                    material_path="",
                    first_index=9,
                    num_faces=4,
                ),
            ],
            str(uemodel_path),
            str(export_root),
        )

    assert descriptors[0].status == "unresolved"
    assert descriptors[0].descriptor_path == os.path.normpath("PM/Content/Nope/MI_MissingPath.MI_MissingPath")
    assert descriptors[0].first_index == 3
    assert descriptors[0].num_faces == 2
    assert descriptors[1].status == "unresolved"
    assert descriptors[1].descriptor_path == "MI_MissingName.MI_MissingName"
