"""This module implements a config-backed generic material profile."""

from __future__ import annotations

import typing as t
import dataclasses
import os

import bpy

from .. import utils
from .. import props_txt_parser
from ..materials import rules as rule_module


GAME_NAME = "Generic"
GAME_DESCRIPTION = "Provides basic support for any Unreal Engine game"

_RULE_SET_CACHE_KEY: tuple[str, ...] | None = None
_RULE_SET_CACHE: rule_module.MaterialRuleSet | None = None
_RULE_PATH_OVERRIDE: tuple[str, ...] | None = None


@dataclasses.dataclass
class MaterialContext:
    bsdf_node: t.Optional[bpy.types.ShaderNodeBsdfPrincipled | bpy.types.ShaderNodeBsdfDiffuse]
    desc_ast: t.Any
    use_pbr: bool
    blend_mode: str | None
    scalar_parameters: dict[str, float]
    vector_parameters: dict[str, props_txt_parser.Color]
    static_switch_parameters: dict[str, bool]
    shading_model: str | None = None
    linked_maps: set[str] = dataclasses.field(default_factory=set)


_state_buffer: dict[bpy.types.Material, MaterialContext] = {}


def process_material(mat: bpy.types.Material, desc_ast: t.Any, use_pbr: bool):  # pylint: disable=unused-argument
    if hasattr(desc_ast, "base_prop_overrides"):
        blend_mode = getattr(desc_ast, "blend_mode", None)
        shading_model = _extract_description_shading_model(desc_ast)
        scalar_parameters = getattr(desc_ast, "scalar_parameters", {})
        vector_parameters = getattr(desc_ast, "vector_parameters", {})
        static_switch_parameters = getattr(desc_ast, "static_switch_parameters", {})
    else:
        blend_mode = _extract_blend_mode(desc_ast)
        shading_model = _extract_shading_model(desc_ast)
        scalar_parameters = props_txt_parser.extract_scalar_parameters(desc_ast)
        vector_parameters = props_txt_parser.extract_vector_parameters(desc_ast)
        static_switch_parameters = props_txt_parser.extract_static_switch_parameters(desc_ast)

    _state_buffer[mat] = MaterialContext(
        bsdf_node=None,
        desc_ast=desc_ast,
        use_pbr=use_pbr,
        blend_mode=blend_mode,
        scalar_parameters=scalar_parameters,
        vector_parameters=vector_parameters,
        static_switch_parameters=static_switch_parameters,
        shading_model=shading_model,
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

    if _should_skip_rule(mat_ctx, rule):
        mat.node_tree.nodes.remove(img_node)
        return

    # do not connect the same texture purpose twice
    if rule.name in mat_ctx.linked_maps:
        mat.node_tree.nodes.remove(img_node)
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
            _treat_diffuse_alpha_as_data(img_node)
            _route_packed_diffuse_alpha(mat, mat_ctx, img_node)
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
        _link_toon_normal_fallback(mat, mat_ctx)

    del _state_buffer[mat]


# Non-interface functions below

def _resolve_rule(tex_type: str, tex_short_name: str) -> rule_module.TextureRule | None:
    return _active_rule_set().resolve(tex_type, tex_short_name)


def _active_rule_set() -> rule_module.MaterialRuleSet:
    global _RULE_SET_CACHE_KEY, _RULE_SET_CACHE  # pylint: disable=global-statement

    rule_paths = _active_rule_paths()
    cache_key = tuple(
        f"{path}:{os.path.getmtime(path) if os.path.isfile(path) else 'missing'}"
        for path in rule_paths
    )
    if _RULE_SET_CACHE is not None and cache_key == _RULE_SET_CACHE_KEY:
        return _RULE_SET_CACHE

    _RULE_SET_CACHE = rule_module.load_rule_sets(rule_paths)
    _RULE_SET_CACHE_KEY = cache_key
    return _RULE_SET_CACHE


def _active_rule_paths() -> tuple[str, ...]:
    if _RULE_PATH_OVERRIDE is not None:
        return _RULE_PATH_OVERRIDE

    try:
        prefs = utils.preferences.get_addon_preferences()
        return tuple(prefs.get_active_material_rule_dataset_paths())
    except Exception:  # pragma: no cover - Blender preferences may be unavailable in isolated probes.
        return (rule_module.default_rule_path("generic"),)


def set_material_rule_path_override(rule_paths: t.Sequence[str] | None) -> None:
    global _RULE_PATH_OVERRIDE, _RULE_SET_CACHE_KEY, _RULE_SET_CACHE  # pylint: disable=global-statement
    _RULE_PATH_OVERRIDE = tuple(rule_paths) if rule_paths is not None else None
    _RULE_SET_CACHE_KEY = None
    _RULE_SET_CACHE = None


def _create_rule_nodes(mat: bpy.types.Material, rule: rule_module.TextureRule) -> dict[str, bpy.types.Node]:
    nodes = {
        node_spec.name: mat.node_tree.nodes.new(node_spec.node_type)
        for node_spec in rule.nodes
    }
    nodes.update({
        group_name: _create_rule_node_group(mat, group_name)
        for group_name in rule.node_groups
    })
    return nodes


def _create_rule_node_group(mat: bpy.types.Material, group_name: str) -> bpy.types.Node:
    if group_name == "directx_normal_to_blender":
        group = _get_directx_normal_to_blender_group()
    elif group_name == "matcap_emission_strength":
        group = _get_matcap_emission_strength_group()
    elif group_name == "toon_coordinate_normal":
        group = _get_toon_coordinate_normal_group()
    else:
        raise RuntimeError(f"Unknown material rule node group {group_name!r}.")

    node = mat.node_tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    return node


def _get_directx_normal_to_blender_group() -> bpy.types.NodeTree:
    group_name = "UTM DirectX Normal To Blender"
    existing = bpy.data.node_groups.get(group_name)
    if existing is not None:
        return existing

    group = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    _add_group_socket(group, "Color", "INPUT", "NodeSocketColor")
    _add_group_socket(group, "Normal", "OUTPUT", "NodeSocketVector")

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    split = nodes.new("ShaderNodeSeparateColor")
    invert_green = nodes.new("ShaderNodeInvert")
    combine = nodes.new("ShaderNodeCombineColor")
    normal_map = nodes.new("ShaderNodeNormalMap")

    group_input.location = (-700, 0)
    split.location = (-500, 0)
    invert_green.location = (-300, -80)
    combine.location = (-120, 0)
    normal_map.location = (80, 0)
    group_output.location = (300, 0)

    links.new(group_input.outputs["Color"], split.inputs["Color"])
    links.new(split.outputs["Red"], combine.inputs["Red"])
    links.new(split.outputs["Green"], invert_green.inputs["Color"])
    links.new(invert_green.outputs["Color"], combine.inputs["Green"])
    links.new(split.outputs["Blue"], combine.inputs["Blue"])
    links.new(combine.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], group_output.inputs["Normal"])
    return group


