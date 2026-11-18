# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PixelC3: native Blender texture pixelation."""

bl_info = {
    "name": "PixelC3",
    "author": "PixelC3 contributors",
    "version": (0, 4, 3),
    "blender": (4, 2, 0),
    "location": "Image Editor / 3D View > Sidebar > PixelC3",
    "description": "Pixelate textures with dithering, generated palettes and retro color modes",
    "category": "Paint",
}


def register():
    from . import addon
    addon.register()


def unregister():
    from . import addon
    addon.unregister()
