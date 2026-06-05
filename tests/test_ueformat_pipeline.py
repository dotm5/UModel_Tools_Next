import importlib.util
import os
import sys
import tempfile
import types


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
REFERENCE_ROOT = os.path.join(ADDON_ROOT, "reference", "my real project", "model unpack")
GENERIC_RULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "game_profiles", "rules", "generic.toml")
CHARACTER_RULE_PATH = os.path.join(
    ADDON_ROOT,
    "umodel_tools",
    "game_profiles",
    "rules",
    "wuthering_waves.toml",
)

UEMODELS = {
    os.path.join(
        REFERENCE_ROOT,
        "PM", "Content", "PaperMan", "SkinAssets", "Characters", "Kanami", "S103", "Mesh3D",
        "Kanami_Mesh_103.uemodel",
    ): {
        "vertices": 27694,
        "materials": 7,
        "bones": 194,
        "morphs": 96,
    },
    os.path.join(
        REFERENCE_ROOT,
        "PM", "Content", "PaperMan", "SkinAssets", "Characters", "Kanami", "S103", "Mesh3DLobby",
        "SK_Kanami_Lobby_S103.uemodel",
    ): {
        "vertices": 27626,
        "materials": 7,
        "bones": 194,
        "morphs": 96,
    },
    os.path.join(
        REFERENCE_ROOT,
        "PM", "Content", "PaperMan", "SkinAssets", "Characters", "Kanami", "S103", "Mesh2D",
        "Kanami_PPM_103_Skin.uemodel",
    ): {
        "vertices": 1764,
        "materials": 1,
        "bones": 103,
        "morphs": 0,
    },
}

MATERIAL_REFERENCES = [
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S001/Mesh3D/Materials/MI_Kanami_Face.MI_Kanami_Face",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S001/Mesh3D/Materials/MI_Kanami_Eye.MI_Kanami_Eye",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh3D/MI_Kanami_Hair_103.MI_Kanami_Hair_103",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh3D/T_Kanami_Skin_103.T_Kanami_Skin_103",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh3D/MI_Kanami_Body_103.MI_Kanami_Body_103",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh3D/T_Kanami_Body_Metal_103.T_Kanami_Body_Metal_103",
    "PM/Content/PaperMan/SkinAssets/Characters/Kanami/S103/Mesh2D/MI_Kanami_PPM_103.MI_Kanami_PPM_103",
]


def main():
    test_reference_uemodel_reader()
    test_reference_fmodel_material_json()
    test_uemodel_material_descriptor_lookup()
    test_wuthering_waves_rule_set()
    print("TEST_UEFORMAT_PIPELINE_OK")


def test_reference_uemodel_reader():
    if not os.path.isdir(REFERENCE_ROOT):
        print("TEST_UEFORMAT_READER_SKIPPED missing reference project")
        return

    original_package = sys.modules.pop("umodel_tools", None)
    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools")]
    sys.modules["umodel_tools"] = fake_package
    try:
        from umodel_tools.ueformat import load_uemodel  # pylint: disable=import-outside-toplevel

        for path, expected in UEMODELS.items():
            if not os.path.isfile(path):
                raise AssertionError(f"Missing reference .uemodel fixture: {path}")

            model = load_uemodel(path)
            if len(model.lods) != 1:
                raise AssertionError(f"Expected one LOD for {path}, got {len(model.lods)}")

            lod = model.lods[0]
            skeleton = model.skeleton
            if len(lod.vertices) != expected["vertices"]:
                raise AssertionError(f"{path} vertex count changed: {len(lod.vertices)}")
            if len(lod.materials) != expected["materials"]:
                raise AssertionError(f"{path} material count changed: {len(lod.materials)}")
            if (len(skeleton.bones) if skeleton else 0) != expected["bones"]:
                raise AssertionError(f"{path} bone count changed.")
            if len(lod.morphs) != expected["morphs"]:
                raise AssertionError(f"{path} morph count changed: {len(lod.morphs)}")
    finally:
        for module_name in list(sys.modules):
            if module_name == "umodel_tools" or module_name.startswith("umodel_tools."):
                del sys.modules[module_name]
        if original_package is not None:
            sys.modules["umodel_tools"] = original_package


def test_reference_fmodel_material_json():
    if not os.path.isdir(REFERENCE_ROOT):
        print("TEST_FMODEL_MATERIAL_JSON_SKIPPED missing reference project")
        return

    fmodel_material_json = _load_module(
        "fmodel_material_json",
        os.path.join(ADDON_ROOT, "umodel_tools", "fmodel_material_json.py"),
    )

    for material_reference in MATERIAL_REFERENCES:
        json_rel = fmodel_material_json.json_path_from_material_reference(material_reference)
        json_path = os.path.join(REFERENCE_ROOT, json_rel)
        if not os.path.isfile(json_path):
            raise AssertionError(f"Missing material JSON: {json_path}")

        desc = fmodel_material_json.load_material_description(json_path)
        if not desc.texture_infos:
            raise AssertionError(f"Expected textures in {json_path}")

        for texture_reference in desc.texture_infos.values():
            if texture_reference.startswith("Engine"):
                continue
            texture_rel = texture_reference[:texture_reference.rfind(".")] + ".png"
            texture_path = os.path.join(REFERENCE_ROOT, texture_rel)
            if not os.path.isfile(texture_path):
                raise AssertionError(f"Missing texture {texture_path} referenced by {json_path}")


