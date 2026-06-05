"""Support helpers for map import."""

from __future__ import annotations

import math
import os
import time
import typing as t

import bpy
import mathutils as mu

from . import utils


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


class StaticMesh:
    static_mesh_types = [
        "StaticMeshComponent",
        "InstancedStaticMeshComponent",
        "HierarchicalInstancedStaticMeshComponent",
    ]

    entity_name: str = ""
    asset_path: str = ""
    raw_object_path: str = ""
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

    def __init__(self, json_obj: t.Any, json_entity: t.Any, entity_type: str) -> None:
        self.entity_name = json_entity.get("Outer", "Error")
        self.instance_transforms = []

        if not (props := json_entity.get("Properties", None)):
            self.no_entity = True
            return

        if not props.get("StaticMesh", None):
            self.no_mesh = True
            return

        if not (object_path := props.get("StaticMesh").get("ObjectPath", None)) or object_path == "":
            self.no_path = True
            return

        if "BasicShapes" in object_path:
            self.base_shape = True
            return

        if (render_in_main_pass := props.get("bRenderInMainPass", None)) is not None and not render_in_main_pass:
            self.not_rendered = True
            return

        if (is_visible := props.get("bVisible", None)) is not None and not is_visible:
            self.invisible = True

        if ((parent := props.get("AttachParent", None)) is not None
           and (obj_name := parent.get("ObjectName", None)) is not None):
            self.parent_mtx = get_parent_transform_matrix(json_obj, *parse_ue_object_name(obj_name))

        objpath = split_object_path(object_path)
        self.raw_object_path = objpath

        self.asset_path = os.path.normpath(objpath + ".uasset")
        self.asset_path = self.asset_path[1:] if self.asset_path.startswith(os.sep) else self.asset_path

        match entity_type:
            case "StaticMeshComponent":
                self.transform = _component_transform(props)

            case "InstancedStaticMeshComponent" | "HierarchicalInstancedStaticMeshComponent":
                self.is_instanced = True

                if (instances := json_entity.get("PerInstanceSMData", None)) is None:
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

    @property
    def invalid(self) -> bool:
        return (self.no_path or self.no_entity or self.base_shape or self.no_mesh or self.no_per_instance_data
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

        return objects

    @property
    def expected_instance_count(self) -> int:
        if self.invalid:
            return 0
        return len(self.instance_transforms) if self.is_instanced else 1


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
