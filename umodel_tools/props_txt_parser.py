import os
import typing as t

import lark


with open(os.path.join(os.path.dirname(__file__), 'props_txt_grammar.lark'), mode='r', encoding='utf-8') as grammar_f:
    lark_parser = lark.Lark(grammar_f, parser='earley', propagate_positions=True, ambiguity='resolve')


@t.overload
def parse_props_txt(props_txt_path: str, mode: t.Literal['MESH']) -> tuple[lark.Tree, list[str]]:
    ...


@t.overload
def parse_props_txt(props_txt_path: str,
                    mode: t.Literal['MATERIAL']
                    ) -> tuple[lark.Tree, dict[str, str], dict[str, str | float | bool]]:
    ...


def parse_props_txt(props_txt_path: str,
                    mode: t.Literal['MESH'] | t.Literal['MATERIAL']
                    ) -> tuple[lark.Tree, list[str]] | tuple[lark.Tree, dict[str, str], dict[str, str | float | bool]]:
    """Parses props.txt file (UModel output) and returns either a list of material paths, or a list of texture paths
    depending on the mode. Note, the mode should be used appropriately depending on the origin of the file.

    :param props_txt_path: Path to the prop.txt file.
    :param mode: Mode of parsing, either mesh properties or texture properties.
    :raises NotImplementedError: Raised when not supported mode is passed.
    :raises OSError: Raised when file could not be opened.
    :raises RuntimeError: Raised when reading the file failed.
    :return: A list of relative paths (game format paths).
    """
    _verbose_print(f"Parsing {props_txt_path}...")

    with open(props_txt_path, mode='r', encoding='utf-8') as f:
        text = f.read()

        try:
            ast = lark_parser.parse(text)
        except lark.UnexpectedInput as e:
            raise RuntimeError(f"ERROR: Failed parsing {props_txt_path}.") from e

        match mode:
            case 'MESH':
                material_paths = []

                for child in ast.children:
                    assert child.data == 'definition'
                    def_name, array_qual, value = child.children

                    if def_name != 'Materials':
                        continue

                    assert array_qual is not None
                    assert value.data == 'structured_block'

                    for path_entry in value.children:
                        assert path_entry.data == 'definition'
                        _, _, path_desc = path_entry.children

                        assert path_desc.data == 'path'

                        _, path_value = path_desc.children
                        material_paths.append(path_value.children[0].value[1:][:-1])

                return ast, material_paths

            case 'MATERIAL':
                texture_infos = {}
                base_prop_overrides = None

                for child in ast.children:
                    assert child.data == 'definition'
                    def_name, array_qual, value = child.children

                    match def_name:
                        case 'TextureParameterValues':
                            assert array_qual is not None
                            assert value.data == 'structured_block'

                            for tex_param_def in value.children:
                                _, _, tex_param = tex_param_def.children
                                param_info, param_val, _ = tex_param.children
                                _, _, path_desc = param_val.children

                                # ignore unused materials
                                if path_desc.data != 'path':
                                    continue

                                _, path_value = path_desc.children

                                tex_path = path_value.children[0].value[1:][:-1]
                                tex_type = param_info.children[2].children[0].children[2].children[0].value.strip()

                                texture_infos[tex_type] = tex_path
                        case 'BasePropertyOverrides':
                            assert array_qual is None
                            assert value.data == 'structured_block'

                            base_prop_overrides = {}

                            for prop_override_entry in value.children:
                                prop_name, _, prop_value = prop_override_entry.children
                                prop_name = prop_name.value

                                match prop_name:
                                    case 'BlendMode':
                                        prop_value = prop_value.children[0].value.strip()
                                    case 'TwoSided':
                                        prop_value = prop_value.children[0].value == 'true'
                                    case 'OpacityMaskClipValue':
                                        prop_value = float(prop_value.children[0].value)
                                    case _:
                                        continue

                                base_prop_overrides[prop_name] = prop_value

                return ast, texture_infos, base_prop_overrides

            case _:
                raise NotImplementedError()


Color: t.TypeAlias = tuple[float, float, float, float]


