"""Support helpers for map import."""

from __future__ import annotations

import math
import os
import time
import typing as t

import bpy
import mathutils as mu

from . import utils
from . import map_scene_graph


def split_object_path(object_path: str) -> str:
    path_parts = object_path.split(".")
    if len(path_parts) > 1:
        return path_parts[0]
    return object_path


def parse_ue_object_name(obj_name: str) -> tuple[str, str, str]:
    obj_type, obj_path, _ = obj_name.split("'")
    _, obj_path = obj_path.split(":")

    names = obj_path.split(".")
    assert len(names) >= 2

    return obj_type, names[-2], names[-1]


class InstanceTransform:
    pos: tuple[float, float, float]
    rot_euler: tuple[float, float, float]
    scale: tuple[float, float, float]

    def __init__(self,
                 pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 rot_euler: tuple[float, float, float] = (0.0, 0.0, 0.0),
                 scale: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
        self.pos = pos
        self.rot_euler = rot_euler
        self.scale = scale

    @property
    def matrix_4x4(self) -> mu.Matrix:
        return mu.Matrix.LocRotScale(
            mu.Vector(self.pos),
            mu.Euler(self.rot_euler, "XYZ"),
            mu.Vector(self.scale),
        )


def get_parent_transform_matrix(json_obj: t.Any,
                                obj_type: str,
                                obj_outer: str,
                                obj_name: str) -> mu.Matrix:
    for entity in json_obj:
        if (((entity_type := entity.get("Type", None)) is None or entity_type != obj_type)
           or ((entity_outer := entity.get("Outer", None)) is None or entity_outer != obj_outer)
           or ((entity_name := entity.get("Name", None)) is None or entity_name != obj_name)):
            continue

        props = entity.get("Properties", None)
        if props is None:
            return InstanceTransform().matrix_4x4

        trs = InstanceTransform()

        if (pos := props.get("RelativeLocation", None)) is not None:
            trs.pos = [pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100]

        if (scale := props.get("RelativeScale3D", None)) is not None:
            trs.scale = [scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1)]

        match obj_type:
            case "SpotLightComponent" | "PointLightComponent":
                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (rot.get("Roll") + 90, -rot.get("Pitch") - 90, rot.get("Yaw"))
            case _:
                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (
                        math.radians(rot.get("Roll")),
                        math.radians(-rot.get("Pitch")),
                        math.radians(-rot.get("Yaw")),
                    )

        if ((parent := props.get("AttachParent", None)) is not None
           and (parent_obj_name := parent.get("ObjectName", None)) is not None):
            return get_parent_transform_matrix(json_obj, *parse_ue_object_name(parent_obj_name)) @ trs.matrix_4x4

        return trs.matrix_4x4

    return InstanceTransform().matrix_4x4


def get_reference_transform_matrix(
    json_obj: t.Any,
    reference: t.Any,
    scene_graph: map_scene_graph.FModelSceneGraph | None = None,
    visited: set[int] | None = None,
) -> mu.Matrix:
    """Resolve a component reference and compose its AttachParent chain."""

    entity = scene_graph.resolve_reference(reference) if scene_graph is not None else None
    if entity is None and isinstance(reference, dict):
        object_name = reference.get("ObjectName")
        if isinstance(object_name, str):
            try:
                object_type, object_outer, leaf_name = parse_ue_object_name(object_name)
            except (AssertionError, ValueError):
                return InstanceTransform().matrix_4x4
            entity = _find_entity(json_obj, object_type, object_outer, leaf_name)

    if entity is None:
        return InstanceTransform().matrix_4x4

    visited = visited if visited is not None else set()
    entity_id = id(entity)
    if entity_id in visited:
        return InstanceTransform().matrix_4x4
    visited.add(entity_id)

    props = entity.get("Properties")
    if not isinstance(props, dict):
        return InstanceTransform().matrix_4x4

    local_matrix = _component_transform(props).matrix_4x4
    parent = props.get("AttachParent")
    if isinstance(parent, dict):
        return get_reference_transform_matrix(json_obj, parent, scene_graph, visited) @ local_matrix
    return local_matrix


def _find_entity(json_obj: t.Any, obj_type: str, obj_outer: str, obj_name: str) -> dict[str, t.Any] | None:
    for entity in json_obj:
        if (
            entity.get("Type") == obj_type
            and entity.get("Outer") == obj_outer
            and entity.get("Name") == obj_name
        ):
            return entity
    return None


