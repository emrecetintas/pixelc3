# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks using real Blender Image buffers, including packed reloads.

Can be run from an existing Blender Python Console without changing its project:
    p = '/absolute/path/to/tests/blender_image_regeneration.py'
    exec(compile(open(p).read(), p, 'exec'), {'__file__': p})

Set 'target' in the exec globals to an add-on module to test that module instead.
Only test-created images, material and temporary files are removed afterward.
"""
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import traceback

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'tests' / 'blender_image_regeneration.log'


def load_checkout():
    name = '_pixel4ever_regression'
    for key in list(sys.modules):
        if key == name or key.startswith(name + '.'):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(name, ROOT / 'pixel4ever' / '__init__.py',
                                                submodule_search_locations=[str(ROOT / 'pixel4ever')])
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return importlib.import_module(name + '.addon')


def run(addon):
    images = []
    material = bpy.data.materials.new('PixelC3 regression temporary material')
    material.use_nodes = True
    node = material.node_tree.nodes.new('ShaderNodeTexImage')
    checks = []
    try:
        rng = np.random.default_rng(17)
        source = rng.random((256, 256, 4), dtype=np.float32)
        source[..., 3] = 1
        image = None
        config = addon.core.Settings(output_size='PIXELS')
        # Exercise the resize path for previously packed images.
        for i, count in enumerate((128, 256, 64, 256, 256, 128)):
            config.pixel_count = count
            config.quantize = 'CHANNELS'
            config.channel_colors = 4 if i % 2 else 8
            result = addon.core.process(source, config)
            previous = image
            image = addon.write_image(result, 'PixelC3 regression temporary result', image)
            if previous is None:
                images.append(image)
                node.image = image
            assert previous is None or image == previous, 'Image identity changed'
            assert node.image == image, 'Material lost its image reference'
            assert tuple(image.size) == (count, count), tuple(image.size)
            assert len(image.pixels) == count * count * 4
            assert image.packed_file is not None, 'Result is not packed'
            np.testing.assert_allclose(addon.read_image(image), result.pixels, atol=1 / 255 + 1e-6)
            image.reload()
            assert tuple(image.size) == (count, count), 'Packed size is stale after reload'
            np.testing.assert_allclose(addon.read_image(image), result.pixels, atol=1 / 255 + 1e-6)
            checks.append(f'PASS: regenerate/reload {count} × {count}, channel levels {config.channel_colors}, same Image and material reference')
        # Setting alpha/color space must happen before a resize even if the user
        # edits the output's metadata between generations.
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'PREMUL'
        config.pixel_count = 256
        result = addon.core.process(source, config)
        addon.write_image(result, image.name, image)
        assert tuple(image.size) == (256, 256)
        np.testing.assert_allclose(addon.read_image(image), result.pixels, atol=1 / 255 + 1e-6)
        checks.append('PASS: color-space and alpha changes before resizing a packed result')
        # Palette swatches, rectangular results, and full-size output must be
        # interchangeable without retaining the previous packed dimensions.
        for width, height in ((16, 16), (192, 96), (256, 256)):
            pixels = rng.random((height, width, 4), dtype=np.float32)
            result = addon.core.Result(pixels, None, (width, height))
            addon.write_image(result, image.name, image)
            image.reload()
            assert tuple(image.size) == (width, height)
            np.testing.assert_allclose(addon.read_image(image), pixels, atol=1 / 255 + 1e-6)
            checks.append(f'PASS: switch/reload output size {width} × {height} with alpha')
        # File-backed saved results must also survive regeneration and repacking.
        with tempfile.TemporaryDirectory(prefix='pixel4ever-regression-') as temporary:
            image.file_format = 'PNG'
            image.filepath_raw = str(Path(temporary) / 'result.png')
            image.save()
            result = addon.core.Result(source[:64, :128], None, (128, 64))
            addon.write_image(result, image.name, image)
            image.reload()
            assert tuple(image.size) == (128, 64)
            np.testing.assert_allclose(addon.read_image(image), result.pixels, atol=1 / 255 + 1e-6)
            checks.append('PASS: resize, repack and reload a previously saved result')
        return checks
    finally:
        bpy.data.materials.remove(material)
        for image in images:
            bpy.data.images.remove(image)


try:
    tested = globals().get('target') or load_checkout()
    checks = run(tested)
    report = '\n'.join([f'Blender {bpy.app.version_string}', f'Module: {tested.__file__}', *checks,
                        f'PASS: {len(checks)} regression scenarios'])
    LOG.write_text(report + '\n')
    print(report)
except Exception:
    LOG.write_text(traceback.format_exc())
    raise
