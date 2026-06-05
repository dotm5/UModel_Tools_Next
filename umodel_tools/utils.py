import os
import sys
import typing as t
import tempfile
import contextlib
import json

import bpy

from . import preferences


tmphandle, tmppath = tempfile.mkstemp()
#: Determines whether the OS's filesystem is case sensitive or not
FS_CASE_INSENSITIVE = os.path.exists(tmppath.upper())
os.close(tmphandle)
os.remove(tmppath)


def copy_object(obj: bpy.types.Object) -> bpy.types.Object:
    """Copies an object and its mesh. No linking is performed.

    :param obj: Blender object.
    :return: Copied object.
    """
    copied_obj = obj.copy()
    copied_obj.data = obj.data.copy()
    return copied_obj


def compare_meshes(first: bpy.types.Mesh, second: bpy.types.Mesh) -> bool:
    """Compare two meshes on basic geometric similarity.

    :param first: First mesh.
    :param second: Second mesh.
    :return: Returns True if number of vertices, edges, faces and loops is equal.
    """

    return (len(first.vertices) == len(second.vertices)
            and len(first.polygons) == len(second.polygons)
            and len(first.loops) == len(second.loops)
            and len(first.edges) == len(second.edges))


def compare_paths(first: str, second: str) -> bool:
    """Compares that to paths are identical. Respects OS case sensitivity rules for the filesystem.

    :param first: First path.
    :param second: Second path.
    :return: True if paths are identical, else False.
    """
    first = os.path.realpath(first)
    second = os.path.realpath(second)

    return (first.lower() == second.lower()) if FS_CASE_INSENSITIVE else (first == second)


DataBlock: t.TypeAlias = bpy.types.Object | bpy.types.Material | bpy.types.Image


def normalize_ue_name(value: t.Any, fallback: str = "Unnamed") -> str:
    """Convert UE/FModel object references into a Blender API-safe name string."""
    if isinstance(value, str):
        name = value
    elif value is None:
        name = fallback
    elif isinstance(value, dict):
        for key in ("Name", "ObjectName", "ObjectPath", "Outer", "Type"):
            if key in value and value[key] not in {None, ""}:
                return normalize_ue_name(value[key], fallback=fallback)
        name = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        name = str(value)

    name = name.replace("\x00", "").strip()
    return name if name else fallback


def warn_ue_mapping(kind: str, name: t.Any, reason: str, **details: t.Any) -> None:
    """Emit a structured warning for UE data that cannot be mapped directly."""
    payload = {
        "kind": kind,
        "name": normalize_ue_name(name),
        "reason": reason,
        "details": details,
    }
    print(f"UMODEL_TOOLS_WARNING {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


_BSDF_SOCKET_ALIASES = {
    "Specular": ("Specular", "Specular IOR Level"),
    "Clearcoat": ("Clearcoat", "Coat Weight"),
    "Clearcoat Roughness": ("Clearcoat Roughness", "Coat Roughness"),
}


def get_bsdf_input(bsdf_node: bpy.types.Node, socket_name: str) -> bpy.types.NodeSocket:
    """Return a Principled BSDF input by RNA identifier/name, including known API renames."""
    names = _BSDF_SOCKET_ALIASES.get(socket_name, (socket_name,))

    for socket in bsdf_node.inputs:
        if socket.identifier in names or socket.name in names:
            return socket

    available = [(socket.identifier, socket.name) for socket in bsdf_node.inputs]
    raise KeyError(f"Principled BSDF input {socket_name!r} not found. Available sockets: {available!r}")


def set_socket_value(socket: bpy.types.NodeSocket, value: t.Any) -> None:
    """Set a socket default value while respecting scalar vs array RNA socket values."""
    current_value = getattr(socket, "default_value", None)
    if current_value is None:
        raise TypeError(f"Socket {socket.identifier!r} has no default_value.")

    if hasattr(current_value, "__len__") and not isinstance(current_value, (str, bytes)):
        length = len(current_value)
        if isinstance(value, (int, float)):
            if length == 4:
                socket.default_value = (float(value), float(value), float(value), current_value[3])
            else:
                socket.default_value = tuple(float(value) for _ in range(length))
        else:
            socket.default_value = value
    else:
        socket.default_value = value


def linked_libraries_search(lib_filepath: str, dtype: t.Type[DataBlock]) -> t.Optional[DataBlock]:
    """Check already linked libraries for the associated data block and return it.

    :param lib_filepath: Filepath of the library.
    :param dtype: Datablock type.
    :return: None or data-block (if found).
    """

    for lib in bpy.data.libraries:
        if compare_paths(lib.filepath, lib_filepath):
            for id_data in lib.users_id:
                if isinstance(id_data, dtype):
                    return id_data

    return None


def verbose_print(*args: t.Any):
    """Prints to stdout, if addon has verbose setting enabled.

    :args: Arguments to internal print() call.
    """
    if preferences.get_addon_preferences().verbose:
        print(*args)


@contextlib.contextmanager
def std_out_err_passthrough():
    """Compatibility no-op for import loops that used to wrap console output."""
    yield sys.stdout


@contextlib.contextmanager
def redirect_cstdout(to=os.devnull):
    """Redirect stdout from C/C++ parts of Blender and external libaries.
    We use this to suppress library reading and linking messages.

    :param to: _description_, defaults to os.devnull
    :yield: _description_
    """

    # disable the whole redirect in debug mode
    if preferences.get_addon_preferences().debug:
        yield
        return None

    fd = sys.stdout.fileno()

    def _redirect_stdout(to):
        os.dup2(to.fileno(), fd)  # fd writes to 'to' file

    with os.fdopen(os.dup(fd), 'w') as old_stdout:
        with open(to, 'w') as file:  # pylint: disable=unspecified-encoding
            _redirect_stdout(to=file)
        try:
            yield  # allow code to be run with the redirected stdout
        finally:
            _redirect_stdout(to=old_stdout)  # restore stdout

    return None
