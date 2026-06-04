"""Compatibility wrapper — canonical implementation in umodel_tools.materials.rules_yaml."""

import importlib.util as _importlib_util
import os as _os
import sys as _sys

# --- Load canonical module and mirror its public namespace. ---
_canonical_module = None
try:
    from .materials.rules_yaml import *  # noqa: F401, F403
except ImportError:
    # Standalone load (e.g. `spec_from_file_location("material_rules", ...)`).
    _materials_dir = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "materials"
    )
    _spec = _importlib_util.spec_from_file_location(
        "umodel_tools.materials.rules_yaml",
        _os.path.join(_materials_dir, "rules_yaml.py"),
    )
    _canonical_module = _importlib_util.module_from_spec(_spec)
    _sys.modules["umodel_tools.materials.rules_yaml"] = _canonical_module
    _spec.loader.exec_module(_canonical_module)
    globals().update({k: v for k, v in _canonical_module.__dict__.items() if not k.startswith("_")})

# --- Expose private helpers referenced via protected access. ---
# game_profiles/generic.py accesses material_rules._normalize_token (etc.)
# via protected-member notation.  Ensure these names are visible regardless
# of how *this* module was loaded (package-relative vs. standalone).
_PRIVATE_NAMES = (
    "_normalize_token",
    "_normalize_texture_name",
    "_texture_suffix",
    "_matches_texture_suffix",
)

if _canonical_module is not None:
    # Standalone path: pull from the already-loaded canonical module.
    for _name in _PRIVATE_NAMES:
        globals()[_name] = getattr(_canonical_module, _name)
else:
    # Package-relative path: the `from .materials.rules_yaml import *` above
    # only brought in public names; re-import the private ones explicitly.
    from .materials.rules_yaml import (  # noqa: E402, F401
        _normalize_token,            # noqa: F401
        _normalize_texture_name,     # noqa: F401
        _texture_suffix,             # noqa: F401
        _matches_texture_suffix,     # noqa: F401
    )
