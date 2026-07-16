import typing as t
import os
import shutil

import bpy

from . import enums
from . import utils
from . import props_txt_parser
from . import game_profiles
from . import import_support
from . import fmodel_material_json
from . import material_node_layout
from .materials import rules as rule_module


MATERIAL_CACHE_VERSION = 9
MATERIAL_CACHE_VERSION_KEY = "umodel_tools_material_cache_version"

PLACEHOLDER_MATERIAL_UNRESOLVED = "unresolved"
PLACEHOLDER_MATERIAL_AMBIGUOUS = "ambiguous"

_PLACEHOLDER_PBR_COLORS = {
    PLACEHOLDER_MATERIAL_UNRESOLVED: (0.45, 0.45, 0.45, 1.0),
    PLACEHOLDER_MATERIAL_AMBIGUOUS: (1.0, 0.78, 0.18, 1.0),
}

_PLACEHOLDER_PBR_SUFFIXES = {
    PLACEHOLDER_MATERIAL_UNRESOLVED: "Unresolved_PBR",
    PLACEHOLDER_MATERIAL_AMBIGUOUS: "Ambiguous_PBR",
}


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
                             shader_hint: rule_module.MaterialShaderHint) -> None:
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


def _placeholder_pbr_status(status: str) -> str:
    return status if status in _PLACEHOLDER_PBR_COLORS else PLACEHOLDER_MATERIAL_UNRESOLVED


def _placeholder_pbr_name(material_name: str, status: str) -> str:
    status = _placeholder_pbr_status(status)
    suffix = _PLACEHOLDER_PBR_SUFFIXES[status]
    return utils.normalize_ue_name(f"{material_name}_{suffix}", fallback="Material_Placeholder")


def _create_placeholder_pbr_material(material_name: str, status: str) -> bpy.types.Material:
    status = _placeholder_pbr_status(status)
    color = _PLACEHOLDER_PBR_COLORS[status]
    new_mat = bpy.data.materials.new(_placeholder_pbr_name(material_name, status))
    new_mat[MATERIAL_CACHE_VERSION_KEY] = MATERIAL_CACHE_VERSION - 1
    new_mat.diffuse_color = color
    new_mat.use_nodes = True
    new_mat.node_tree.links.clear()
    new_mat.node_tree.nodes.clear()

    out = new_mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
    bsdf = new_mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    _set_node_input_default(bsdf, 'Base Color', color)
    _set_node_input_default(bsdf, 'Roughness', 0.5)
    _set_node_input_default(bsdf, 'Metallic', 0.0)
    new_mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    if material_node_layout.arrange_material_node_tree(new_mat.node_tree):
        new_mat[MATERIAL_CACHE_VERSION_KEY] = MATERIAL_CACHE_VERSION
    return new_mat


def _write_placeholder_pbr_material_to_library(
    material_name: str,
    material_path_local_no_ext: str,
    status: str,
    material_lib_path: str,
    db: import_support.AssetDB,
) -> None:
    new_mat = _create_placeholder_pbr_material(material_name, status)
    new_mat.asset_mark()
    new_mat.asset_data.catalog_id = db.uid_for_entry(material_path_local_no_ext)
    os.makedirs(os.path.dirname(material_lib_path), exist_ok=True)
    bpy.data.libraries.write(filepath=material_lib_path, datablocks={new_mat, }, fake_user=True)
    bpy.data.materials.remove(new_mat, do_unlink=True)


def _material_cache_is_current(material_lib_path: str) -> bool:
    return import_support.material_cache_is_current(
        material_lib_path,
        MATERIAL_CACHE_VERSION_KEY,
        MATERIAL_CACHE_VERSION,
    )


def _remove_loaded_material_library(material_lib_path: str) -> None:
    import_support.remove_loaded_material_library(material_lib_path)


def _remove_loaded_asset_library(asset_lib_path: str) -> None:
    import_support.remove_loaded_asset_library(asset_lib_path)


def _is_diffuse_texture_path(tex_path: str) -> bool:
    return import_support.is_diffuse_texture_path(tex_path)

