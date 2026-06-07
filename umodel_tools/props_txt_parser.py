import dataclasses
import os
import typing as t


@dataclasses.dataclass
class Token:
    value: str


@dataclasses.dataclass
class Tree:
    data: str
    children: list[t.Any]


@t.overload
def parse_props_txt(props_txt_path: str, mode: t.Literal['MESH']) -> tuple[Tree, list[str]]:
    ...


@t.overload
def parse_props_txt(props_txt_path: str,
                    mode: t.Literal['MATERIAL']
                    ) -> tuple[Tree, dict[str, str], dict[str, str | float | bool]]:
    ...


def parse_props_txt(props_txt_path: str,
                    mode: t.Literal['MESH'] | t.Literal['MATERIAL']
                    ) -> tuple[Tree, list[str]] | tuple[Tree, dict[str, str], dict[str, str | float | bool]]:
    _verbose_print(f"Parsing {props_txt_path}...")

    with open(props_txt_path, mode='r', encoding='utf-8') as f:
        text = f.read()

    try:
        ast = _PropsParser(text).parse()
    except ValueError as exc:
        raise RuntimeError(f"ERROR: Failed parsing {props_txt_path}.") from exc

    match mode:
        case 'MESH':
            material_paths = []
            materials = _top_level_struct(ast, 'Materials')
            if materials is not None:
                for path_entry in materials.children:
                    _, _, path_desc = path_entry.children
                    if path_desc.data == 'path':
                        material_paths.append(_path_value(path_desc))
            return ast, material_paths

        case 'MATERIAL':
            texture_infos = {}
            base_prop_overrides = None

            for tex_param in _iter_parameter_blocks(ast, 'TextureParameterValues'):
                tex_type = _parameter_name(tex_param)
                path_desc = _struct_value(tex_param, 'ParameterValue')
                if tex_type is None or path_desc is None or path_desc.data != 'path':
                    continue
                texture_infos[tex_type] = _path_value(path_desc)

            base_property_overrides = _top_level_struct(ast, 'BasePropertyOverrides')
            if base_property_overrides is not None:
                base_prop_overrides = {}

                for prop_override_entry in base_property_overrides.children:
                    prop_name, _, prop_value = prop_override_entry.children

                    match prop_name:
                        case 'BlendMode':
                            parsed_value = _const_value(prop_value)
                        case 'TwoSided':
                            parsed_value = _const_value(prop_value).lower() == 'true'
                        case 'ShadingModel':
                            parsed_value = _const_value(prop_value)
                        case 'OpacityMaskClipValue':
                            parsed_value = float(_const_value(prop_value))
                        case _:
                            continue

                    base_prop_overrides[prop_name] = parsed_value

            return ast, texture_infos, base_prop_overrides

        case _:
            raise NotImplementedError()


Color: t.TypeAlias = tuple[float, float, float, float]


