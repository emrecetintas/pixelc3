# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Short-lived real progress/cancel UI check; auto-restores the original scene."""
from pathlib import Path
import sys
import bpy

addon = next(m for name, m in list(sys.modules.items())
             if name.endswith('pixel4ever.addon') and 'extensions' in getattr(m, '__file__', ''))
window = bpy.context.window
original = window.scene
area = bpy.context.area
temporary = bpy.data.scenes.new('PixelC3 progress UI temporary scene')
source = original.pixel4ever.source
result_before = original.pixel4ever.result
cleaned = False


def cleanup():
    global cleaned
    if cleaned:
        return None
    cleaned = True
    addon.jobs.cancel(temporary)
    generated = [row.result for row in temporary.pixel4ever.outputs if row.result]
    window.scene = original
    bpy.data.scenes.remove(temporary)
    for image in generated:
        assert image != result_before
        bpy.data.images.remove(image)
    assert original.pixel4ever.source == source
    assert original.pixel4ever.result == result_before
    Path(__file__).with_suffix('.log').write_text('PASS: progress UI check restored the original scene and images\n')
    return None


s = temporary.pixel4ever
s.source = source
s.quantize = 'GENERATE'
s.colors = 256
s.quality = 8
s.pixel_count = 256
s.apply_space = 'LAB'
s.output_lut = True
window.scene = temporary
addon.jobs.start(temporary)
bpy.app.timers.register(cleanup, first_interval=30)
area.type = 'VIEW_3D'
area.spaces.active.show_region_ui = True
