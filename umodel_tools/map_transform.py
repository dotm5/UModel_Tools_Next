import math

import mathutils as mu


def split_object_path(object_path):
    # For some reason ObjectPaths end with a period and a digit.
    # This is kind of a sucky way to split that out.

    path_parts = object_path.split(".")

    if len(path_parts) > 1:
        # Usually works, but will fail If the path contains multiple periods.
        return path_parts[0]

    # Nothing to do
    return object_path


def parse_ue_object_name(obj_name: str) -> tuple[str, str, str]:
    obj_type, obj_path, _ = obj_name.split('\'')
    _, obj_path = obj_path.split(':')

    names = obj_path.split('.')
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
        return mu.Matrix.LocRotScale(mu.Vector(self.pos),
                                     mu.Euler(self.rot_euler, 'XYZ'),
                                     mu.Vector(self.scale))


def get_parent_transform_matrix(json_obj,
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

        # obtain the parent's relative matrix
        trs = InstanceTransform()

        if (pos := props.get("RelativeLocation", None)) is not None:
            trs.pos = [pos.get("X") / 100, pos.get("Y") / -100, pos.get("Z") / 100]

        if (scale := props.get("RelativeScale3D", None)) is not None:
            trs.scale = [scale.get("X", 1), scale.get("Y", 1), scale.get("Z", 1)]

        match obj_type:
            case 'SpotLightComponent' | 'PointLightComponent':
                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (rot.get("Roll") + 90,
                                     -rot.get("Pitch") - 90,
                                     rot.get("Yaw"))
            case _:
                if (rot := props.get("RelativeRotation", None)) is not None:
                    trs.rot_euler = (math.radians(rot.get("Roll")),
                                     math.radians(-rot.get("Pitch")),
                                     math.radians(-rot.get("Yaw")))

        # obtain the parent's parent transform
        if ((parent := props.get("AttachParent", None)) is not None
           and (obj_name := parent.get("ObjectName", None)) is not None):
            return get_parent_transform_matrix(json_obj, *parse_ue_object_name(obj_name)) @ trs.matrix_4x4

        # return the absolute transform if no parent
        return trs.matrix_4x4

    return InstanceTransform().matrix_4x4