class MaterialCacheMixin:
    """Creates texture and material cache libraries used by map asset caches."""

    def _import_image_to_library(self,
                                 tex_path: str,
                                 tex_lib_path: str,
                                 tex_umodel_path: str,
                                 db: import_support.AssetDB):
        """Import image texture to asset library from UModel output.

        :param tex_path: Path to texture in game format.````
        :param tex_lib_path: Path to texture in the library dir (absolute).
        :param tex_umodel_path: Path to texture in the UModel output dir (absolute).
        """
        # copy file to library dir
        os.makedirs(os.path.dirname(tex_lib_path), exist_ok=True)
        shutil.copyfile(tex_umodel_path, tex_lib_path)

        img = bpy.data.images.load(filepath=tex_lib_path)
        if _is_diffuse_texture_path(tex_path):
            img.alpha_mode = "CHANNEL_PACKED"
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
                                    db: import_support.AssetDB,
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
        self._import_material_description_to_library(
            material_name=material_name,
            material_path_local=material_path_local,
            material_path_local_no_ext=material_path_local_no_ext,
            desc_source=desc_ast,
            texture_infos=texture_infos,
            base_prop_overrides=base_prop_overrides or {},
            parent_reference=props_txt_parser.extract_parent_reference(desc_ast),
            scalar_parameters=props_txt_parser.extract_scalar_parameters(desc_ast),
            vector_parameters=props_txt_parser.extract_vector_parameters(desc_ast),
            db=db,
            umodel_export_dir=umodel_export_dir,
            asset_library_dir=asset_library_dir,
            game_profile_impl=game_profile_impl,
        )

    def _import_fmodel_json_material_to_library(self,
                                                material_name: str,
                                                material_path_local: str,
                                                db: import_support.AssetDB,
                                                umodel_export_dir: str,
                                                asset_library_dir: str,
                                                game_profile: str
                                                ) -> None:
        game_profile_impl = game_profiles.GAME_HANDLERS.get(game_profile)

        if game_profile_impl is None:
            raise NotImplementedError(f"Requested game profile {game_profile} is not implemented/available.")

        material_path_local_no_ext = os.path.splitext(material_path_local)[0]
        material_json = self._resolve_umodel_path(
            umodel_export_dir=umodel_export_dir,
            asset_path=material_path_local,
            extensions=('.json',),
        )
        if not material_json.found or material_json.path is None:
            self._last_missing_resolution = material_json
            raise FileNotFoundError(
                f"FModel material descriptor {material_path_local} was not found in the export path."
            )

        desc = fmodel_material_json.load_material_description(
            material_json.path,
            material_name=material_name,
            material_path_local=material_path_local,
        )
        self._import_material_description_to_library(
            material_name=material_name,
            material_path_local=material_path_local,
            material_path_local_no_ext=material_path_local_no_ext,
            desc_source=desc,
            texture_infos=desc.texture_infos,
            base_prop_overrides=desc.base_prop_overrides,
            parent_reference=desc.parent_reference,
            scalar_parameters=desc.scalar_parameters,
            vector_parameters=desc.vector_parameters,
            db=db,
            umodel_export_dir=umodel_export_dir,
            asset_library_dir=asset_library_dir,
            game_profile_impl=game_profile_impl,
        )

    def _import_material_description_to_library(self,
                                                material_name: str,
                                                material_path_local: str,
                                                material_path_local_no_ext: str,
                                                desc_source: t.Any,
                                                texture_infos: dict[str, str],
                                                base_prop_overrides: dict[str, str | float | bool],
                                                parent_reference: str | None,
                                                scalar_parameters: dict[str, float],
                                                vector_parameters: dict[str, props_txt_parser.Color],
                                                db: import_support.AssetDB,
                                                umodel_export_dir: str,
                                                asset_library_dir: str,
                                                game_profile_impl: game_profiles.GameHandler
                                                ) -> None:
        material_name = utils.normalize_ue_name(material_name, fallback="Material")
        new_mat = bpy.data.materials.new(utils.normalize_ue_name(material_name, fallback="Material"))
        new_mat[MATERIAL_CACHE_VERSION_KEY] = MATERIAL_CACHE_VERSION - 1
        new_mat.asset_mark()
        new_mat.asset_data.catalog_id = db.uid_for_entry(material_path_local_no_ext)
        new_mat.use_nodes = True
        new_mat.node_tree.links.clear()
        new_mat.node_tree.nodes.clear()

        if isinstance(desc_source, fmodel_material_json.MaterialDescription):
            utils.verbose_print(
                f"FModel JSON material: {material_name}, "
                f"textures={len(desc_source.texture_infos)}, "
                f"switches={list(desc_source.static_switch_parameters.keys())}, "
                f"overrides={list(desc_source.base_prop_overrides.keys())}"
            )

        rule_paths_override = getattr(self, "material_rule_paths_override", None)
        if rule_paths_override is not None and hasattr(game_profile_impl, "set_material_rule_path_override"):
            game_profile_impl.set_material_rule_path_override(rule_paths_override)

        out = new_mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
        shader_hint = None

        mesh_props = None
        try:
            game_profile_impl.process_material(mat=new_mat, desc_ast=desc_source, use_pbr=self.load_pbr_maps)

            if self.load_pbr_maps:
                special_blend_mode = None
                blend_mode = base_prop_overrides.get('BlendMode') if base_prop_overrides is not None else None
                shader_hint = rule_module.infer_shader_hint(
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
                ao_mix = None
                new_mat.node_tree.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

            for tex_type, tex_path_and_name in texture_infos.items():
                if shader_hint is not None:
                    continue

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
                               f"but it resolved as {tex_path_resolved.status}.")
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

                if (img := self._linked_libraries_search_cached(tex_lib_blend_path, bpy.types.Image)) is None:
                    # load datablock from the library
                    with utils.redirect_cstdout():
                        with bpy.data.libraries.load(filepath=tex_lib_blend_path, link=True) as (data_from, data_to):
                            # we assume there is exactly one texture we have just written there
                            data_to.images = [data_from.images[0]]

                        img = data_to.images[0]
                        self._remember_linked_library(tex_lib_blend_path, img)

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
        finally:
            if rule_paths_override is not None and hasattr(game_profile_impl, "set_material_rule_path_override"):
                game_profile_impl.set_material_rule_path_override(None)

        if material_node_layout.arrange_material_node_tree(new_mat.node_tree):
            new_mat[MATERIAL_CACHE_VERSION_KEY] = MATERIAL_CACHE_VERSION

        # new_mat.asset_generate_preview()

        material_lib_path = os.path.join(asset_library_dir, material_path_local_no_ext) + '.blend'
        os.makedirs(os.path.dirname(material_lib_path), exist_ok=True)
        bpy.data.libraries.write(filepath=material_lib_path, datablocks={new_mat, }, fake_user=True)
        bpy.data.materials.remove(new_mat, do_unlink=True)
