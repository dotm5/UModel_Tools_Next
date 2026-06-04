"""Compatibility wrapper — canonical implementation in umodel_tools.materials.decision."""

try:
    from .materials.decision import *  # noqa: F401, F403
except ImportError:
    # Standalone load (e.g. `import material_decision` from tests).
    # Resolve the canonical module directly without triggering
    # umodel_tools.__init__ (which imports bpy).
    import importlib.util as _importlib_util
    import os as _os
    _materials_dir = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "materials"
    )
    _spec = _importlib_util.spec_from_file_location(
        "umodel_tools.materials.decision",
        _os.path.join(_materials_dir, "decision.py"),
    )
    _mod = _importlib_util.module_from_spec(_spec)
    import sys as _sys
    _sys.modules["umodel_tools.materials.decision"] = _mod
    _spec.loader.exec_module(_mod)
    globals().update({k: v for k, v in _mod.__dict__.items() if not k.startswith("_")})