def _get_matcap_emission_strength_group() -> bpy.types.NodeTree:
    group_name = "UTM MatCap Emission Strength"
    existing = bpy.data.node_groups.get(group_name)
    if existing is not None:
        return existing

    group = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    _add_group_socket(group, "Color", "INPUT", "NodeSocketColor")
    _add_group_socket(group, "Value", "OUTPUT", "NodeSocketFloat")

    nodes = group.nodes
    links = group.links
    group_input = nodes.new("NodeGroupInput")
    group_output = nodes.new("NodeGroupOutput")
    rgb_to_bw = nodes.new("ShaderNodeRGBToBW")

    group_input.location = (-320, 0)
    rgb_to_bw.location = (-100, 0)
    group_output.location = (120, 0)

    links.new(group_input.outputs["Color"], rgb_to_bw.inputs["Color"])
    links.new(rgb_to_bw.outputs["Val"], group_output.inputs["Value"])
    return group


def _get_toon_coordinate_normal_group() -> bpy.types.NodeTree:
    group_name = "UTM Toon Coordinate Normal"
    existing = bpy.data.node_groups.get(group_name)
    if existing is not None:
        return existing

    group = bpy.data.node_groups.new(group_name, "ShaderNodeTree")
    _add_group_socket(group, "Normal", "OUTPUT", "NodeSocketVector")

    nodes = group.nodes
    links = group.links
    texcoord = nodes.new("ShaderNodeTexCoord")
    group_output = nodes.new("NodeGroupOutput")

    texcoord.location = (-220, 0)
    group_output.location = (0, 0)

    links.new(texcoord.outputs["Normal"], group_output.inputs["Normal"])
    return group


def _add_group_socket(group: bpy.types.NodeTree, name: str, in_out: str, socket_type: str) -> None:
    interface = getattr(group, "interface", None)
    if interface is not None and hasattr(interface, "new_socket"):
        interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
        return

    sockets = group.inputs if in_out == "INPUT" else group.outputs
    sockets.new(socket_type, name)


def _should_skip_connection(mat_ctx: MaterialContext,
                            rule: rule_module.TextureRule,
                            connection: rule_module.ConnectionSpec) -> bool:
    if (
        rule.diffuse
        and connection.source == "image.Alpha"
        and connection.target == "bsdf.Alpha"
        and not _material_uses_texture_alpha(mat_ctx.blend_mode)
    ):
        return True

    return False


def _should_skip_rule(mat_ctx: MaterialContext,
                      rule: rule_module.TextureRule) -> bool:
    for switch_name, expected_value in rule.skip_when:
        actual_value = _static_switch_value(mat_ctx, switch_name)
        if actual_value is not None and actual_value == expected_value:
            return True

    if rule.name == "alpha_mask" and not _material_uses_texture_alpha(mat_ctx.blend_mode):
        return True

    if rule.name == "normal" and _static_switch_is_disabled(mat_ctx, "usenormal", "use normal"):
        return True

    if (
        rule.name in {"orm", "rmo", "mroh", "mro", "rm", "sro"}
        and _static_switch_is_disabled(mat_ctx, "useorm", "use orm")
    ):
        return True

    return False


