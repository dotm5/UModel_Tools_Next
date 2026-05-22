import typing as t
import io
import os
import shutil
import contextlib
import dataclasses

from io_import_scene_unreal_psa_psk_280 import pskimport  # pylint: disable=import-error
import bpy

from . import enums
from . import utils
from . import asset_db
from . import props_txt_parser
from . import game_profiles
from . import umodel_path_resolver
from . import localization
from . import missing_asset_report
from . import material_shader_hints


LINKED_ASSET_LIBRARY = "LINKED_ASSET_LIBRARY"
LOCAL_SINGLE_FILE = "LOCAL_SINGLE_FILE"
APPEND_AS_LOCAL = "APPEND_AS_LOCAL"

WARN_SKIP = "WARN_SKIP"
USE_PLACEHOLDER = "USE_PLACEHOLDER"
FAIL_IMPORT = "FAIL_IMPORT"


@dataclasses.dataclass
class ImportRuntimeStats:
    storage_mode: str = LINKED_ASSET_LIBRARY
    missing_mesh_count: int = 0
    missing_material_count: int = 0
    missing_texture_count: int = 0
    skipped_instances: int = 0
    imported_instance_count: int = 0
    linked_object_count: int = 0
    local_object_count: int = 0
    linked_material_count: int = 0
    local_material_count: int = 0

    def summary(self) -> str:
        return (
            f"storage_mode={self.storage_mode}, "
            f"linked_object_count={self.linked_object_count}, "
            f"local_object_count={self.local_object_count}, "
            f"local_material_count={self.local_material_count}, "
            f"linked_material_count={self.linked_material_count}, "
            f"missing_mesh_count={self.missing_mesh_count}, "
            f"missing_material_count={self.missing_material_count}, "
            f"missing_texture_count={self.missing_texture_count}, "
            f"skipped_instances={self.skipped_instances}, "
            f"imported_instance_count={self.imported_instance_count}"
        )


class AssetImportPolicyError(RuntimeError):
    """Raised when a user-selected missing-asset policy requires import cancellation."""


def _remove_unused_ao_mix(mat: bpy.types.Material,
                          ao_mix: bpy.types.ShaderNodeMix,
                          bsdf: bpy.types.ShaderNodeBsdfPrincipled) -> None:
    """Bypass the base-color AO multiply node when no AO texture was connected."""
    ao_input = ao_mix.inputs[7]
    if ao_input.is_linked:
        return

    base_color_input = utils.get_bsdf_input(bsdf, 'Base Color')
    color_input = ao_mix.inputs[6]
    result_output = ao_mix.outputs[2]
    color_links = list(color_input.links)
    result_links = list(result_output.links)

    if color_links:
        color_source = color_links[0].from_socket
        for link in result_links:
            target_socket = link.to_socket
            mat.node_tree.links.remove(link)
            mat.node_tree.links.new(color_source, target_socket)
    else:
        try:
            base_color_input.default_value = color_input.default_value
        except (AttributeError, TypeError):
            pass

    mat.node_tree.nodes.remove(ao_mix)


def _set_node_input_default(node: bpy.types.Node, socket_name: str, value: t.Any) -> None:
    socket = node.inputs.get(socket_name)
    if socket is None:
        return

    utils.set_socket_value(socket, value)


def _configure_dithered_alpha_surface(mat: bpy.types.Material) -> None:
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = 'DITHERED'
    if hasattr(mat, 'blend_method'):
        mat.blend_method = 'HASHED'
    if hasattr(mat, 'use_transparency_overlap'):
        mat.use_transparency_overlap = True
    if hasattr(mat, 'show_transparent_back'):
        mat.show_transparent_back = True
    if hasattr(mat, 'use_transparent_shadow'):
        mat.use_transparent_shadow = True


def _apply_glass_shader_hint(mat: bpy.types.Material,
                             out: bpy.types.ShaderNodeOutputMaterial,
                             bsdf: bpy.types.ShaderNodeBsdfPrincipled,
                             shader_hint: material_shader_hints.MaterialShaderHint) -> None:
    for link in list(out.inputs['Surface'].links):
        mat.node_tree.links.remove(link)

    mat.diffuse_color = shader_hint.color[:3] + (shader_hint.alpha,)
    _configure_dithered_alpha_surface(mat)

    glass = mat.node_tree.nodes.new('ShaderNodeBsdfGlass')
    _set_node_input_default(glass, 'Color', shader_hint.color)
    if shader_hint.roughness is not None:
        _set_node_input_default(glass, 'Roughness', shader_hint.roughness)

    if shader_hint.alpha < 1.0:
        transparent = mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
        mix_shader = mat.node_tree.nodes.new('ShaderNodeMixShader')
        mix_shader.inputs[0].default_value = 1.0 - shader_hint.alpha
        mat.node_tree.links.new(glass.outputs['BSDF'], mix_shader.inputs[1])
        mat.node_tree.links.new(transparent.outputs['BSDF'], mix_shader.inputs[2])
        mat.node_tree.links.new(mix_shader.outputs[0], out.inputs['Surface'])
    else:
        mat.node_tree.links.new(glass.outputs['BSDF'], out.inputs['Surface'])

    utils.set_socket_value(utils.get_bsdf_input(bsdf, 'Alpha'), shader_hint.alpha)