class _PropsParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.length = len(text)

    def parse(self) -> Tree:
        return Tree('start', self._definitions())

    def _definitions(self, stop: str | None = None) -> list[Tree]:
        definitions = []
        while True:
            self._skip_ws_and_comments()
            if self._eof():
                if stop is not None:
                    raise ValueError(f"Expected {stop!r}.")
                break
            if stop is not None and self._peek() == stop:
                self.pos += 1
                break

            definitions.append(self._definition())
        return definitions

    def _definition(self) -> Tree:
        name = self._identifier()
        array_qual = None

        self._skip_inline_ws()
        if self._peek() == '[':
            self.pos += 1
            start = self.pos
            while not self._eof() and self._peek() != ']':
                self.pos += 1
            if self._eof():
                raise ValueError("Unterminated array qualifier.")
            array_qual = self.text[start:self.pos].strip()
            self.pos += 1

        self._skip_inline_ws()
        self._expect('=')
        value = self._value()

        self._skip_inline_ws()
        if not self._eof() and self._peek() == ',':
            self.pos += 1

        return Tree('definition', [name, array_qual, value])

    def _value(self) -> Tree:
        self._skip_inline_ws()

        if not self._eof() and self._peek() in '\r\n':
            saved = self.pos
            self._skip_ws_and_comments()
            if not self._eof() and self._peek() == '{':
                self.pos += 1
                return self._brace_value()
            self.pos = saved
            return Tree('const', [Token('')])

        if self._eof() or self._peek() in '\r\n}':
            return Tree('const', [Token('')])

        if self._peek() == '{':
            self.pos += 1
            return self._brace_value()

        path_type, path_value = self._try_path()
        if path_type is not None and path_value is not None:
            return Tree('path', [path_type, Tree('path_value', [Token(path_value)])])

        return Tree('const', [Token(self._const_text())])

    def _try_path(self) -> tuple[str | None, str | None]:
        saved = self.pos
        try:
            path_type = self._identifier()
        except ValueError:
            self.pos = saved
            return None, None

        if self._eof() or self._peek() != "'":
            self.pos = saved
            return None, None

        return path_type, self._quoted("'")

    def _brace_value(self) -> Tree:
        saved = self.pos
        self._skip_ws_and_comments()
        if not self._eof() and self._peek() == '}':
            self.pos += 1
            return Tree('structured_block', [])

        if self._looks_like_definition():
            self.pos = saved
            return Tree('structured_block', self._definitions(stop='}'))

        self.pos = saved
        values = []
        while True:
            self._skip_ws_and_comments()
            if self._eof():
                raise ValueError("Unterminated const list.")
            if self._peek() == '}':
                self.pos += 1
                break

            values.append(Tree('const', [Token(self._const_text())]))
            self._skip_ws_and_comments()
            if not self._eof() and self._peek() == ',':
                self.pos += 1

        return Tree('const_list', values)

    def _looks_like_definition(self) -> bool:
        saved = self.pos
        try:
            self._identifier()
            self._skip_inline_ws()
            if not self._eof() and self._peek() == '[':
                while not self._eof() and self._peek() != ']':
                    self.pos += 1
                if not self._eof():
                    self.pos += 1
            self._skip_inline_ws()
            return not self._eof() and self._peek() == '='
        except ValueError:
            return False
        finally:
            self.pos = saved

    def _identifier(self) -> str:
        self._skip_inline_ws()
        if self._eof():
            raise ValueError("Expected identifier.")

        start = self.pos
        while not self._eof():
            char = self._peek()
            if char.isspace() or char in "[]=,{}'\"":
                break
            self.pos += 1

        value = self.text[start:self.pos].strip()
        if not value:
            raise ValueError("Expected identifier.")
        return value

    def _const_text(self) -> str:
        pieces = []
        while not self._eof():
            char = self._peek()
            if char in '\r\n},':
                break
            if char == '/' and self._peek_next() == '/':
                break
            if char in {'"', "'"}:
                pieces.append(self._quoted(char))
                continue
            pieces.append(char)
            self.pos += 1
        return ''.join(pieces).strip()

    def _quoted(self, quote: str) -> str:
        self._expect(quote)
        start = self.pos
        while not self._eof() and self._peek() != quote:
            self.pos += 1
        if self._eof():
            raise ValueError("Unterminated quoted string.")
        value = self.text[start:self.pos]
        self.pos += 1
        return f"{quote}{value}{quote}"

    def _skip_ws_and_comments(self) -> None:
        while not self._eof():
            if self._peek().isspace():
                self.pos += 1
                continue
            if self._peek() == '/' and self._peek_next() == '/':
                self._skip_comment()
                continue
            break

    def _skip_inline_ws(self) -> None:
        while not self._eof() and self._peek() in ' \t':
            self.pos += 1

    def _skip_comment(self) -> None:
        while not self._eof() and self._peek() not in '\r\n':
            self.pos += 1

    def _expect(self, value: str) -> None:
        if self._eof() or self._peek() != value:
            raise ValueError(f"Expected {value!r}.")
        self.pos += 1

    def _peek(self) -> str:
        return self.text[self.pos]

    def _peek_next(self) -> str:
        return self.text[self.pos + 1] if self.pos + 1 < self.length else ''

    def _eof(self) -> bool:
        return self.pos >= self.length


def extract_parent_reference(ast: Tree) -> str | None:
    for child in ast.children:
        def_name, _, value = child.children
        if def_name == 'Parent' and value.data == 'path':
            return _path_value(value)

    return None


def extract_scalar_parameters(ast: Tree) -> dict[str, float]:
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


def extract_vector_parameters(ast: Tree) -> dict[str, Color]:
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


def extract_static_switch_parameters(ast: Tree) -> dict[str, bool]:
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
    except Exception:
        return

    try:
        utils.verbose_print(*args)
    except Exception:
        return


def _top_level_struct(ast: Tree, name: str) -> Tree | None:
    for child in ast.children:
        def_name, _, value = child.children
        if def_name == name and value.data == 'structured_block':
            return value

    return None


def _iter_parameter_blocks(ast: Tree, block_name: str) -> t.Iterator[Tree]:
    for child in ast.children:
        def_name, array_qual, value = child.children
        if def_name != block_name or array_qual is None or value.data != 'structured_block':
            continue

        for param_def in value.children:
            _, _, parameter = param_def.children
            if parameter.data == 'structured_block':
                yield parameter


def _parameter_name(parameter: Tree) -> str | None:
    param_info = _struct_value(parameter, 'ParameterInfo')
    if param_info is None or param_info.data != 'structured_block':
        return None

    name_value = _struct_value(param_info, 'Name')
    if name_value is None or name_value.data != 'const':
        return None

    return _const_value(name_value)


def _struct_value(structured_block: Tree, name: str) -> Tree | None:
    for child in structured_block.children:
        def_name, _, value = child.children
        if def_name == name:
            return value

    return None


def _vector_value(structured_block: Tree) -> Color | None:
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


def _const_value(value: Tree) -> str:
    return value.children[0].value.strip()


def _path_value(value: Tree) -> str:
    return value.children[1].children[0].value[1:-1]