def _static_switch_is_disabled(mat_ctx: MaterialContext, *names: str) -> bool:
    for name in names:
        if mat_ctx.static_switch_parameters.get(name.lower()) is False:
            return True
    return False


def _static_switch_value(mat_ctx: MaterialContext, name: str) -> bool | None:
    if name in mat_ctx.static_switch_parameters:
        return mat_ctx.static_switch_parameters[name]

    normalized_name = _normalize_static_switch_name(name)
    for switch_name, value in mat_ctx.static_switch_parameters.items():
        if _normalize_static_switch_name(switch_name) == normalized_name:
            return value

    return None


def _normalize_static_switch_name(name: str) -> str:
    return rule_module._normalize_token(name).replace(" ", "").replace("_", "")  # pylint: disable=protected-access


def _material_uses_texture_alpha(blend_mode: str | None) -> bool:
    if blend_mode == "BLEND_Opaque (0)":
        return False

    return True


def _route_packed_diffuse_alpha(mat: bpy.types.Material,
                                mat_ctx: MaterialContext,
                                img_node: bpy.types.ShaderNodeTexImage) -> None:
    if not _material_uses_packed_diffuse_alpha_emission(mat_ctx):
        return

    if mat_ctx.bsdf_node is None:
        return

    emission_color = mat_ctx.vector_parameters.get("e_color", (1.0, 1.0, 1.0, 1.0))
    emission_level = max(mat_ctx.scalar_parameters.get("e_level", 1.0), 0.0)

    color_socket = utils.get_bsdf_input(mat_ctx.bsdf_node, "Emission Color")
    strength_socket = utils.get_bsdf_input(mat_ctx.bsdf_node, "Emission Strength")
    utils.set_socket_value(color_socket, emission_color)

    multiply = mat.node_tree.nodes.new("ShaderNodeMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = emission_level
    mat.node_tree.links.new(img_node.outputs["Alpha"], multiply.inputs[0])
    mat.node_tree.links.new(multiply.outputs[0], strength_socket)


def _treat_diffuse_alpha_as_data(img_node: bpy.types.ShaderNodeTexImage) -> None:
    image = img_node.image
    if image is None:
        return

    try:
        image.alpha_mode = "CHANNEL_PACKED"
    except (AttributeError, TypeError):
        pass


def _material_uses_packed_diffuse_alpha_emission(mat_ctx: MaterialContext) -> bool:
    if mat_ctx.blend_mode != "BLEND_Opaque (0)":
        return False

    return "e_level" in mat_ctx.scalar_parameters or "e_color" in mat_ctx.vector_parameters


def _link_toon_normal_fallback(mat: bpy.types.Material, mat_ctx: MaterialContext) -> None:
    if not _is_toon_shading_model(mat_ctx.shading_model):
        return
    if mat_ctx.bsdf_node is None:
        return

    normal_input = utils.get_bsdf_input(mat_ctx.bsdf_node, "Normal")
    if normal_input is None or normal_input.is_linked:
        return

    toon_normal = _create_rule_node_group(mat, "toon_coordinate_normal")
    mat.node_tree.links.new(toon_normal.outputs["Normal"], normal_input)


def _is_toon_shading_model(shading_model: str | None) -> bool:
    if shading_model is None:
        return False
    return rule_module._normalize_token(str(shading_model)) == "msm_toon"  # pylint: disable=protected-access


def _extract_blend_mode(desc_ast: t.Any) -> str | None:
    for child in desc_ast.children:
        def_name, _, value = child.children
        if def_name != "BasePropertyOverrides" or value.data != "structured_block":
            continue

        for prop_override_entry in value.children:
            prop_name, _, prop_value = prop_override_entry.children
            if prop_name == "BlendMode":
                return prop_value.children[0].value.strip()

    return None


def _extract_shading_model(desc_ast: t.Any) -> str | None:
    for child in desc_ast.children:
        def_name, _, value = child.children
        if def_name != "BasePropertyOverrides" or value.data != "structured_block":
            continue

        for prop_override_entry in value.children:
            prop_name, _, prop_value = prop_override_entry.children
            if prop_name == "ShadingModel":
                return prop_value.children[0].value.strip()

    return None


def _extract_description_shading_model(desc: t.Any) -> str | None:
    base_prop_overrides = getattr(desc, "base_prop_overrides", {})
    value = base_prop_overrides.get("ShadingModel")
    return str(value) if value is not None else None


def _configure_image_color_space(img_node: bpy.types.ShaderNodeTexImage,
                                 rule: rule_module.TextureRule) -> None:
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