def _remove_default_principled_nodes(mat: bpy.types.Material,
                                    ao_mix: bpy.types.ShaderNodeMix,
                                    bsdf: bpy.types.ShaderNodeBsdfPrincipled) -> None:
    if ao_mix.name in mat.node_tree.nodes:
        mat.node_tree.nodes.remove(ao_mix)
    if bsdf.name in mat.node_tree.nodes:
        mat.node_tree.nodes.remove(bsdf)


class AssetImporter:
    """Implements functionality of asset import from UModel output.
       Intended to be inherited a bpy.types.Operator subclass.
    """

    load_pbr_maps: bpy.props.BoolProperty(
        name="Load PBR textures",
        description="Load normal maps, specular, roughness, etc into materials. Experimental",
        default=True
    )

    import_backface_culling: bpy.props.BoolProperty(
        name="Use backface culling",
        description="If this setting is checked, material settings for backface culling will be kept, "
                    "otherwise backface culling is always off",
        default=False
    )

    texture_format: bpy.props.EnumProperty(
        name="Texture format",
        description="Format of textures expected to be in the UModel export directory.",
        items=[
            ('.png', '.png', '', 0),
            ('.dds', '.dds', '', 1),
            ('.tga', '.tga', '', 2)
        ],
        default='.png'
    )

    _unrecognized_texture_types: set[str] = set()

    _has_warnings: bool = False
    _path_resolve_stats: umodel_path_resolver.UModelPathResolveStats = umodel_path_resolver.UModelPathResolveStats()
    _import_stats: ImportRuntimeStats = ImportRuntimeStats()
    _missing_warning_paths: set[tuple[str, str]] = set()
    _missing_warning_printed_count: int = 0
    _local_loaded_assets: dict[str, bpy.types.Object] = {}
    _missing_asset_reporter: missing_asset_report.MissingAssetReporter | None = None
    _missing_asset_context: dict[str, t.Any] = {}
    _last_missing_resolution: umodel_path_resolver.ResolvedUModelPath | None = None
    _last_import_report: missing_asset_report.ImportReport = missing_asset_report.ImportReport()

    def _reset_import_runtime_state(self) -> None:
        self._unrecognized_texture_types.clear()
        self._has_warnings = False
        self._path_resolve_stats = umodel_path_resolver.UModelPathResolveStats()
        self._import_stats = ImportRuntimeStats(storage_mode=getattr(self, "import_storage_mode", LINKED_ASSET_LIBRARY))
        self._missing_warning_paths = set()
        self._missing_warning_printed_count = 0
        self._local_loaded_assets = {}
        self._missing_asset_reporter = None
        self._missing_asset_context = {}
        self._last_missing_resolution = None
        self._last_import_report = missing_asset_report.ImportReport()

    def _op_message(self, msg_type: t.Literal['INFO'] | t.Literal['ERROR'] | t.Literal['WARNING'], msg: str):
        """Print operator message and return the associated status-code.

        :param msg_type: Type of message.
        :param msg: Message text.
        :raises NotImplementedError: Raise when an incorrect ``type`` is passed.
        :return: Blender operator error code.
        """
        self.report(type={msg_type, }, message=localization.t_report(msg))  # pylint: disable=no-member
        match msg_type:
            case 'INFO':
                return {'FINISHED'}
            case 'ERROR':
                return {'CANCELLED'}
            case 'WARNING':
                return {'FINISHED'}
            case _:
                raise NotImplementedError()

    def _warn_print(self, *args: t.Any) -> None:
        """Print a message and mark that an operation had warnings.
        :param args: Arguments to internal print() call.
        """
        self._has_warnings = True
        print(*args)

    def _warn_missing_asset(self, asset_kind: str, asset_path: str, message: str) -> None:
        key = (asset_kind, asset_path)
        if key in self._missing_warning_paths:
            self._has_warnings = True
            return

        self._missing_warning_paths.add(key)
        if utils.preferences.get_addon_preferences().verbose:
            self._warn_print(message)
            self._missing_warning_printed_count += 1
        else:
            self._has_warnings = True

    def _set_missing_asset_context(self, **kwargs: t.Any) -> None:
        self._missing_asset_context = kwargs

    def _record_missing_asset(
        self,
        resource_type: t.Literal["mesh", "material", "texture", "unknown"],
        json_asset_path: str,
        message: str,
        fallback_used: str,
        resolution: umodel_path_resolver.ResolvedUModelPath | None = None,
        material_name: str = "",
        texture_parameter_name: str = "",
        component_name: str = "",
    ) -> None:
        self._has_warnings = True
        reporter = self._missing_asset_reporter
        if reporter is None:
            self._warn_missing_asset(resource_type, json_asset_path, f"Warning: {message}")
            return

        resolution = resolution or self._last_missing_resolution
        context = self._missing_asset_context
        policy = self._missing_policy(resource_type) if resource_type in {"mesh", "material", "texture"} else ""
        severity = "error" if policy == FAIL_IMPORT else "warning"
        normalized_asset_path = (
            resolution.normalized_asset_path
            if resolution is not None and resolution.normalized_asset_path
            else umodel_path_resolver.normalize_unreal_asset_path(json_asset_path)
        )
        attempted_extensions = (
            resolution.attempted_extensions
            if resolution is not None and resolution.attempted_extensions
            else tuple()
        )
        expected_path = resolution.expected_path if resolution is not None else ""
        resolved_candidate_count = resolution.resolved_candidate_count if resolution is not None else 0
        resolution_status = resolution.status if resolution is not None else "missing_file"
        if resolution_status == "unresolved":
            resolution_status = "unresolved"

        reporter.add(missing_asset_report.MissingAssetRecord(
            resource_type=resource_type,
            severity=severity,
            policy=missing_asset_report.policy_label(policy, fallback_used),
            json_asset_path=json_asset_path,
            normalized_asset_path=normalized_asset_path,
            attempted_extensions=attempted_extensions,
            resolution_status=resolution_status,
            expected_path=expected_path,
            resolved_candidate_count=resolved_candidate_count,
            actor_name=str(context.get("actor_name", "")),
            actor_object_path=str(context.get("actor_object_path", "")),
            component_name=component_name or str(context.get("component_name", "")),
            component_object_path=str(context.get("component_object_path", "")),
            instance_index=str(context.get("instance_index", "")),
            material_name=material_name,
            texture_parameter_name=texture_parameter_name,
            fallback_used=fallback_used,
            message=message,
            path_inference_mode=getattr(self, "path_inference_mode", ""),
        ))

    def _missing_policy(self, asset_kind: t.Literal["mesh", "material", "texture"]) -> str:
        attr_name = f"missing_{asset_kind}_policy"
        default_policy = WARN_SKIP if asset_kind == "mesh" else USE_PLACEHOLDER
        if getattr(self, "validation_preset", "") == "STRICT":
            default_policy = FAIL_IMPORT
        return getattr(self, attr_name, default_policy)

    def _missing_policy_fails(self, asset_kind: t.Literal["mesh", "material", "texture"]) -> bool:
        return self._missing_policy(asset_kind) == FAIL_IMPORT

    def _print_unrecognized_textures(self) -> None:
        """Print all unrecognized texture map names found. Useful for adding support for new games.
        """
        if utils.preferences.get_addon_preferences().verbose:
            print("Unrecognized texture types found:")
            print(self._unrecognized_texture_types)
            self._unrecognized_texture_types.clear()

    def _get_path_inference_settings(self) -> umodel_path_resolver.UModelPathInferenceSettings:
        prefs = utils.preferences.get_addon_preferences()
        return umodel_path_resolver.UModelPathInferenceSettings(
            enable_umodel_path_inference=getattr(
                self, "enable_umodel_path_inference", getattr(prefs, "enable_umodel_path_inference", True)
            ),
            path_inference_mode=getattr(
                self, "path_inference_mode", getattr(prefs, "path_inference_mode", umodel_path_resolver.BASIC_DEFAULT)
            ),
            enable_suffix_index=getattr(self, "enable_suffix_index", getattr(prefs, "enable_suffix_index", True)),
        )

    def _resolve_umodel_path(self,
                             umodel_export_dir: str,
                             asset_path: str,
                             extensions: t.Sequence[str]) -> umodel_path_resolver.ResolvedUModelPath:
        resolved = umodel_path_resolver.resolve_umodel_export_asset_path(
            export_dir=umodel_export_dir,
            asset_path=asset_path,
            extensions=extensions,
            settings=self._get_path_inference_settings(),
            stats=self._path_resolve_stats,
        )

        for warning in resolved.warnings:
            self._warn_print(f"Warning: {warning}")

        if resolved.status in {"inferred", "suffix"} and resolved.relative_path is not None:
            exact_candidate = umodel_path_resolver.build_umodel_asset_path_candidates(
                asset_path=asset_path,
                extensions=extensions,
                settings=umodel_path_resolver.UModelPathInferenceSettings(
                    enable_umodel_path_inference=False,
                    path_inference_mode=umodel_path_resolver.STRICT_EXACT,
                ),
            )[0]
            utils.verbose_print(
                f"{localization.t_report('Resolved truncated UModel path')}:\n"
                f"  {exact_candidate}\n"
                f"  -> {resolved.relative_path}"
            )

        return resolved

    def _load_asset(self,
                    context: bpy.types.Context,
                    asset_dir: str,
                    asset_path: str,
                    umodel_export_dir: str,
                    game_profile: str,
                    load: bool = True,
                    db: t.Optional[asset_db.AssetDB] = None
                    ) -> bpy.types.Object | None:
        """Loads the asset from library dir, or adds it to library and loads it.

        :param context: Current Blender context.
        :param asset_dir: Asset library directory.
        :param asset_path: Asset path in game format.
        :param umodel_export_dir: UModel output directory.
        :param game_profile: Game profile to import.
        :param load: If False, the asset will be imported to the library, but no the current scene.
        :param db: Asset database to operate on. If given, no saving is performed, else the function handles
        everything by itself.
        :return: Object reference or None (if object was not found or failed loading due to filesystem errors).
        :raises NotImplementedError: Raised when requested game profile is not implemented or available.
        """
        asset_path_abs_no_ext = os.path.join(asset_dir, os.path.splitext(asset_path)[0])
        asset_path_abs = asset_path_abs_no_ext + '.blend'
        storage_mode = getattr(self, "import_storage_mode", LINKED_ASSET_LIBRARY)

        try:
            if os.path.isfile(asset_path_abs) and self._is_asset_cache_stale(
                asset_path_abs=asset_path_abs,
                asset_path=asset_path,
                umodel_export_dir=umodel_export_dir,
            ):
                os.remove(asset_path_abs)

            if not os.path.isfile(asset_path_abs):
                self._import_asset_to_library(context=context, asset_library_dir=asset_dir, asset_path=asset_path,
                                              umodel_export_dir=umodel_export_dir, db=db, game_profile=game_profile)

            if load:
                if storage_mode in {LOCAL_SINGLE_FILE, APPEND_AS_LOCAL}:
                    return self._load_asset_as_local(asset_path_abs)

                if (linked_data := utils.linked_libraries_search(asset_path_abs, bpy.types.Object)):
                    return linked_data

                with utils.redirect_cstdout():
                    with bpy.data.libraries.load(asset_path_abs, link=True) as (data_from, data_to):
                        data_to.objects = list(data_from.objects)
                        assert len(data_to.objects) == 1

                    return data_to.objects[0]

            return None

        except FileNotFoundError:
            return None

    def _is_asset_cache_stale(self, asset_path_abs: str, asset_path: str, umodel_export_dir: str) -> bool:
        source_paths = self._asset_cache_source_paths(
            asset_path=asset_path,
            umodel_export_dir=umodel_export_dir,
        )
        if not source_paths:
            return False

        cache_mtime = os.path.getmtime(asset_path_abs)
        stale_sources = [
            source_path for source_path in source_paths
            if os.path.isfile(source_path) and os.path.getmtime(source_path) > cache_mtime
        ]
        if not stale_sources:
            return False

        utils.verbose_print(
            f"Rebuilding stale asset cache {asset_path_abs}; newer source file: {stale_sources[0]}"
        )
        return True

    def _asset_cache_source_paths(self, asset_path: str, umodel_export_dir: str) -> list[str]:
        source_paths: list[str] = []
        asset_path_local_noext = os.path.splitext(asset_path)[0]

        mesh_resolved = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=('.pskx', '.psk'),
        )
        if mesh_resolved.found and mesh_resolved.path is not None:
            source_paths.append(mesh_resolved.path)

        mesh_props = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=('.props.txt',),
        )
        if not mesh_props.found or mesh_props.path is None:
            return source_paths

        source_paths.append(mesh_props.path)
        try:
            _, material_descriptor_paths = props_txt_parser.parse_props_txt(mesh_props.path, mode='MESH')
        except OSError:
            return source_paths

        for mat_desc_path in material_descriptor_paths:
            material_path_local_no_ext, _material_name = os.path.splitext(mat_desc_path)
            material_path_local_no_ext = os.path.normpath(material_path_local_no_ext)
            if material_path_local_no_ext.startswith(os.sep):
                material_path_local_no_ext = material_path_local_no_ext[1:]

            material_props = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=material_path_local_no_ext + '.props.txt',
                extensions=('.props.txt',),
            )
            if material_props.found and material_props.path is not None:
                source_paths.append(material_props.path)

        return source_paths

    def _load_asset_as_local(self, asset_path_abs: str) -> bpy.types.Object:
        if asset_path_abs in self._local_loaded_assets:
            return self._local_loaded_assets[asset_path_abs]

        with utils.redirect_cstdout():
            with bpy.data.libraries.load(asset_path_abs, link=False) as (data_from, data_to):
                data_to.objects = list(data_from.objects)
                assert len(data_to.objects) == 1

        obj = self._make_object_editable_local(data_to.objects[0])
        self._local_loaded_assets[asset_path_abs] = obj
        return obj

    def _make_object_editable_local(self, obj: bpy.types.Object) -> bpy.types.Object:
        if obj.library is not None:
            obj = obj.copy()

        if obj.data is not None and getattr(obj.data, "library", None) is not None:
            obj.data = obj.data.copy()

        if obj.type == "MESH" and obj.data is not None:
            for idx, mat in enumerate(obj.data.materials):
                if mat is None:
                    continue

                local_mat = mat.copy() if mat.library is not None else mat
                self._localize_material_images(local_mat)
                obj.data.materials[idx] = local_mat

        return obj

    @staticmethod
    def _localize_material_images(mat: bpy.types.Material) -> None:
        if mat.node_tree is None:
            return

        for node in mat.node_tree.nodes:
            image = getattr(node, "image", None)
            if image is not None and image.library is not None:
                node.image = image.copy()

    def _import_image_to_library(self,
                                 tex_path: str,
                                 tex_lib_path: str,
                                 tex_umodel_path: str,
                                 db: asset_db.AssetDB):
        """Import image texture to asset library from UModel output.

        :param tex_path: Path to texture in game format.````
        :param tex_lib_path: Path to texture in the library dir (absolute).
        :param tex_umodel_path: Path to texture in the UModel output dir (absolute).
        """
        # copy file to library dir
        os.makedirs(os.path.dirname(tex_lib_path), exist_ok=True)
        shutil.copyfile(tex_umodel_path, tex_lib_path)

        img = bpy.data.images.load(filepath=tex_lib_path)
        img.asset_mark()
        img.asset_data.catalog_id = db.uid_for_entry(os.path.dirname(tex_path))
        # img.asset_generate_preview()

        tex_lib_blend_path = os.path.splitext(tex_lib_path)[0] + '.blend'

        # write texture library
        bpy.data.libraries.write(tex_lib_blend_path, {img, }, fake_user=True, compress=True)

        # remove original datablock
        bpy.data.images.remove(img, do_unlink=True)

    def _import_material_to_library(self,
                                    material_name: str,
                                    material_path_local: str,
                                    db: asset_db.AssetDB,
                                    umodel_export_dir: str,
                                    asset_library_dir: str,
                                    game_profile: str
                                    ) -> None:
        """Import material to asset library from UModel output.

        :param material_name: Short name of material.
        :param material_path_local: Path to material properties (.props.txt) in game format.
        :param db: Blender AssetDB.
        :param umodel_export_dir: UModel export directory.
        :param asset_library_dir: Asset library directory.
        :param game_profile: Game profile to use.
        :raises RuntimeError: Raised when material properties (.props.txt) file was not found or failed to open.
        :raises NotImplementedError: Raised when requested game profile is not implemented or available.
        """
        game_profile_impl = game_profiles.GAME_HANDLERS.get(game_profile)

        if game_profile_impl is None:
            raise NotImplementedError(f"Requested game profile {game_profile} is not implemented/available.")

        material_path_local_no_ext = os.path.splitext(os.path.splitext(material_path_local)[0])[0]  # remove .props.txt

        # load texture infos, may throw OSError if file is not found.
        # pylint: disable=unpacking-non-sequence
        material_props = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=material_path_local,
            extensions=('.props.txt',),
        )
        if not material_props.found or material_props.path is None:
            self._last_missing_resolution = material_props
            raise FileNotFoundError(
                f"Material descriptor {material_path_local} was not found in the UModel export path."
            )

        desc_ast, texture_infos, base_prop_overrides = props_txt_parser.parse_props_txt(material_props.path,
                                                                                        mode='MATERIAL')
        parent_reference = props_txt_parser.extract_parent_reference(desc_ast)
        scalar_parameters = props_txt_parser.extract_scalar_parameters(desc_ast)
        vector_parameters = props_txt_parser.extract_vector_parameters(desc_ast)
        material_name = utils.normalize_ue_name(material_name, fallback="Material")
        new_mat = bpy.data.materials.new(utils.normalize_ue_name(material_name, fallback="Material"))
        new_mat.asset_mark()
        new_mat.asset_data.catalog_id = db.uid_for_entry(material_path_local_no_ext)
        new_mat.use_nodes = True
        new_mat.node_tree.links.clear()
        new_mat.node_tree.nodes.clear()
        game_profile_impl.process_material(mat=new_mat, desc_ast=desc_ast, use_pbr=self.load_pbr_maps)

        out = new_mat.node_tree.nodes.new('ShaderNodeOutputMaterial')

        if self.load_pbr_maps:
            special_blend_mode = None
            blend_mode = base_prop_overrides.get('BlendMode') if base_prop_overrides is not None else None
            shader_hint = material_shader_hints.infer_shader_hint(
                material_name=material_name,
                material_path_local=material_path_local,
                parent_reference=parent_reference,
                scalar_parameters=scalar_parameters,
                vector_parameters=vector_parameters,
                blend_mode=blend_mode,
            )

            # set various material parameters
            if base_prop_overrides is not None:

                if (blend_mode := base_prop_overrides.get('BlendMode')) is not None:
                    match blend_mode:
                        case 'BLEND_Opaque (0)':
                            pass
                        case 'BLEND_Masked (1)':
                            new_mat.blend_method = 'CLIP'
                        case 'BLEND_Translucent (2)':
                            new_mat.blend_method = 'BLEND'
                        case 'BLEND_Additive (3)':
                            special_blend_mode = enums.SpecialBlendingMode.Add
                            new_mat.blend_method = 'BLEND'
                        case 'BLEND_Modulate (4)':
                            special_blend_mode = enums.SpecialBlendingMode.Mod
                            new_mat.blend_method = 'BLEND'
                        case _:
                            self._warn_print(f"Warning: Unknown blending mode \'{blend_mode}\' found on importing "
                                             f"material \"{material_name}\".")

                if self.import_backface_culling and (two_sided := base_prop_overrides.get('TwoSided')) is not None:
                    new_mat.use_backface_culling = not two_sided

                if (alpha_threshold := base_prop_overrides.get('OpacityMaskClipValue')) is not None:
                    new_mat.alpha_threshold = alpha_threshold

            elif self.import_backface_culling:
                new_mat.use_backface_culling = True

            # create basic shader nodes and set their default values
            bsdf = new_mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')

            ao_mix = new_mat.node_tree.nodes.new('ShaderNodeMix')
            ao_mix.data_type = 'RGBA'
            ao_mix.blend_type = 'MULTIPLY'
            ao_mix.inputs[6].default_value = (1, 1, 1, 1)
            ao_mix.inputs[7].default_value = (1, 1, 1, 1)
            new_mat.node_tree.links.new(ao_mix.outputs[2], utils.get_bsdf_input(bsdf, 'Base Color'))

            # in order to simulate some blending modes special node logic is required
            match special_blend_mode:
                case None:
                    new_mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
                case enums.SpecialBlendingMode.Add:
                    transparent_bsdf = new_mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
                    add_shader = new_mat.node_tree.nodes.new('ShaderNodeAddShader')

                    new_mat.node_tree.links.new(bsdf.outputs['BSDF'], add_shader.inputs[0])
                    new_mat.node_tree.links.new(transparent_bsdf.outputs['BSDF'], add_shader.inputs[1])
                    new_mat.node_tree.links.new(add_shader.outputs[0], out.inputs['Surface'])

                case enums.SpecialBlendingMode.Mod:
                    shader_to_rgb = new_mat.node_tree.nodes.new('ShaderNodeShaderToRGB')
                    transparent_bsdf = new_mat.node_tree.nodes.new('ShaderNodeBsdfTransparent')
                    new_mat.node_tree.links.new(bsdf.outputs['BSDF'], shader_to_rgb.inputs[0])
                    new_mat.node_tree.links.new(shader_to_rgb.outputs['Color'], transparent_bsdf.inputs['Color'])
                    new_mat.node_tree.links.new(transparent_bsdf.outputs['BSDF'], out.inputs['Surface'])

            if shader_hint is not None and shader_hint.shader == "glass":
                _apply_glass_shader_hint(new_mat, out, bsdf, shader_hint)
        else:
            bsdf = new_mat.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
            new_mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

        for tex_type, tex_path_and_name in texture_infos.items():
            tex_path_no_ext, tex_short_name = os.path.splitext(tex_path_and_name)

            # skip non-diffuse textures if we do not import PBR
            if not self.load_pbr_maps and not game_profile_impl.is_diffuse_tex_type(tex_type, tex_short_name):
                continue

            # skip the texture if we don't know what to do with it
            if not game_profile_impl.do_process_texture(tex_type, tex_short_name):
                self._unrecognized_texture_types.add(tex_type)
                continue

            # normalize path from config
            tex_path_no_ext = os.path.normpath(tex_path_no_ext)

            # remove leading separator
            tex_path_no_ext = tex_path_no_ext[1:] if tex_path_no_ext.startswith(os.sep) else tex_path_no_ext

            tex_path = tex_path_no_ext + self.texture_format
            tex_path_resolved = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=tex_path,
                extensions=(self.texture_format,),
            )

            tex_lib_path = os.path.join(asset_library_dir, tex_path)
            tex_lib_blend_path = os.path.splitext(tex_lib_path)[0] + '.blend'

            # check if texture is not already in the library
            if not os.path.isfile(tex_lib_blend_path):
                if tex_path_resolved.found and tex_path_resolved.path is not None:
                    self._import_image_to_library(tex_path=tex_path,
                                                  tex_lib_path=tex_lib_path,
                                                  tex_umodel_path=tex_path_resolved.path,
                                                  db=db)
                else:
                    self._import_stats.missing_texture_count += 1
                    msg = (f"Warning: Material \"{material_name}\" referenced texture \"{tex_path}\", "
                           "but it does not exist in the UModel export path.")
                    self._record_missing_asset(
                        resource_type="texture",
                        json_asset_path=tex_path,
                        message=msg,
                        fallback_used="placeholder_color",
                        resolution=tex_path_resolved,
                        material_name=material_name,
                        texture_parameter_name=tex_type,
                        component_name=tex_type,
                    )
                    if self._missing_policy_fails("texture"):
                        raise AssetImportPolicyError(msg)
                    continue

            if (img := utils.linked_libraries_search(tex_lib_blend_path, bpy.types.Image)) is None:
                # load datablock from the library
                with utils.redirect_cstdout():
                    with bpy.data.libraries.load(filepath=tex_lib_blend_path, link=True) as (data_from, data_to):
                        # we assume there is exactly one texture we have just written there
                        data_to.images = [data_from.images[0]]

                    img = data_to.images[0]

            img_node = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            img_node.image = img

            if self.load_pbr_maps:
                game_profile_impl.handle_material_texture_pbr(mat=new_mat,
                                                              tex_type=tex_type,
                                                              tex_short_name=tex_short_name,
                                                              img_node=img_node,
                                                              ao_mix_node=ao_mix,
                                                              bsdf_node=bsdf,
                                                              out_node=out)
            # just simply connect the diffuse map to the shader node, if we do not go the PBR route
            else:
                game_profile_impl.handle_material_texture_simple(mat=new_mat,
                                                                 tex_type=tex_type,
                                                                 tex_short_name=tex_short_name,
                                                                 img_node=img_node,
                                                                 bsdf_node=bsdf)

        game_profile_impl.end_process_material(new_mat)
        if self.load_pbr_maps:
            if shader_hint is not None and shader_hint.shader == "glass":
                _remove_default_principled_nodes(new_mat, ao_mix, bsdf)
            else:
                _remove_unused_ao_mix(new_mat, ao_mix, bsdf)

        # new_mat.asset_generate_preview()

        material_lib_path = os.path.join(asset_library_dir, material_path_local_no_ext) + '.blend'
        os.makedirs(os.path.dirname(material_lib_path), exist_ok=True)
        bpy.data.libraries.write(filepath=material_lib_path, datablocks={new_mat, }, fake_user=True)
        bpy.data.materials.remove(new_mat, do_unlink=True)

    def _import_asset_to_library(self,
                                 context: bpy.types.Context,
                                 asset_library_dir: str,
                                 asset_path: str,
                                 umodel_export_dir: str,
                                 game_profile: str,
                                 db: t.Optional[asset_db.AssetDB] = None
                                 ) -> None:
        """Import asset (mesh) to an assset library from UModel output.

        :param context: Current Blender context.
        :param asset_library_dir: Directory to store the asset, and its dependencies in.
        :param asset_path: Path to the asset in game format.
        :param umodel_export_dir: UModel output directory to source .psk files from.
        :param game_profile: Game profile to import.
        :param db: Asset database to operate on. If given, no saving is performed, else the function handles
        everything by itself.
        :raises OSError: Raised when an asset was not found in the UModel output dir or failed opening.
        :raises FileNotFounderror: Raised when an asset was not found in the directory.
        :raises RuntimeError: Raised when an asset failed importing due to unknown .psk/.pskx importer issue.
        :raises NotImplementedError: Raised when requested game profile is not implemented or available.
        """

        has_external_db = db is not None
        if db is None:
            db = asset_db.AssetDB(asset_library_dir)

        asset_local_dir = os.path.dirname(asset_path)
        catalog_uid = db.uid_for_entry(asset_local_dir) if asset_local_dir else None
        asset_absolute_dir = os.path.join(asset_library_dir, asset_local_dir)
        asset_path_local_noext = os.path.splitext(asset_path)[0]

        os.makedirs(asset_absolute_dir, exist_ok=True)

        asset_psk_path_noext = os.path.join(umodel_export_dir, asset_path_local_noext)
        psk_resolved = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=asset_path_local_noext,
            extensions=('.pskx', '.psk'),
        )

        found_path: str | None = None
        animated = False

        if psk_resolved.found and psk_resolved.path is not None:
            if psk_resolved.path.endswith('.pskx'):
                found_path = psk_resolved.path
            elif psk_resolved.path.endswith('.psk'):
                found_path = psk_resolved.path
                animated = True

        if found_path is None:
            lod0_base_path = asset_psk_path_noext + '_LOD0'
            lod0_resolved = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=lod0_base_path,
                extensions=('.pskx', '.psk'),
            )
            if lod0_resolved.found and lod0_resolved.path is not None:
                found_path = lod0_resolved.path
                animated = found_path.endswith('.psk')
                utils.verbose_print(f"Info: Exact file not found, using LOD0 fallback: \"{found_path}\"")

        if found_path is None:
            self._last_missing_resolution = psk_resolved
            raise FileNotFoundError(f"Error: Failed importing asset: {asset_psk_path_noext} was not found "
                                    "(.psk/.pskx, also tried _LOD0 suffix).")

        utils.verbose_print(f"Importing \"{found_path}\"")

        with contextlib.redirect_stdout(io.StringIO()):
            if not pskimport(filepath=found_path,
                             context=context,
                             bImportbone=False):
                raise RuntimeError(f"Error: Failed importing asset {found_path} due to unknown reason.")

        obj = context.object
        asset_psk_path_noext = os.path.splitext(found_path)[0]
        if asset_psk_path_noext.endswith('_LOD0'):
            asset_psk_path_noext = asset_psk_path_noext[:-5]

        # mark object as asset
        obj.asset_mark()
        obj.asset_data.catalog_id = catalog_uid

        # handle materials
        new_materials = []

        # - read material descriptor file and identify associated materials
        try:
            # pylint: disable=unpacking-non-sequence
            mesh_props = self._resolve_umodel_path(
                umodel_export_dir=umodel_export_dir,
                asset_path=asset_path_local_noext,
                extensions=('.props.txt',),
            )
            if not mesh_props.found or mesh_props.path is None:
                raise OSError()
            _, mat_descriptors_paths = props_txt_parser.parse_props_txt(mesh_props.path,
                                                                        mode='MESH')
        except OSError as exc:
            self._import_stats.missing_material_count += 1
            msg = (f"Warning: Loading material descriptor {asset_psk_path_noext + '.props.txt'} failed. "
                   "Materials will not be avaialble for the imported object.")
            self._record_missing_asset(
                resource_type="material",
                json_asset_path=asset_path_local_noext + '.props.txt',
                message=msg,
                fallback_used="placeholder_material",
                resolution=mesh_props,
                component_name="StaticMesh material descriptor",
            )
            if self._missing_policy_fails("material"):
                raise AssetImportPolicyError(msg) from exc
        else:
            # attempt to obtain materials manually if descriptor is not available
            mat_desc_order_map = {mat.name: None for mat in obj.data.materials}

            if animated and not mat_descriptors_paths:
                if os.path.isdir(mat_dir := os.path.join(os.path.dirname(found_path), 'Materials')):
                    for root, _, files in os.walk(mat_dir):
                        for file in files:
                            if not file.endswith('.props.txt'):
                                continue

                            file_abs = os.path.splitext(os.path.splitext(os.path.join(root, file))[0])[0]
                            mat_name = os.path.basename(file_abs)

                            if mat_name not in mat_desc_order_map:
                                self._warn_print(f"Warning: Found extra material {mat_name} in the Materials dir. "
                                                 "It won't be imported.")
                                continue

                            mat_desc_order_map[mat_name] = f"{os.path.relpath(file_abs, umodel_export_dir)}.{mat_name}"

                    if any(mat_desc is None for mat_desc in mat_desc_order_map.values()):
                        print(f"Warning: Material count mismatch for asset \"{obj.name}\".")
                        mesh = obj.data

                        bpy.data.objects.remove(obj, do_unlink=True)
                        bpy.data.meshes.remove(mesh, do_unlink=True)

                        old_materials = list(mesh.materials)

                        # perform cleanup before raising
                        for mat in old_materials:
                            try:
                                bpy.data.materials.remove(mat, do_unlink=True)
                            except ReferenceError:  # TODO: figure out why?
                                pass

                        raise FileNotFoundError()

                    mat_descriptors_paths = list(mat_desc_order_map.values())

            # replace materials
            old_materials = list(obj.data.materials)

            # initialize each material and populate it with data
            for mat_desc_path in mat_descriptors_paths:
                material_path_local_no_ext, material_name = os.path.splitext(mat_desc_path)
                material_name = material_name[1:]  # removing the .

                # normalize path from config
                material_path_local_no_ext = os.path.normpath(material_path_local_no_ext)

                # remove leading separator
                material_path_local_no_ext = material_path_local_no_ext[1:] \
                    if material_path_local_no_ext.startswith(os.sep) else material_path_local_no_ext

                material_path_local = material_path_local_no_ext + '.props.txt'
                material_lib_path = os.path.join(asset_library_dir, material_path_local_no_ext) + '.blend'

                try:
                    # add material to asset library if does not exist
                    if not os.path.isfile(material_lib_path):
                        self._import_material_to_library(material_name=material_name,
                                                         material_path_local=material_path_local,
                                                         db=db,
                                                         umodel_export_dir=umodel_export_dir,
                                                         asset_library_dir=asset_library_dir,
                                                         game_profile=game_profile)

                    if (new_mat := utils.linked_libraries_search(material_lib_path, bpy.types.Material)) is None:
                        # load material from the library
                        with utils.redirect_cstdout():
                            with bpy.data.libraries.load(filepath=material_lib_path, link=True) as (data_from, data_to):
                                # we presume there is exactly one material in the library, no validation performed
                                data_to.materials = [data_from.materials[0]]

                            new_mat = data_to.materials[0]

                except FileNotFoundError as e:
                    self._import_stats.missing_material_count += 1
                    msg = f"Warning: Material \"{material_name}\" failed to load, placeholder used instead. ({e})."
                    self._record_missing_asset(
                        resource_type="material",
                        json_asset_path=material_path_local,
                        message=msg,
                        fallback_used="placeholder_material",
                        resolution=self._last_missing_resolution,
                        material_name=material_name,
                        component_name="Material slot",
                    )
                    if self._missing_policy_fails("material"):
                        raise AssetImportPolicyError(
                            f"Missing material \"{material_name}\" while importing \"{asset_path}\"."
                        ) from e
                    new_mat = bpy.data.materials.new(
                        utils.normalize_ue_name(f"{material_name}_Placeholder", fallback="Material_Placeholder")
                    )

                except OSError as exc:
                    self._import_stats.missing_material_count += 1
                    msg = f"Warning: Material \"{material_name}\" failed to load, placeholder used instead."
                    self._record_missing_asset(
                        resource_type="material",
                        json_asset_path=material_path_local,
                        message=msg,
                        fallback_used="placeholder_material",
                        material_name=material_name,
                        component_name="Material slot",
                    )
                    if self._missing_policy_fails("material"):
                        raise AssetImportPolicyError(
                            f"Missing material \"{material_name}\" while importing \"{asset_path}\"."
                        ) from exc
                    new_mat = bpy.data.materials.new(
                        utils.normalize_ue_name(f"{material_name}_Placeholder", fallback="Material_Placeholder")
                    )

                new_materials.append((new_mat, material_name))

            for mat, mat_name in new_materials:
                if mat_name in obj.data.materials:
                    obj.data.materials[obj.data.materials.find(mat_name)] = mat
                else:
                    obj.data.materials.append(mat)

            # remove original materials
            for mat in old_materials:
                try:
                    bpy.data.materials.remove(mat, do_unlink=True)
                except ReferenceError:  # TODO: figure out why?
                    pass

        # obj.asset_generate_preview()

        asset_abs_lib_path = os.path.join(asset_library_dir, asset_path_local_noext) + '.blend'
        os.makedirs(os.path.dirname(asset_abs_lib_path), exist_ok=True)
        bpy.data.libraries.write(asset_abs_lib_path, {obj, }, fake_user=True)

        # cleanup
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh, do_unlink=True)

        for mat, _ in new_materials:
            try:
                bpy.data.materials.remove(mat, do_unlink=True)
            except ReferenceError:
                pass

        if not has_external_db:
            db.save_db()