def extract_parent_reference(ast: lark.Tree) -> str | None:
    for child in ast.children:
        def_name, _, value = child.children
        if def_name == 'Parent' and value.data == 'path':
            return _path_value(value)

    return None


def extract_scalar_parameters(ast: lark.Tree) -> dict[str, float]:
    values = {}

    for parameter in _iter_parameter_blocks(ast, 'ScalarParameterValues'):
        name = _parameter_name(parameter)
        value = _struct_value(parameter, 'ParameterValue')
        if name is None or value is None or value.data != 'const':
            continue

        try:
            values[name.lower()] = float(_const_value(value))
        except ValueError:
            continue

    return values


def extract_vector_parameters(ast: lark.Tree) -> dict[str, Color]:
    values = {}

    for parameter in _iter_parameter_blocks(ast, 'VectorParameterValues'):
        name = _parameter_name(parameter)
        value = _struct_value(parameter, 'ParameterValue')
        if name is None or value is None or value.data != 'structured_block':
            continue

        color = _vector_value(value)
        if color is not None:
            values[name.lower()] = color

    return values


def extract_static_switch_parameters(ast: lark.Tree) -> dict[str, bool]:
    values = {}

    static_parameters = _top_level_struct(ast, 'StaticParameters')
    if static_parameters is None:
        return values

    static_switches = _struct_value(static_parameters, 'StaticSwitchParameters')
    if static_switches is None or static_switches.data != 'structured_block':
        return values

    for parameter in static_switches.children:
        _, _, switch = parameter.children
        if switch.data != 'structured_block':
            continue

        name = _parameter_name(switch)
        value = _struct_value(switch, 'Value')
        if name is None or value is None or value.data != 'const':
            continue

        raw_value = _const_value(value).lower()
        if raw_value in {'true', 'false'}:
            values[name.lower()] = raw_value == 'true'

    return values


def _verbose_print(*args: t.Any) -> None:
    try:
        from . import utils  # pylint: disable=import-outside-toplevel
    except Exception:  # pragma: no cover - test environments may not provide bpy.
        return

    try:
        utils.verbose_print(*args)
    except Exception:  # pragma: no cover - addon preferences may not be registered in headless tests.
        return


def _top_level_struct(ast: lark.Tree, name: str) -> lark.Tree | None:
    for child in ast.children:
        def_name, _, value = child.children
        if def_name == name and value.data == 'structured_block':
            return value

    return None


def _iter_parameter_blocks(ast: lark.Tree, block_name: str) -> t.Iterator[lark.Tree]:
    for child in ast.children:
        def_name, array_qual, value = child.children
        if def_name != block_name or array_qual is None or value.data != 'structured_block':
            continue

        for param_def in value.children:
            _, _, parameter = param_def.children
            if parameter.data == 'structured_block':
                yield parameter


def _parameter_name(parameter: lark.Tree) -> str | None:
    param_info = _struct_value(parameter, 'ParameterInfo')
    if param_info is None or param_info.data != 'structured_block':
        return None

    name_value = _struct_value(param_info, 'Name')
    if name_value is None or name_value.data != 'const':
        return None

    return _const_value(name_value)


def _struct_value(structured_block: lark.Tree, name: str) -> lark.Tree | None:
    for child in structured_block.children:
        def_name, _, value = child.children
        if def_name == name:
            return value

    return None


def _vector_value(structured_block: lark.Tree) -> Color | None:
    channels = {
        'r': 0.0,
        'g': 0.0,
        'b': 0.0,
        'a': 1.0,
    }

    for child in structured_block.children:
        channel_name, _, channel_value = child.children
        channel_name = channel_name.lower()
        if channel_name not in channels or channel_value.data != 'const':
            return None

        try:
            channels[channel_name] = float(_const_value(channel_value))
        except ValueError:
            return None

    return channels['r'], channels['g'], channels['b'], channels['a']


def _const_value(value: lark.Tree) -> str:
    return value.children[0].value.strip()


def _path_value(value: lark.Tree) -> str:
    return value.children[1].children[0].value[1:-1]
