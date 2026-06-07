"""Mesh backend interfaces, concrete backends, and registry."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import typing as t


MAIN_ASSET_OBJECT_KEY = "umodel_tools_main_asset_object"
IMPORTED = "imported"
MISSING = "missing"
UNSUPPORTED = "unsupported"
FAILED = "failed"


@dataclasses.dataclass
class MeshImportContext:
    blender_context: t.Any = None
    asset_path: str = ""
    asset_name: str = ""
    source_filepath: str = ""
    asset_library_dir: str = ""
    umodel_export_dir: str = ""
    game_profile: str = ""
    import_report: t.Any = None
    options: dict[str, t.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class MeshImportResult:
    status: str
    objects: list[t.Any] = dataclasses.field(default_factory=list)
    main_object: t.Any = None
    mesh_data: t.Any = None
    source_filepath: str = ""
    backend_id: str = ""
    warnings: list[str] = dataclasses.field(default_factory=list)
    metadata: dict[str, t.Any] = dataclasses.field(default_factory=dict)


class MeshImportBackend:
    id: str = ""
    label: str = ""
    supported_extensions: tuple[str, ...] = ()
    priority: int = 0
    supports_static_mesh: bool = True
    supports_skeletal_mesh: bool = False
    supports_armature: bool = False
    supports_morph_targets: bool = False
    supports_animation: bool = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        return filepath.lower().endswith(self.supported_extensions)

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        raise NotImplementedError


class PskMeshBackend(MeshImportBackend):
    id = "PSK"
    label = "PSK/PSKX"
    supported_extensions = (".pskx", ".psk")
    priority = 100
    supports_static_mesh = True
    supports_skeletal_mesh = False
    supports_armature = False
    supports_morph_targets = False
    supports_animation = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        return os.path.splitext(filepath)[1].lower() in self.supported_extensions

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        if not os.path.isfile(filepath):
            return MeshImportResult(
                status=MISSING,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=[f"Mesh file does not exist: {filepath}"],
            )

        blender_context = context.blender_context
        before_objects = set(getattr(getattr(blender_context, "scene", None), "objects", ()))

        from .. import psk_importer  # Imported lazily to keep backend registry importable without bpy.

        captured_stdout = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout):
            imported = psk_importer.import_psk_mesh(
                filepath=filepath,
                context=blender_context,
                import_bones=False,
            )

        main_object = getattr(blender_context, "object", None)
        scene_objects = getattr(getattr(blender_context, "scene", None), "objects", ())
        objects = [obj for obj in scene_objects if obj not in before_objects]
        if main_object is not None and main_object not in objects:
            objects.append(main_object)

        if not imported or main_object is None:
            return MeshImportResult(
                status=FAILED,
                objects=objects,
                main_object=main_object,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=["PSK importer returned no active object."],
                metadata={"importer_output": captured_stdout.getvalue()},
            )

        return MeshImportResult(
            status=IMPORTED,
            objects=objects,
            main_object=main_object,
            mesh_data=getattr(main_object, "data", None),
            source_filepath=filepath,
            backend_id=self.id,
            metadata={
                "animated_material_layout": filepath.lower().endswith(".psk"),
                "importer_output": captured_stdout.getvalue(),
            },
        )


class UModelMeshBackend(MeshImportBackend):
    id = "UEMODEL"
    label = "UEFormat .uemodel"
    supported_extensions = (".uemodel",)
    priority = 50
    supports_static_mesh = True
    supports_skeletal_mesh = True
    supports_armature = True
    supports_morph_targets = True
    supports_animation = False

    def can_import(self, filepath: str, context: MeshImportContext | None = None) -> bool:
        return os.path.splitext(filepath)[1].lower() in self.supported_extensions

    def import_mesh(self, filepath: str, context: MeshImportContext) -> MeshImportResult:
        if not os.path.isfile(filepath):
            return MeshImportResult(
                status=MISSING,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=[f"Mesh file does not exist: {filepath}"],
            )

        try:
            return _import_uemodel(filepath, context)
        except Exception as exc:  # pragma: no cover - Blender importer errors are surfaced in integration tests.
            return MeshImportResult(
                status=FAILED,
                source_filepath=filepath,
                backend_id=self.id,
                warnings=[f"UEFormat import failed: {exc}"],
            )


def _import_uemodel(filepath: str, context: MeshImportContext) -> MeshImportResult:
    import bpy  # pylint: disable=import-outside-toplevel
    import mathutils  # pylint: disable=import-outside-toplevel

    from ..ueformat import load_uemodel  # pylint: disable=import-outside-toplevel

    options = context.options or {}
    scale_factor = float(options.get("ueformat_scale_factor", 0.01))
    target_lod_index = int(options.get("target_lod", 0))
    import_skeleton = bool(options.get("import_skeleton", False))
    import_morph_targets = bool(options.get("import_morph_targets", True))

    model = load_uemodel(filepath, scale=scale_factor)
    if not model.lods:
        return MeshImportResult(
            status=FAILED,
            source_filepath=filepath,
            backend_id=UModelMeshBackend.id,
            warnings=["UEFormat model contains no LODs."],
        )

    lod = model.lods[min(max(target_lod_index, 0), len(model.lods) - 1)]
    mesh_name = f"{model.name}_{lod.name}"
    mesh_data = bpy.data.meshes.new(mesh_name)
    mesh_data.from_pydata(lod.vertices, [], lod.indices)
    mesh_data.update()

    mesh_object = bpy.data.objects.new(mesh_name, mesh_data)
    mesh_object[MAIN_ASSET_OBJECT_KEY] = True
    context.blender_context.collection.objects.link(mesh_object)

    if lod.normals:
        try:
            mesh_data.polygons.foreach_set("use_smooth", [True] * len(mesh_data.polygons))
            mesh_data.normals_split_custom_set_from_vertices(lod.normals)
            if hasattr(mesh_data, "use_auto_smooth"):
                mesh_data.use_auto_smooth = True
        except (AttributeError, RuntimeError, ValueError):
            pass

    _apply_uvs(mesh_data, lod.uvs)
    _apply_vertex_colors(mesh_data, lod.colors)
    _apply_material_slots(bpy, mesh_data, lod.materials)
    _apply_weights(mesh_object, model, lod)
    if import_morph_targets:
        _apply_morph_targets(mesh_object, lod)

    objects = [mesh_object]
    armature_object = None
    if import_skeleton and model.skeleton is not None and model.skeleton.bones:
        armature_object = _create_armature(bpy, mathutils, context, model, mesh_object)
        objects.append(armature_object)

    material_descriptors = _build_material_descriptors(
        lod.materials,
        filepath,
        context.umodel_export_dir,
    )

    return MeshImportResult(
        status=IMPORTED,
        objects=objects,
        main_object=mesh_object,
        mesh_data=mesh_data,
        source_filepath=filepath,
        backend_id=UModelMeshBackend.id,
        metadata={
            "ueformat_model_name": model.name,
            "ueformat_version": model.version,
            "material_descriptors": material_descriptors,
            "material_descriptor_format": "fmodel_json",
            "vertex_count": len(lod.vertices),
            "face_count": len(lod.indices),
            "material_count": len(lod.materials),
            "bone_count": len(model.skeleton.bones) if model.skeleton is not None else 0,
            "morph_target_count": len(lod.morphs),
            "armature_object_name": armature_object.name if armature_object is not None else "",
        },
    )


def _apply_uvs(mesh_data: t.Any, uv_layers: list[list[tuple[float, float]]]) -> None:
    loops = [vertex for polygon in mesh_data.polygons for vertex in polygon.vertices]
    for index, uv_values in enumerate(uv_layers):
        if not uv_values:
            continue
        layer = mesh_data.uv_layers.new(name=f"UV{index}")
        flattened: list[float] = []
        for vertex_index in loops:
            uv = uv_values[vertex_index]
            flattened.extend((uv[0], uv[1]))
        layer.data.foreach_set("uv", flattened)


def _apply_vertex_colors(mesh_data: t.Any, color_layers: t.Iterable[t.Any]) -> None:
    loops = [vertex for polygon in mesh_data.polygons for vertex in polygon.vertices]
    for color_info in color_layers:
        try:
            color_layer = mesh_data.color_attributes.new(
                domain="CORNER",
                type="BYTE_COLOR",
                name=color_info.name,
            )
        except (AttributeError, RuntimeError):
            continue

        flattened: list[float] = []
        for vertex_index in loops:
            flattened.extend(color_info.colors[vertex_index])
        color_layer.data.foreach_set("color", flattened)


def _apply_material_slots(bpy: t.Any, mesh_data: t.Any, materials: t.Iterable[t.Any]) -> None:
    for material_index, material in enumerate(materials):
        mat = bpy.data.materials.get(material.material_name)
        if mat is None:
            mat = bpy.data.materials.new(name=material.material_name)
        mesh_data.materials.append(mat)

        start_face_index = material.first_index // 3
        end_face_index = min(start_face_index + material.num_faces, len(mesh_data.polygons))
        for face_index in range(start_face_index, end_face_index):
            mesh_data.polygons[face_index].material_index = material_index


def _build_material_descriptors(
    materials: t.Iterable[t.Any],
    uemodel_filepath: str,
    umodel_export_dir: str = "",
) -> list[dict[str, t.Any]]:
    from ..ueformat.material_resolution import resolve_material_descriptors  # pylint: disable=import-outside-toplevel

    return [
        descriptor.to_backend_dict()
        for descriptor in resolve_material_descriptors(materials, uemodel_filepath, umodel_export_dir)
    ]


def _apply_weights(mesh_object: t.Any, model: t.Any, lod: t.Any) -> None:
    if model.skeleton is None or not model.skeleton.bones:
        return

    for bone in model.skeleton.bones:
        if mesh_object.vertex_groups.get(bone.name) is None:
            mesh_object.vertex_groups.new(name=bone.name)

    for weight in lod.weights:
        if weight.bone_index < 0 or weight.bone_index >= len(model.skeleton.bones):
            continue
        bone_name = model.skeleton.bones[weight.bone_index].name
        vertex_group = mesh_object.vertex_groups[bone_name]
        vertex_group.add([weight.vertex_index], weight.weight, "ADD")


def _apply_morph_targets(mesh_object: t.Any, lod: t.Any) -> None:
    if not lod.morphs:
        return

    if not mesh_object.data.shape_keys:
        mesh_object.shape_key_add(name="Basis", from_mix=False)

    for morph in lod.morphs:
        key = mesh_object.shape_key_add(name=morph.name, from_mix=False)
        key.interpolation = "KEY_LINEAR"
        for delta in morph.deltas:
            coord = key.data[delta.vertex_index].co
            coord.x += delta.position[0]
            coord.y += delta.position[1]
            coord.z += delta.position[2]
        key.value = 0.0


def _create_armature(bpy: t.Any, mathutils: t.Any, context: MeshImportContext, model: t.Any, mesh_object: t.Any) -> t.Any:
    armature_data = bpy.data.armatures.new(name=model.name)
    armature_data.display_type = "STICK"
    armature_object = bpy.data.objects.new(f"{model.name}_Skeleton", armature_data)
    armature_object.show_in_front = True
    context.blender_context.collection.objects.link(armature_object)

    previous_active = bpy.context.view_layer.objects.active
    previous_mode = getattr(previous_active, "mode", "OBJECT") if previous_active is not None else "OBJECT"
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = armature_data.edit_bones
    bone_lookup = {}
    for bone in model.skeleton.bones:
        edit_bone = edit_bones.new(bone.name)
        head = mathutils.Vector(bone.position)
        edit_bone.head = head
        edit_bone.tail = head + mathutils.Vector((0.0, 0.04, 0.0))
        edit_bone["orig_loc"] = bone.position
        edit_bone["orig_quat"] = (bone.rotation[3], bone.rotation[0], bone.rotation[1], bone.rotation[2])
        edit_bone["post_quat"] = (bone.rotation[3], bone.rotation[0], bone.rotation[1], bone.rotation[2])
        bone_lookup[bone.name] = edit_bone
        if bone.parent_index >= 0 and bone.parent_index < len(model.skeleton.bones):
            parent_name = model.skeleton.bones[bone.parent_index].name
            parent_bone = bone_lookup.get(parent_name)
            if parent_bone is not None:
                edit_bone.parent = parent_bone
                edit_bone.use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    if previous_active is not None:
        try:
            bpy.context.view_layer.objects.active = previous_active
            if previous_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=previous_mode)
        except RuntimeError:
            bpy.ops.object.mode_set(mode="OBJECT")

    mesh_object.parent = armature_object
    modifier = mesh_object.modifiers.new(armature_object.name, type="ARMATURE")
    modifier.show_expanded = False
    modifier.use_vertex_groups = True
    modifier.object = armature_object
    return armature_object


_BACKENDS: dict[str, MeshImportBackend] = {}


def _normalize_backend_id(backend_id: str) -> str:
    normalized = backend_id.strip().upper()
    if normalized in {"PSK/PSKX", "PSKX"}:
        return "PSK"
    return normalized


def register_mesh_backend(backend: MeshImportBackend) -> None:
    _BACKENDS[_normalize_backend_id(backend.id)] = backend


def unregister_mesh_backend(backend_id: str) -> None:
    _BACKENDS.pop(_normalize_backend_id(backend_id), None)


def list_mesh_backends() -> list[MeshImportBackend]:
    return sorted(_BACKENDS.values(), key=lambda backend: (-backend.priority, backend.id))


def get_supported_mesh_extensions() -> tuple[str, ...]:
    extensions: list[str] = []
    for backend in list_mesh_backends():
        for ext in backend.supported_extensions:
            ext = ext.lower()
            if ext not in extensions:
                extensions.append(ext)
    return tuple(extensions)


def get_mesh_backend_for_file(
    filepath: str,
    context: MeshImportContext | None = None,
    preferred_backend: str = "AUTO",
) -> MeshImportBackend | None:
    ext = os.path.splitext(filepath)[1].lower()
    preferred_backend = _normalize_backend_id(preferred_backend or "AUTO")

    candidates = list_mesh_backends()
    if preferred_backend != "AUTO":
        backend = _BACKENDS.get(preferred_backend)
        candidates = [backend] if backend is not None else []

    for backend in candidates:
        if ext not in backend.supported_extensions:
            continue
        if backend.can_import(filepath, context):
            return backend
    return None


def get_default_mesh_backend() -> MeshImportBackend | None:
    backends = list_mesh_backends()
    return backends[0] if backends else None


def register_experimental_mesh_backends() -> None:
    register_mesh_backend(UModelMeshBackend())


def get_backend_for_path(
    filepath: str,
    context: MeshImportContext | None = None,
    preferred_backend: str = "AUTO",
) -> MeshImportBackend | None:
    return get_mesh_backend_for_file(filepath, context=context, preferred_backend=preferred_backend)


register_mesh_backend(PskMeshBackend())
register_mesh_backend(UModelMeshBackend())
