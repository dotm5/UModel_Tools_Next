# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import os
import sys
import bpy


# include custom lib vendoring dir
parent_dir = os.path.abspath(os.path.dirname(__file__))
vendor_dir = os.path.join(parent_dir, 'third_party')

sys.path.append(vendor_dir)

from . import auto_load  # nopep8 pylint: disable=wrong-import-position
from . import localization  # nopep8 pylint: disable=wrong-import-position


#: Addon description for Blender. Displayed in settings.
bl_info = {
    "name": "UModel Tools Next",
    "author": "dotm5 (fork maintainer), Skarn (original author)",
    "version": (1, 3, 0),
    "blender": (5, 1, 0),
    "description": "Map-focused UModel/FModel recovery tools for Blender",
    "doc_url": "https://github.com/dotm5/UModel_Tools_Next",
    "tracker_url": "https://github.com/dotm5/UModel_Tools_Next/issues",
    "category": "Import-Export"
}

#: Name of the addon recognizeable by Blender
PACKAGE_NAME = __package__


def register():
    auto_load.init()
    localization.register_translations()
    auto_load.register()


def unregister():
    auto_load.unregister()
    localization.unregister_translations()


__all__ = (
    'bl_info',
    'register',
    'unregister',
    'PACKAGE_NAME'
)


if __name__ == "__main__":
    register()
