"""Internal PSK/PSKX importer facade."""

from __future__ import annotations

from .vendor_inline.psk_psa_importer import pskimport as import_psk


__all__ = ("import_psk",)
