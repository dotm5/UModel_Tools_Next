"""This module implements a config-backed generic material profile."""

import typing as t
import dataclasses

import bpy
import lark

from .. import utils
from .. import material_rules


GAME_NAME = "Generic"
GAME_DESCRIPTION = "Provides basic support for any Unreal Engine game"

RULE_SET = material_rules.load_rule_set(material_rules.default_rule_path("generic"))


@dataclasses.dataclass
class MaterialContext:
    bsdf_node: t.Optional[bpy.types.ShaderNodeBsdfPrincipled | bpy.types.ShaderNodeBsdfDiffuse]
    desc_ast: lark.Tree
    use_pbr: bool
    blend_mode: str | None
    linked_maps: set[str] = dataclasses.field(default_factory=set)


_state_buffer: dict[bpy.types.Material, MaterialContext] = {}


def process_material(mat: bpy.types.Material, desc_ast: lark.Tree, use_pbr: bool):  # pylint: disable=unused-argument
    _state_buffer[mat] = MaterialContext(
        bsdf_node=None,
        desc_ast=desc_ast,
        use_pbr=use_pbr,
        blend_mode=_extract_blend_mode(desc_ast),
    )


def do_process_texture(tex_type: str, tex_short_name: str) -> bool:
    return _resolve_rule(tex_type, tex_short_name) is not None


def is_diffuse_tex_type(tex_type: str, tex_short_name: str) -> bool:
    rule = _resolve_rule(tex_type, tex_short_name)
    return rule.diffuse if rule is not None else False


def handle_material_texture_pbr(mat: bpy.types.Material,
                                tex_type: str,
                                tex_short_name: str,
                                img_node: bpy.types.ShaderNodeTexImage,
                                ao_mix_node: bpy.types.ShaderNodeMix,
                                bsdf_node: bpy.types.ShaderNodeBsdfPrincipled,
                                out_node: bpy.types.ShaderNodeOutputMaterial):
    mat_ctx = _state_buffer[mat]
    mat_ctx.bsdf_node = bsdf_node

    rule = _resolve_rule(tex_type, tex_short_name)
    if rule is None:
        return

    # do not connect the same texture purpose twice
    if rule.name in mat_ctx.linked_maps:
        return

    # remember that we processed a texture of that type
    mat_ctx.linked_maps.add(rule.name)
    _configure_image_color_space(img_node, rule)

    nodes = _create_rule_nodes(mat, rule)
    nodes.update({
        "image": img_node,
        "ao_mix": ao_mix_node,
        "bsdf": bsdf_node,
        "output": out_node,
    })

    for connection in rule.connections:
        if _should_skip_connection(mat_ctx, rule, connection):
            continue

        source_socket = _resolve_socket(nodes, connection.source, "output")
        target_socket = _resolve_socket(nodes, connection.target, "input")
        if source_socket is not None and target_socket is not None:
            mat.node_tree.links.new(source_socket, target_socket)

    if rule.diffuse:
        img_node.select = True
        mat.node_tree.nodes.active = img_node


def handle_material_texture_simple(mat: bpy.types.Material,
                                   tex_type: str,
                                   tex_short_name: str,
                                   img_node: bpy.types.ShaderNodeTexImage,
                                   bsdf_node: bpy.types.ShaderNodeBsdfDiffuse):
    _state_buffer[mat].bsdf_node = bsdf_node

    if not is_diffuse_tex_type(tex_type, tex_short_name):
        return

    mat.node_tree.links.new(img_node.outputs['Color'], bsdf_node.inputs['Color'])
    img_node.select = True
    mat.node_tree.nodes.active = img_node


def end_process_material(mat: bpy.types.Material):
    mat_ctx = _state_buffer[mat]

    if mat_ctx.use_pbr and mat_ctx.bsdf_node is not None:
        # set defaults
        utils.set_socket_value(utils.get_bsdf_input(mat_ctx.bsdf_node, 'Subsurface IOR'), 1.01)
        utils.set_socket_value(utils.get_bsdf_input(mat_ctx.bsdf_node, 'Specular'), 0.0)
        utils.set_socket_value(utils.get_bsdf_input(mat_ctx.bsdf_node, 'Roughness'), 0.0)
        utils.set_socket_value(utils.get_bsdf_input(mat_ctx.bsdf_node, 'Sheen Tint'), 0.0)
        utils.set_socket_value(utils.get_bsdf_input(mat_ctx.bsdf_node, 'Clearcoat Roughness'), 0.0)

    del _state_buffer[mat]


