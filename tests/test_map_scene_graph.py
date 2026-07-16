"""Regression tests for the FModel-style map reference graph."""

import importlib.util
import json
import os
import sys


ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
MODULE_PATH = os.path.join(ADDON_ROOT, "umodel_tools", "map_scene_graph.py")
WLBl_PATH = os.path.join(ADDON_ROOT, "tests", "fixtures", "map_import_samples", "Envi_Wlbl.json")
ICE_PATH = os.path.join(ADDON_ROOT, "tests", "fixtures", "map_import_samples", "Envi_Ice_Base.json")


def load_module():
    spec = importlib.util.spec_from_file_location("map_scene_graph_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ref(package, index, object_type, object_name):
    return {
        "ObjectName": f"{object_type}'Synthetic:PersistentLevel.{object_name}'",
        "ObjectPath": f"{package}.{index}",
    }


def synthetic_entities():
    package = "Game/Content/Maps/Synthetic"
    actor = {
        "Type": "Actor",
        "Name": "Actor0",
        "Properties": {
            "InstanceComponents": [ref(package, 2, "CustomStaticMeshComponent", "Mesh0")],
            "BlueprintCreatedComponents": [ref(package, 2, "CustomStaticMeshComponent", "Mesh0")],
        },
    }
    template = {
        "Type": "CustomStaticMeshComponent",
        "Name": "MeshTemplate",
        "Template": ref(package, 2, "CustomStaticMeshComponent", "Mesh0"),
        "Properties": {
            "StaticMesh": {
                "ObjectName": "StaticMesh'Cube'",
                "ObjectPath": "Engine/Content/BasicShapes/Cube.2",
            }
        },
        "PerInstanceSMData": [{"TransformData": {"Translation": {"X": 100, "Y": 0, "Z": 0}}}],
    }
    component = {
        "Type": "CustomStaticMeshComponent",
        "Name": "Mesh0",
        "Template": ref(package, 1, "CustomStaticMeshComponent", "MeshTemplate"),
        "Properties": {"AttachParent": ref(package, 3, "SceneComponent", "Root")},
    }
    parent = {
        "Type": "SceneComponent",
        "Name": "Root",
        "Properties": {"RelativeLocation": {"X": 100, "Y": 200, "Z": 300}},
    }
    level = {
        "Type": "Level",
        "Name": "PersistentLevel",
        "Actors": [ref(package, 0, "Actor", "Actor0"), None],
    }
    world = {
        "Type": "World",
        "Name": "Synthetic",
        "Package": package,
        "PersistentLevel": ref(package, 4, "Level", "PersistentLevel"),
    }
    return [actor, template, component, parent, level, world]


def test_reference_graph_and_template_fallback():
    module = load_module()
    graph = module.FModelSceneGraph(synthetic_entities())
    actors = graph.persistent_level_actors()
    assert [actor["Name"] for actor in actors] == ["Actor0"]
    components = graph.actor_components(actors[0])
    assert [component["Name"] for component in components] == ["Mesh0"]

    view = graph.component_view(components[0])
    assert graph.component_view(components[0]) is view
    assert view.mesh_source == "template"
    assert view.instance_source == "template"
    assert view.component_kind == "instanced"
    assert view.mesh_reference["ObjectPath"] == "Engine/Content/BasicShapes/Cube.2"
    assert len(view.instance_data) == 1
    assert graph.should_import_preview_component(components[0])
    assert not graph.should_import_preview_component(synthetic_entities()[1])


def test_external_package_reference_is_not_misresolved():
    module = load_module()
    graph = module.FModelSceneGraph(synthetic_entities())
    external = ref("Other/Content/Maps/External", 2, "CustomStaticMeshComponent", "Mesh0")
    assert graph.resolve_reference(external) is None


def test_basic_shape_detection():
    module = load_module()
    assert module.basic_shape_name("Engine/Content/BasicShapes/Cube") == "Cube"
    assert module.basic_shape_name(r"Engine\Content\BasicShapes\Sphere.2") == "Sphere"
    assert module.basic_shape_name("Game/Content/Props/Cube") == ""


def test_static_mesh_reference_accepts_legacy_path_only_shape():
    module = load_module()
    assert module.is_static_mesh_reference({"ObjectPath": "/Game/Props/Chair.Chair"})
    assert not module.is_static_mesh_reference({
        "ObjectPath": "/Game/Props/Chair.Chair",
        "ObjectName": "Texture2D'Chair'",
    })
    assert not module.is_static_mesh_reference({"ObjectName": "StaticMesh'Chair'"})


def test_real_wlbl_world_and_component_graph():
    module = load_module()
    with open(WLBl_PATH, mode="r", encoding="utf-8") as file:
        entities = json.load(file)
    graph = module.FModelSceneGraph(entities)
    assert graph.package_name.endswith("/Envi_Wlbl")
    assert graph.persistent_level() is not None
    assert len(graph.persistent_level_actors()) > 100
    preview_components = [entity for entity in entities if graph.is_preview_mesh_component(entity)]
    assert len(preview_components) >= 136
    importable_components = [entity for entity in preview_components if graph.should_import_preview_component(entity)]
    assert len(importable_components) == 131
    basic_shapes = [
        entity for entity in preview_components
        if module.basic_shape_name((entity.get("Properties") or {}).get("StaticMesh", {}).get("ObjectPath", ""))
    ]
    assert len(basic_shapes) == 11


def test_real_blueprint_created_spline_components_are_reachable():
    module = load_module()
    with open(ICE_PATH, mode="r", encoding="utf-8") as file:
        entities = json.load(file)
    graph = module.FModelSceneGraph(entities)
    importable_splines = [
        entity
        for entity in entities
        if isinstance(entity, dict)
        and graph.should_import_preview_component(entity)
        and graph.component_view(entity).component_kind == "spline"
    ]
    assert len(importable_splines) == 37


def main():
    tests = [
        test_reference_graph_and_template_fallback,
        test_external_package_reference_is_not_misresolved,
        test_basic_shape_detection,
        test_static_mesh_reference_accepts_legacy_path_only_shape,
        test_real_wlbl_world_and_component_graph,
        test_real_blueprint_created_spline_components_are_reachable,
    ]
    for test_fn in tests:
        test_fn()
    print("TEST_MAP_SCENE_GRAPH_OK")


if __name__ == "__main__":
    main()