class StaticMesh:
    static_mesh_types = [
        "StaticMeshComponent",
        "InstancedStaticMeshComponent",
        "HierarchicalInstancedStaticMeshComponent",
    ]

    entity_name: str = ""
    asset_path: str = ""
    raw_object_path: str = ""
    basic_shape_name: str = ""
    mesh_source: str = "missing"
    instance_source: str = "missing"
    component_kind: str = "static"
    transform: InstanceTransform
    instance_transforms: list[InstanceTransform]
    parent_mtx: t.Optional[mu.Matrix] = None

    no_entity: bool = False
    no_mesh: bool = False
    no_path: bool = False
    no_per_instance_data: bool = False
    base_shape: bool = False
    is_instanced: bool = False
    not_rendered: bool = False
    invisible: bool = False

    def __init__(
        self,
        json_obj: t.Any,
        json_entity: t.Any,
        entity_type: str,
        scene_graph: map_scene_graph.FModelSceneGraph | None = None,
    ) -> None:
        self.entity_name = json_entity.get("Outer", "Error")
        self.instance_transforms = []
        self.parent_mtx = None
        self.no_entity = False
        self.no_mesh = False
        self.no_path = False
        self.no_per_instance_data = False
        self.base_shape = False
        self.is_instanced = False
        self.not_rendered = False
        self.invisible = False
        self.basic_shape_name = ""
        self.mesh_source = "missing"
        self.instance_source = "missing"
        self.component_kind = "static"

        component_view = scene_graph.component_view(json_entity) if scene_graph is not None else None

        props = component_view.properties if component_view is not None else json_entity.get("Properties", None)
        if not props:
            self.no_entity = True
            return

        mesh_reference = component_view.mesh_reference if component_view is not None else props.get("StaticMesh", None)
        if component_view is not None:
            self.mesh_source = component_view.mesh_source
            self.instance_source = component_view.instance_source
            self.component_kind = component_view.component_kind
        elif mesh_reference is not None:
            self.mesh_source = "direct"

        if not mesh_reference:
            self.no_mesh = True
            return

        if not (object_path := mesh_reference.get("ObjectPath", None)) or object_path == "":
            self.no_path = True
            return

        self.basic_shape_name = map_scene_graph.basic_shape_name(object_path)
        if self.basic_shape_name:
            self.base_shape = True

        if (render_in_main_pass := props.get("bRenderInMainPass", None)) is not None and not render_in_main_pass:
            self.not_rendered = True
            return

        if (is_visible := props.get("bVisible", None)) is not None and not is_visible:
            self.invisible = True

        if isinstance((parent := props.get("AttachParent", None)), dict):
            self.parent_mtx = get_reference_transform_matrix(json_obj, parent, scene_graph)

        objpath = split_object_path(object_path)
        self.raw_object_path = objpath

        self.asset_path = os.path.normpath(objpath + ".uasset")
        self.asset_path = self.asset_path[1:] if self.asset_path.startswith(os.sep) else self.asset_path

        match self.component_kind:
            case "static":
                self.transform = _component_transform(props)

            case "instanced":
                self.is_instanced = True

                instances = (
                    component_view.instance_data
                    if component_view is not None
                    else json_entity.get("PerInstanceSMData", None)
                )
                if instances is None:
                    self.no_per_instance_data = True
                    return

                self.transform = _component_transform(props)

                for instance in instances:
                    trs = InstanceTransform()

                    if (trs_data := instance.get("TransformData", None)) is not None:
                        if (pos := trs_data.get("Translation", None)) is not None:
                            trs.pos = (pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100)

                        if (rot := trs_data.get("Rotation", None)) is not None:
                            rot_quat = mu.Quaternion((rot.get("W"), rot.get("X"), rot.get("Y"), rot.get("Z")))
                            quat_to_euler: mu.Euler = rot_quat.to_euler()
                            trs.rot_euler = (-quat_to_euler.x, quat_to_euler.y, -quat_to_euler.z)

                        if (scale := trs_data.get("Scale3D", None)) is not None:
                            trs.scale = (scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1))

                    self.instance_transforms.append(trs)

            case "spline":
                self.transform = _component_transform(props)
                self._apply_spline_chord_transform(props)

            case _:
                self.transform = _component_transform(props)

    @property
    def invalid(self) -> bool:
        return (self.no_path or self.no_entity or self.no_mesh or self.no_per_instance_data
                or self.not_rendered or self.invisible)

    def link_object_instance(self,
                             obj: bpy.types.Object,
                             collection: bpy.types.Collection) -> list[bpy.types.Object]:
        if self.invalid:
            print(f"Refusing to import {self.entity_name} due to failed checks.")
            return []

        objects = []
        trs = self.transform

        if self.is_instanced:
            for instance_trs in self.instance_transforms:
                mat_world = trs.matrix_4x4 @ instance_trs.matrix_4x4
                new_obj = bpy.data.objects.new(
                    utils.normalize_ue_name(obj.name, fallback="StaticMesh"),
                    object_data=obj.data,
                )
                new_obj.rotation_mode = "XYZ"

                if self.parent_mtx is None:
                    new_obj.matrix_world = mat_world
                else:
                    new_obj.matrix_world = self.parent_mtx @ mat_world

                collection.objects.link(new_obj)
                objects.append(new_obj)

        else:
            new_obj = bpy.data.objects.new(
                utils.normalize_ue_name(obj.name, fallback="StaticMesh"),
                object_data=obj.data,
            )

            if self.parent_mtx is None:
                new_obj.scale = (trs.scale[0], trs.scale[1], trs.scale[2])
                new_obj.location = (trs.pos[0], trs.pos[1], trs.pos[2])
                new_obj.rotation_mode = "XYZ"
                new_obj.rotation_euler = mu.Euler((trs.rot_euler[0], trs.rot_euler[1], trs.rot_euler[2]), "XYZ")
            else:
                new_obj.matrix_world = self.parent_mtx @ trs.matrix_4x4

            collection.objects.link(new_obj)
            objects.append(new_obj)

        if self.component_kind == "spline":
            for new_obj in objects:
                new_obj["umodel_tools_geometry_fallback"] = "spline_chord_approximation"
                new_obj["umodel_tools_preview_fallback"] = "spline_chord_approximation"
                new_obj["umodel_tools_unreal_asset_path"] = self.raw_object_path
        if self.mesh_source == "template":
            for new_obj in objects:
                new_obj["umodel_tools_reference_fallback"] = "template_mesh_reference"
                if not new_obj.get("umodel_tools_preview_fallback"):
                    new_obj["umodel_tools_preview_fallback"] = "template_mesh_reference"
                new_obj["umodel_tools_unreal_asset_path"] = self.raw_object_path

        return objects

    @property
    def expected_instance_count(self) -> int:
        if self.invalid:
            return 0
        return len(self.instance_transforms) if self.is_instanced else 1

    def _apply_spline_chord_transform(self, props: dict[str, t.Any]) -> None:
        """Place an undeformed spline mesh along its start/end chord.

        FModel deforms spline meshes in the GPU viewer.  Blender map recovery
        cannot reproduce that without the source spline mesh evaluator, so the
        generic fallback preserves the segment's position, direction, and
        chord length and labels the result as an approximation.
        """

        spline = props.get("SplineParams")
        if not isinstance(spline, dict):
            return
        start = _ue_vector_to_blender(spline.get("StartPos"))
        end = _ue_vector_to_blender(spline.get("EndPos"))
        if start is None or end is None:
            return
        direction = end - start
        if direction.length <= 1e-8:
            self.transform.pos = tuple(start)
            return

        forward_axis = str(props.get("ForwardAxis", "ESplineMeshAxis::X")).rsplit("::", 1)[-1]
        axis = {
            "X": mu.Vector((1.0, 0.0, 0.0)),
            "Y": mu.Vector((0.0, 1.0, 0.0)),
            "Z": mu.Vector((0.0, 0.0, 1.0)),
        }.get(forward_axis, mu.Vector((1.0, 0.0, 0.0)))
        rotation = axis.rotation_difference(direction.normalized()).to_euler("XYZ")
        midpoint = (start + end) * 0.5
        self.transform.pos = tuple(midpoint)
        self.transform.rot_euler = tuple(rotation)
        scale = list(self.transform.scale)
        scale[{"X": 0, "Y": 1, "Z": 2}.get(forward_axis, 0)] *= direction.length
        self.transform.scale = tuple(scale)