# Non-interface functions below

def _resolve_rule(tex_type: str, tex_short_name: str) -> material_rules.TextureRule | None:
    return RULE_SET.resolve(tex_type, tex_short_name)


def _create_rule_nodes(mat: bpy.types.Material, rule: material_rules.TextureRule) -> dict[str, bpy.types.Node]:
    return {
        node_spec.name: mat.node_tree.nodes.new(node_spec.node_type)
        for node_spec in rule.nodes
    }


def _should_skip_connection(mat_ctx: MaterialContext,
                            rule: material_rules.TextureRule,
                            connection: material_rules.ConnectionSpec) -> bool:
    if (
        rule.diffuse
        and connection.source == "image.Alpha"
        and connection.target == "bsdf.Alpha"
        and not _material_uses_texture_alpha(mat_ctx.blend_mode)
    ):
        return True

    return False


def _material_uses_texture_alpha(blend_mode: str | None) -> bool:
    if blend_mode == "BLEND_Opaque (0)":
        return False

    return True


def _extract_blend_mode(desc_ast: lark.Tree) -> str | None:
    for child in desc_ast.children:
        def_name, _, value = child.children
        if def_name != "BasePropertyOverrides" or value.data != "structured_block":
            continue

        for prop_override_entry in value.children:
            prop_name, _, prop_value = prop_override_entry.children
            if prop_name.value == "BlendMode":
                return prop_value.children[0].value.strip()

    return None


def _configure_image_color_space(img_node: bpy.types.ShaderNodeTexImage,
                                 rule: material_rules.TextureRule) -> None:
    if rule.diffuse or img_node.image is None:
        return

    try:
        img_node.image.colorspace_settings.name = "Non-Color"
    except (AttributeError, TypeError):
        pass


def _resolve_socket(nodes: dict[str, bpy.types.Node], path: str, direction: t.Literal["input", "output"]) -> t.Any:
    node_name, socket_name = _split_socket_path(path)
    node = nodes.get(node_name)
    if node is None:
        print(f"Warning: Material rule references unknown node {node_name!r}.")
        return None

    if node_name == "bsdf" and direction == "input":
        return utils.get_bsdf_input(node, socket_name)
    if node_name == "ao_mix":
        return _resolve_ao_mix_socket(node, socket_name, direction)
    if node.bl_idname == "ShaderNodeMixShader":
        return _resolve_mix_shader_socket(node, socket_name, direction)
    if node.bl_idname == "ShaderNodeAddShader":
        return _resolve_add_shader_socket(node, socket_name, direction)

    sockets = node.inputs if direction == "input" else node.outputs
    return sockets[socket_name]


def _split_socket_path(path: str) -> tuple[str, str]:
    node_name, socket_name = path.split(".", 1)
    return node_name.strip(), socket_name.strip()


def _resolve_ao_mix_socket(node: bpy.types.Node, socket_name: str, direction: t.Literal["input", "output"]) -> t.Any:
    if direction == "output":
        if socket_name == "Result":
            return node.outputs[2]
        return node.outputs[socket_name]

    match socket_name:
        case "Color1":
            return node.inputs[6]
        case "Color2":
            return node.inputs[7]
        case _:
            return node.inputs[socket_name]


def _resolve_mix_shader_socket(node: bpy.types.Node, socket_name: str, direction: t.Literal["input", "output"]) -> t.Any:
    if direction == "output":
        return node.outputs[0]

    match socket_name:
        case "Fac" | "Factor":
            return node.inputs[0]
        case "Shader":
            return node.inputs[1]
        case "Shader_001":
            return node.inputs[2]
        case _:
            return node.inputs[socket_name]


def _resolve_add_shader_socket(node: bpy.types.Node, socket_name: str, direction: t.Literal["input", "output"]) -> t.Any:
    if direction == "output":
        return node.outputs[0]

    match socket_name:
        case "Shader":
            return node.inputs[0]
        case "Shader_001":
            return node.inputs[1]
        case _:
            return node.inputs[socket_name]
