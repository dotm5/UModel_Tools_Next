"""Basic PSA-to-Blender Action bridge for experimental skeletal map previews.

The transform conversion follows the PSK/PSA import convention used by the
GPL PSK/PSA Blender importers already referenced by this project.  This module
intentionally imports one sequence only and does not implement Unreal animation
blueprints, montages, notifies, retargeting, or root-motion semantics.
"""

from __future__ import annotations

import dataclasses
import os
import typing as t

import bpy
from bpy_extras import anim_utils
from mathutils import Quaternion, Vector

from . import psa_reader


@dataclasses.dataclass
class PsaImportResult:
    action: bpy.types.Action
    sequence: psa_reader.PsaSequence
    matched_bone_count: int
    missing_bone_names: list[str]
    fcurve_count: int


@dataclasses.dataclass
class _ImportBone:
    pose_bone: t.Any
    original_location: Vector
    original_rotation: Quaternion
    post_rotation: Quaternion
    has_mapped_parent: bool


def import_psa_action(
    filepath: str,
    armature_object: bpy.types.Object,
    preferred_sequence_name: str = "",
    translation_scale: float = 0.01,
) -> PsaImportResult:
    """Load one PSA sequence, create a Blender Action, and assign it to an armature."""

    if armature_object is None or armature_object.type != "ARMATURE":
        raise ValueError("PSA import requires an armature object.")

    psa = psa_reader.load_psa(filepath)
    sequence = psa.find_sequence(preferred_sequence_name)
    sequence_keys = psa.sequence_keys(sequence)
    sequence_scale_keys = psa.sequence_scale_keys(sequence)

    armature_bones_by_name = {
        bone.name.rstrip().casefold(): bone
        for bone in armature_object.data.bones
    }
    psa_names = [bone.name.rstrip() for bone in psa.bones[:sequence.bone_count]]
    mapped_armature_names = {
        armature_bones_by_name[name.casefold()].name
        for name in psa_names
        if name.casefold() in armature_bones_by_name
    }

    import_bones: list[_ImportBone | None] = []
    missing_bone_names: list[str] = []
    for psa_name in psa_names:
        armature_bone = armature_bones_by_name.get(psa_name.casefold())
        if armature_bone is None:
            import_bones.append(None)
            missing_bone_names.append(psa_name)
            continue

        pose_bone = armature_object.pose.bones[armature_bone.name]
        pose_bone.rotation_mode = "QUATERNION"
        original_location, original_rotation, post_rotation = _get_bind_pose(armature_bone)
        import_bones.append(
            _ImportBone(
                pose_bone=pose_bone,
                original_location=original_location,
                original_rotation=original_rotation,
                post_rotation=post_rotation,
                has_mapped_parent=(
                    armature_bone.parent is not None
                    and armature_bone.parent.name in mapped_armature_names
                ),
            )
        )

    matched_bone_count = sum(item is not None for item in import_bones)
    if matched_bone_count == 0:
        raise ValueError("No PSA bones matched the target armature.")

    action = bpy.data.actions.new(name=sequence.name or os.path.splitext(os.path.basename(filepath))[0])
    slot = action.slots.new("OBJECT", armature_object.name)
    channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
    frame_count = sequence.frame_count
    has_scale_keys = bool(sequence_scale_keys)
    fcurve_count = 0

    for bone_index, import_bone in enumerate(import_bones):
        if import_bone is None:
            continue

        pose_bone = import_bone.pose_bone
        rotation_path = pose_bone.path_from_id("rotation_quaternion")
        location_path = pose_bone.path_from_id("location")
        scale_path = pose_bone.path_from_id("scale")
        curves = [
            channelbag.fcurves.ensure(rotation_path, index=index, group_name=pose_bone.name)
            for index in range(4)
        ]
        curves.extend(
            channelbag.fcurves.ensure(location_path, index=index, group_name=pose_bone.name)
            for index in range(3)
        )
        if has_scale_keys:
            curves.extend(
                channelbag.fcurves.ensure(scale_path, index=index, group_name=pose_bone.name)
                for index in range(3)
            )

        curve_values = [[] for _curve in curves]
        for frame_index in range(frame_count):
            key_index = frame_index * sequence.bone_count + bone_index
            key = sequence_keys[key_index]
            scale = sequence_scale_keys[key_index].scale if has_scale_keys else (1.0, 1.0, 1.0)
            values = _calculate_pose_values(import_bone, key, scale, translation_scale)
            for curve_index, value in enumerate(values[:len(curves)]):
                curve_values[curve_index].append(float(value))

        for curve, values in zip(curves, curve_values):
            _write_linear_keyframes(curve, values)
        fcurve_count += len(curves)

    action["umodel_tools_psa_source"] = os.path.abspath(filepath)
    action["umodel_tools_psa_sequence"] = sequence.name
    action["umodel_tools_psa_fps"] = sequence.fps
    action["umodel_tools_psa_basic_preview"] = True

    animation_data = armature_object.animation_data_create()
    animation_data.action = action
    armature_object["umodel_tools_psa_source"] = os.path.abspath(filepath)
    armature_object["umodel_tools_psa_sequence"] = sequence.name

    scene = bpy.context.scene
    scene.frame_start = min(scene.frame_start, 0)
    scene.frame_end = max(scene.frame_end, 0, frame_count - 1)
    rounded_fps = max(1, round(sequence.fps))
    scene.render.fps = rounded_fps
    scene.render.fps_base = rounded_fps / sequence.fps if sequence.fps > 0.0 else 1.0

    return PsaImportResult(
        action=action,
        sequence=sequence,
        matched_bone_count=matched_bone_count,
        missing_bone_names=missing_bone_names,
        fcurve_count=fcurve_count,
    )