def should_print_static_mesh_progress(static_mesh_seen: int,
                                      last_progress_print: float,
                                      interval_seconds: float = 30.0) -> bool:
    return static_mesh_seen % 100 == 0 or time.monotonic() - last_progress_print >= interval_seconds


def format_static_mesh_progress(entity_index: int,
                                total_entities: int,
                                static_mesh_seen: int,
                                imported_instances: int,
                                missing_mesh: int) -> str:
    return (
        "Map import progress: "
        f"entity={entity_index}/{total_entities}, "
        f"static_mesh={static_mesh_seen}, "
        f"imported_instances={imported_instances}, "
        f"missing_mesh={missing_mesh}"
    )


def _component_transform(props: dict[str, t.Any]) -> InstanceTransform:
    trs = InstanceTransform()

    if (pos := props.get("RelativeLocation", None)) is not None:
        trs.pos = (pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100)

    if (rot := props.get("RelativeRotation", None)) is not None:
        trs.rot_euler = (
            math.radians(rot.get("Roll")),
            math.radians(-rot.get("Pitch")),
            math.radians(-rot.get("Yaw")),
        )

    if (scale := props.get("RelativeScale3D", None)) is not None:
        trs.scale = (scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1))

    return trs


def _ue_vector_to_blender(value: t.Any) -> mu.Vector | None:
    if not isinstance(value, dict):
        return None
    return mu.Vector((
        float(value.get("X", 0.0)) / 100.0,
        float(value.get("Y", 0.0)) / -100.0,
        float(value.get("Z", 0.0)) / 100.0,
    ))


