# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate a procedural source and a pixelated example in Blender.

From Blender's Python Console, run this file with runpy.run_path().
The example uses the active scene's PixelC3 settings and writes its PNGs
to exports/demo/. Run it in a new Blender project to keep a separate look.
"""
from pathlib import Path
import importlib
import sys

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if hasattr(bpy.types.Scene, 'pixel4ever'):
    addon = importlib.import_module(type(bpy.context.scene.pixel4ever).__module__)
else:
    sys.path.insert(0, str(ROOT))
    from pixel4ever import addon
    addon.register()
core = addon.core

# Broad gradients, silhouettes, highlights, high-frequency detail, alpha-safe IO.
width, height = 768, 512
x, y = np.meshgrid(np.linspace(0, 1, width), np.linspace(0, 1, height))
rgb = np.zeros((height, width, 3), np.float32)
top = np.array([.08, .12, .30])
bottom = np.array([.86, .43, .32])
rgb[:] = top + (bottom - top) * y[..., None]
sun = (x - .73) ** 2 + (y - .31) ** 2 < .092 ** 2
rgb[sun] = np.array([1.0, .79, .47])
for distance, color, base in [(0, [.27, .22, .40], .53), (1, [.16, .23, .34], .66), (2, [.06, .15, .24], .79)]:
    ridge = base + .04 * np.sin(16 * x + distance * 3) + .045 * np.sin(33 * x + distance)
    rgb[y > ridge] = color
water = y > .77
reflect = np.exp(-((x - .73) / (.025 + .2 * (y - .77).clip(0))) ** 2)
waves = (.5 + .5 * np.sin(y * 350 + np.sin(x * 75) * 2))
water_rgb = np.stack((.07 + .5 * reflect * waves, .19 + .25 * reflect * waves, .27 + .08 * waves), -1)
rgb[water] = water_rgb[water]
# Three textured, shaded orbs make the effect on smooth volume easy to inspect.
for cx, cy, radius, color in [(.20, .40, .11, [.19, .75, .78]), (.40, .52, .085, [.94, .43, .20]), (.12, .66, .065, [.69, .44, .85])]:
    nx, ny = (x - cx) / radius, (y - cy) / radius
    inside = nx * nx + ny * ny <= 1
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    light = np.clip(-.42 * nx - .5 * ny + .75 * nz, 0, 1)
    specular = np.clip(-.24 * nx - .35 * ny + .90 * nz, 0, 1) ** 32
    noise = np.random.default_rng(7).normal(0, .013, (height, width))
    sphere = np.array(color) * (.15 + .85 * light[..., None]) + .65 * specular[..., None] + noise[..., None]
    rgb[inside] = sphere[inside]
rgba = np.concatenate((np.clip(rgb, 0, 1), np.ones((height, width, 1), np.float32)), -1)
source = bpy.data.images.get('PixelC3 Demo - Original')
source = addon.write_image(core.Result(rgba, None, (width, height)), 'PixelC3 Demo - Original', source)
source['pixel4ever_generated'] = False
s = bpy.context.scene.pixel4ever
s.source = source
s.pixel_count = 128
s.quantize = 'GENERATE'
s.colors = 24
s.creation_space = 'OKLAB'
s.apply_space = 'OKLAB'
s.dither = 'BAYER'
s.strength = .35
s.grayscale_dither = True
result = addon.generate(bpy.context.scene)
# Store disposable demo exports separately from the checked-in examples.
destination = ROOT / 'exports' / 'demo'
destination.mkdir(exist_ok=True, parents=True)
for image, filename in ((source, 'source.png'), (result, 'pixelc3.png')):
    image.file_format = 'PNG'
    image.filepath_raw = str(destination / filename)
    image.save()
# Turn only the current editor into an Image Editor after script execution.
area = bpy.context.area
if area:
    area.type = 'IMAGE_EDITOR'
    area.spaces.active.image = result
    area.spaces.active.show_region_ui = True
print('PIXELC3 READY:', s.last_summary)