def _get_bind_pose(armature_bone: t.Any) -> tuple[Vector, Quaternion, Quaternion]:
    if all(name in armature_bone for name in ("orig_loc", "orig_quat", "post_quat")):
        return (
            Vector(armature_bone["orig_loc"]),
            Quaternion(armature_bone["orig_quat"]),
            Quaternion(armature_bone["post_quat"]),
        )

    if armature_bone.parent is not None:
        original_location = armature_bone.matrix_local.translation - armature_bone.parent.matrix_local.translation
        original_location.rotate(armature_bone.parent.matrix_local.to_quaternion().conjugated())
        original_rotation = armature_bone.matrix_local.to_quaternion()
        original_rotation.rotate(armature_bone.parent.matrix_local.to_quaternion().conjugated())
        original_rotation.conjugate()
    else:
        original_location = armature_bone.matrix_local.translation.copy()
        original_rotation = armature_bone.matrix_local.to_quaternion().conjugated()

    return original_location, original_rotation, original_rotation.conjugated()


def _calculate_pose_values(
    import_bone: _ImportBone,
    key: psa_reader.PsaKey,
    scale: tuple[float, float, float],
    translation_scale: float,
) -> tuple[float, ...]:
    key_rotation = Quaternion(key.rotation)
    key_location = Vector(key.location) * translation_scale

    rotation = import_bone.post_rotation.copy()
    rotation.rotate(import_bone.original_rotation)
    animated_rotation = import_bone.post_rotation.copy()
    if import_bone.has_mapped_parent:
        animated_rotation.rotate(key_rotation)
    else:
        animated_rotation.rotate(key_rotation.conjugated())
    rotation.rotate(animated_rotation.conjugated())

    location = key_location - import_bone.original_location
    location.rotate(import_bone.post_rotation.conjugated())
    return (
        rotation.w,
        rotation.x,
        rotation.y,
        rotation.z,
        location.x,
        location.y,
        location.z,
        scale[0],
        scale[1],
        scale[2],
    )


def _write_linear_keyframes(fcurve: t.Any, values: list[float]) -> None:
    fcurve.keyframe_points.add(len(values))
    coordinates = []
    for frame_index, value in enumerate(values):
        coordinates.extend((float(frame_index), value))
    fcurve.keyframe_points.foreach_set("co", coordinates)
    for point in fcurve.keyframe_points:
        point.interpolation = "LINEAR"
    fcurve.update()


__all__ = ("PsaImportResult", "import_psa_action")