class PreviewMeshSource:
    """Minimal object-like wrapper accepted by ``StaticMesh.link_object_instance``."""

    def __init__(self, name: str, data: bpy.types.Mesh) -> None:
        self.name = name
        self.data = data


def create_basic_shape_source(shape_name: str) -> PreviewMeshSource:
    """Create a correctly sized procedural replacement for Engine BasicShapes."""

    vertices, faces = _basic_shape_geometry(shape_name)
    mesh = bpy.data.meshes.new(f"UModelTools_{shape_name}_PreviewFallback")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh["umodel_tools_preview_fallback"] = "procedural_basic_shape"
    mesh["umodel_tools_basic_shape"] = shape_name
    return PreviewMeshSource(shape_name, mesh)


def _basic_shape_geometry(shape_name: str) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    if shape_name == "Cube":
        vertices = [
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5),
            (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5),
            (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ]
        faces = [
            (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
            (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        ]
        return vertices, faces
    if shape_name == "Plane":
        return [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)], [(0, 1, 2, 3)]
    if shape_name in {"Cylinder", "Cone"}:
        return _radial_shape_geometry(shape_name, segments=32)
    if shape_name == "Sphere":
        return _sphere_geometry(segments=32, rings=16)
    raise ValueError(f"Unsupported Engine BasicShapes primitive: {shape_name!r}")


def _radial_shape_geometry(
    shape_name: str,
    segments: int,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    bottom = [
        (0.5 * math.cos(2.0 * math.pi * i / segments), 0.5 * math.sin(2.0 * math.pi * i / segments), -0.5)
        for i in range(segments)
    ]
    if shape_name == "Cone":
        vertices = [*bottom, (0.0, 0.0, 0.5)]
        apex = segments
        faces = [tuple(reversed(range(segments)))]
        faces.extend((i, (i + 1) % segments, apex) for i in range(segments))
        return vertices, faces

    top = [(x, y, 0.5) for x, y, _ in bottom]
    vertices = [*bottom, *top]
    faces = [tuple(reversed(range(segments))), tuple(range(segments, segments * 2))]
    faces.extend((i, (i + 1) % segments, (i + 1) % segments + segments, i + segments) for i in range(segments))
    return vertices, faces


def _sphere_geometry(
    segments: int,
    rings: int,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    vertices = [(0.0, 0.0, 0.5)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        z = 0.5 * math.cos(phi)
        radius = 0.5 * math.sin(phi)
        for segment in range(segments):
            theta = 2.0 * math.pi * segment / segments
            vertices.append((radius * math.cos(theta), radius * math.sin(theta), z))
    bottom = len(vertices)
    vertices.append((0.0, 0.0, -0.5))

    faces: list[tuple[int, ...]] = []
    for segment in range(segments):
        faces.append((0, 1 + segment, 1 + (segment + 1) % segments))
    for ring in range(rings - 2):
        current = 1 + ring * segments
        following = current + segments
        for segment in range(segments):
            nxt = (segment + 1) % segments
            faces.append((current + segment, following + segment, following + nxt, current + nxt))
    last_ring = 1 + (rings - 2) * segments
    for segment in range(segments):
        faces.append((last_ring + segment, bottom, last_ring + (segment + 1) % segments))
    return vertices, faces
