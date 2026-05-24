import math
import os
import typing as t

import bpy
import mathutils as mu

from . import utils
from .map_transform import InstanceTransform, get_parent_transform_matrix, parse_ue_object_name, split_object_path


class StaticMesh:
    static_mesh_types = [
        'StaticMeshComponent',
        'InstancedStaticMeshComponent',
        'HierarchicalInstancedStaticMeshComponent'
    ]

    entity_name: str = ""
    asset_path: str = ""
    raw_object_path: str = ""
    transform: InstanceTransform
    instance_transforms: list[InstanceTransform]
    parent_mtx: t.Optional[mu.Matrix] = None

    # these are just properties to help with debugging
    no_entity: bool = False
    no_mesh: bool = False
    no_path: bool = False
    no_per_instance_data: bool = False
    base_shape: bool = False
    is_instanced: bool = False
    not_rendered: bool = False
    invisible: bool = False

    def __init__(self, json_obj: t.Any, json_entity: t.Any, entity_type: str) -> None:
        self.entity_name = json_entity.get("Outer", 'Error')
        self.instance_transforms = []

        if not (props := json_entity.get("Properties", None)):
            self.no_entity = True
            return

        if not props.get("StaticMesh", None):
            self.no_mesh = True
            return

        if not (object_path := props.get("StaticMesh").get("ObjectPath", None)) or object_path == '':
            self.no_path = True
            return

        if 'BasicShapes' in object_path:
            # What is a BasicShape? Do we need these?
            self.base_shape = True
            return

        if (render_in_main_pass := props.get("bRenderInMainPass", None)) is not None and not render_in_main_pass:
            self.not_rendered = True
            return

        if (is_visbile := props.get("bVisible", None)) is not None and not is_visbile:
            self.invisible = True

        if ((parent := props.get("AttachParent", None)) is not None
           and (obj_name := parent.get("ObjectName", None)) is not None):
            self.parent_mtx = get_parent_transform_matrix(json_obj, *parse_ue_object_name(obj_name))

        objpath = split_object_path(object_path)
        self.raw_object_path = objpath

        self.asset_path = os.path.normpath(objpath + ".uasset")
        self.asset_path = self.asset_path[1:] if self.asset_path.startswith(os.sep) else self.asset_path

        match entity_type:
            case 'StaticMeshComponent':
                trs = InstanceTransform()

                if (pos := props.get("RelativeLocation", None)) is not None:
                    trs.pos = (pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100)

                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (math.radians(rot.get("Roll")),
                                     math.radians(-rot.get("Pitch")),
                                     math.radians(-rot.get("Yaw")))

                if (scale := props.get("RelativeScale3D", None)) is not None:
                    trs.scale = (scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1))

                self.transform = trs

            case 'InstancedStaticMeshComponent' | 'HierarchicalInstancedStaticMeshComponent':
                self.is_instanced = True

                if (instances := json_entity.get("PerInstanceSMData", None)) is None:
                    self.no_per_instance_data = True
                    return

                trs = InstanceTransform()

                if (pos := props.get("RelativeLocation", None)) is not None:
                    trs.pos = (pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100)

                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (math.radians(rot.get("Roll")),
                                     math.radians(-rot.get("Pitch")),
                                     math.radians(-rot.get("Yaw")))

                if (scale := props.get("RelativeScale3D", None)) is not None:
                    trs.scale = (scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1))

                self.transform = trs

                for instance in instances:
                    trs = InstanceTransform()

                    if (trs_data := instance.get("TransformData", None)) is not None:
                        if (pos := trs_data.get("Translation", None)) is not None:
                            trs.pos = (pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100)

                        if (rot := trs_data.get("Rotation", None)) is not None:
                            rot_quat = mu.Quaternion((rot.get("W"), rot.get("X"), rot.get("Y"), rot.get("Z")))
                            quat_to_euler: mu.Euler = rot_quat.to_euler()  # pylint: disable=no-value-for-parameter
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
            print(f'Refusing to import {self.entity_name} due to failed checks.')
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
                new_obj.rotation_mode = 'XYZ'

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
                new_obj.rotation_mode = 'XYZ'
                new_obj.rotation_euler = mu.Euler((trs.rot_euler[0], trs.rot_euler[1], trs.rot_euler[2]), 'XYZ')
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
