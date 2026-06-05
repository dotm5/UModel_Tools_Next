"""UEFormat model reader and Blender import helpers.

The binary layout follows the public UEFormat Blender add-on format.  The code
here is intentionally small and local to UModel Tools so .uemodel can participate
in the existing asset cache and material reconstruction pipeline.  See
NOTICE.md for upstream GPL-3.0-or-later attribution.
"""

from .model import (
    MAGIC,
    MODEL_IDENTIFIER,
    UEFormatError,
    UEFormatVersion,
    UEModel,
    load_uemodel,
)

__all__ = (
    "MAGIC",
    "MODEL_IDENTIFIER",
    "UEFormatError",
    "UEFormatVersion",
    "UEModel",
    "load_uemodel",
)
