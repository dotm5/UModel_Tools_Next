"""Internal PSK/PSKX importer facade."""

from __future__ import annotations

from .vendor_inline.psk_psa_importer import pskimport as import_psk


def import_psk_mesh(filepath, context=None, import_bones=False, **kwargs):
    """Import a PSK/PSKX mesh through the legacy importer facade."""
    return import_psk(
        filepath=filepath,
        context=context,
        bImportbone=import_bones,
        **kwargs,
    )


__all__ = ("import_psk", "import_psk_mesh")