def test_uemodel_material_descriptor_lookup():
    backend = _load_uemodel_backend_module()

    with tempfile.TemporaryDirectory() as export_root:
        uemodel_dir = os.path.join(export_root, "PM", "Content", "PaperMan", "Characters", "Kanami", "Mesh3D")
        os.makedirs(os.path.join(uemodel_dir, "Materials"), exist_ok=True)
        uemodel_path = os.path.join(uemodel_dir, "Kanami_Mesh_103.uemodel")

        direct_json = os.path.join(uemodel_dir, "Materials", "MI_ByName.json")
        with open(direct_json, "w", encoding="utf-8") as handle:
            handle.write("{}")

        referenced_rel = os.path.join("PM", "Content", "PaperMan", "Characters", "Kanami", "Mesh3D", "MI_ByPath.json")
        os.makedirs(os.path.dirname(os.path.join(export_root, referenced_rel)), exist_ok=True)
        with open(os.path.join(export_root, referenced_rel), "w", encoding="utf-8") as handle:
            handle.write("{}")

        materials = [
            types.SimpleNamespace(
                material_name="MI_ByName",
                material_path="",
                first_index=0,
                num_faces=1,
            ),
            types.SimpleNamespace(
                material_name="MI_ByPath",
                material_path="PM/Content/PaperMan/Characters/Kanami/Mesh3D/MI_ByPath.MI_ByPath",
                first_index=3,
                num_faces=2,
            ),
        ]
        descriptors = backend._build_material_descriptors(materials, uemodel_path, export_root)

    expected_by_name = os.path.normpath(
        "PM/Content/PaperMan/Characters/Kanami/Mesh3D/Materials/MI_ByName.MI_ByName"
    )
    expected_by_path = os.path.normpath(
        "PM/Content/PaperMan/Characters/Kanami/Mesh3D/MI_ByPath.MI_ByPath"
    )
    actual = [descriptor["descriptor_path"] for descriptor in descriptors]
    if actual != [expected_by_name, expected_by_path]:
        raise AssertionError(f"Unexpected descriptor lookup result: {actual!r}")


def test_wuthering_waves_rule_set():
    from umodel_tools.materials import rules as rule_module  # pylint: disable=import-outside-toplevel
    rules = rule_module.load_rule_sets([GENERIC_RULE_PATH, CHARACTER_RULE_PATH])

    cases = [
        ("BaseMap", "T_Kanami_PPM_103", "ww_diffuse"),
        ("PM_Diffuse", "T_Kanami_Body_103_D", "ww_diffuse"),
        ("NormalMap", "T_Kanami_Body_103_N", "ww_normal"),
        ("PM_Normals", "T_KokonaShiki_Body_N", "ww_normal"),
        ("Mask1", "T_Kanmami_Body_Mask1_Map", "ww_mask1"),
        ("Mask2", "T_Kanami_Face_Mask2_Map", "ww_mask2"),
        ("MatCapTexture", "MatCap_Toon9", "ww_matcap"),
        ("FaceShadowMask", "T_Kanami_SDF", "ww_face_shadow"),
        ("EmotionMask", "expression_Mask", "ww_emotion_mask"),
        ("Emotion_04", "blush_2", "ww_emotion_overlay"),
    ]

    for tex_type, tex_short_name, expected in cases:
        rule = rules.resolve(tex_type, tex_short_name)
        actual = rule.name if rule is not None else None
        if actual != expected:
            raise AssertionError(f"{tex_type}/{tex_short_name} resolved to {actual}, expected {expected}")

    generic_only = rule_module.load_rule_sets([GENERIC_RULE_PATH])
    if generic_only.resolve("Mask1", "T_Kanmami_Body_Mask1_Map") is not None:
        raise AssertionError("Character Mask1 rule should not leak into Generic map rules.")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_uemodel_backend_module():
    fake_package = types.ModuleType("umodel_tools")
    fake_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools")]
    fake_backends_package = types.ModuleType("umodel_tools.mesh_backends")
    fake_backends_package.__path__ = [os.path.join(ADDON_ROOT, "umodel_tools", "mesh_backends")]
    sys.modules["umodel_tools"] = fake_package
    sys.modules["umodel_tools.mesh_backends"] = fake_backends_package

    import importlib

    return importlib.import_module("umodel_tools.mesh_backends.backends")


if __name__ == "__main__":
    main()
