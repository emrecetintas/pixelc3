# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run workflow integration checks with temporary Blender datablocks.

Run in the Python Console after enabling PixelC3:
    p = '/absolute/path/to/tests/blender_workflow.py'
    exec(compile(open(p).read(), p, 'exec'), {'__file__': p})

The final background completion check uses Blender's timers.
"""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'tests' / 'blender_workflow.log'
addon = globals().get('target') or next(m for name, m in list(sys.modules.items())
                                       if name.endswith('pixel4ever.addon') and 'extensions' in getattr(m, '__file__', ''))
checks = []
scene = bpy.data.scenes.new('PixelC3 workflow temporary scene')
tracked_images = []
tracked_scenes = [scene]
material = bpy.data.materials.new('PixelC3 workflow temporary material')
material.use_nodes = True
node = material.node_tree.nodes.new('ShaderNodeTexImage')
temporary = tempfile.TemporaryDirectory(prefix='pixel4ever-workflow-')


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    checks.append('PASS: ' + message)


def source_image(name, rgb):
    pixels = np.ones((64, 64, 4), np.float32)
    pixels[..., :3] = rgb
    image = addon.write_image(addon.core.Result(pixels, None, (64, 64)), name)
    image['pixel4ever_generated'] = False
    tracked_images.append(image)
    return image


def cleanup():
    for entry in tracked_scenes:
        if entry.name in bpy.data.scenes:
            for binding in entry.pixel4ever.outputs:
                for image in (binding.source, binding.result):
                    if image and image not in tracked_images:
                        tracked_images.append(image)
            if entry.pixel4ever.comparison and entry.pixel4ever.comparison not in tracked_images:
                tracked_images.append(entry.pixel4ever.comparison)
            addon.jobs.cancel(entry)
    bpy.data.materials.remove(material)
    for entry in tracked_scenes:
        bpy.data.scenes.remove(entry)
    for image in tracked_images:
        bpy.data.images.remove(image)
    temporary.cleanup()


def failed():
    LOG.write_text('\n'.join(checks) + '\n' + traceback.format_exc())
    cleanup()


try:
    s = scene.pixel4ever
    red = source_image('PixelC3 workflow source RED', [.8, .1, .05])
    blue = source_image('PixelC3 workflow source BLUE', [.05, .1, .8])
    s.source = red
    s.pixel_count = 16
    s.output_size = 'PIXELS'
    first = addon.generate(scene)
    node.image = first
    before = addon.read_image(first).copy()
    s.source = blue
    check(s.result is None, 'new source has no previous source’s result')
    second = addon.generate(scene)
    check(first != second, 'different sources have distinct output Image datablocks')
    np.testing.assert_array_equal(addon.read_image(first), before)
    check(node.image == first, 'switching sources preserves the material’s original result')
    red.name = 'PixelC3 workflow RENAMED RED'
    s.source = red
    check(s.result == first, 'returning to a renamed source restores its own result')
    s.pixel_count = 32
    check(addon.generate(scene) == first, 'same-source regeneration retains output identity')
    check(tuple(second.size) == (16, 16), 'regenerating one source leaves another output unchanged')

    s.custom_dither = blue
    s.strength = .8
    s.colors = 8
    s.seed = 123
    addon.reset_settings(s, 'DIMENSIONS')
    check(s.pixel_count == 256 and s.strength > .79 and s.colors == 8, 'section reset affects only its own settings')
    addon.reset_settings(s)
    check(s.source == red and s.result == first and s.custom_dither == blue and len(s.outputs) == 2,
          'global reset retains source, outputs, material links and custom input images')
    check(s.quantize == 'NONE' and s.dither == 'NONE' and s.seed == 0 and s.colors == 32,
          'global reset restores documented defaults')

    s.pixel_count = 24
    s.quantize = 'PALETTE'
    s.palette_preset = 'C64_EARLY'
    s.dither = 'BAYER'
    s.dither_method = 'QUANTIZATION'
    s.mask_weights = (.1, .2, .3, .4, .5, .6, .7)
    document = addon.presets.recipe(s, 'Workflow test')
    preset_path = Path(temporary.name) / 'recipe.json'
    preset_path.write_text(json.dumps(document))
    addon.reset_settings(s)
    addon.presets.load_file(s, preset_path)
    check(s.pixel_count == 24 and s.palette_preset == 'C64_EARLY' and s.dither_method == 'QUANTIZATION',
          'JSON preset round-trip restores scalars and enum choices')
    np.testing.assert_allclose(s.mask_weights[:], [.1, .2, .3, .4, .5, .6, .7])
    check(s.source == red and s.result == first, 'loading a preset retains the selected source and output')
    invalid = json.loads(json.dumps(document))
    invalid['settings']['pixel_count'] = 12
    invalid['settings']['colors'] = 99999
    try:
        addon.presets.apply(s, invalid)
        raise AssertionError('Invalid preset was accepted')
    except ValueError:
        pass
    check(s.pixel_count == 24, 'invalid preset is rejected before any partial changes')

    original_directory = addon.presets.preset_directory
    shelf = Path(temporary.name) / 'presets'
    shelf.mkdir()
    addon.presets.preset_directory = lambda create=False: shelf
    try:
        with bpy.context.temp_override(scene=scene):
            outcome = bpy.ops.pixel4ever.save_preset(name='Workflow Saved Style')
            check(outcome == {'FINISHED'} and s.user_preset != 'NONE', 'Save Preset adds a named shelf entry')
            s.pixel_count = 10
            outcome = bpy.ops.pixel4ever.load_preset()
            check(outcome == {'FINISHED'} and s.pixel_count == 24, 'Load Preset restores its named shelf entry')
    finally:
        addon.presets.preset_directory = original_directory
        addon.presets.preset_items()
        s.user_preset = 'NONE'

    s.quantize = 'NONE'
    s.dither = 'NONE'
    s.output_size = 'PIXELS'
    s.pixel_count = 32
    first = addon.generate(scene)
    area = next((a for a in bpy.context.screen.areas if a.type == 'IMAGE_EDITOR'), None)
    restore_type = None
    if area is None:
        area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
        if area:
            restore_type = area.type
            area.type = 'IMAGE_EDITOR'
    if area:
        old_image = area.spaces.active.image
        try:
            with bpy.context.temp_override(scene=scene, area=area):
                outcome = bpy.ops.pixel4ever.compare()
            check(outcome == {'FINISHED'} and s.comparison != first and s.result == first,
                  'comparison is a separate preview and leaves the output binding intact')
        finally:
            area.spaces.active.image = old_image
            if restore_type:
                area.type = restore_type
    else:
        checks.append('SKIP: comparison view (no Image Editor in this workspace)')

    library = Path(temporary.name) / 'bindings.blend'
    bpy.data.libraries.write(str(library), {scene})
    with bpy.data.libraries.load(str(library), link=False) as (data_from, data_to):
        data_to.scenes = [scene.name]
    restored = data_to.scenes[0]
    tracked_scenes.append(restored)
    check(len(restored.pixel4ever.outputs) == 2 and all(row.source and row.result for row in restored.pixel4ever.outputs),
          'source/output bindings survive a .blend library save and reload')

    addon.processing.clear()
    s.quantize = 'GENERATE'
    s.creation_space = 'OKLAB'
    s.colors = 16
    snapshot = addon.read_image(first).copy()
    check(addon.jobs.start(scene), 'background generation starts in a separate process')
    addon.jobs.cancel(scene)
    check(not s.busy and not addon.jobs.active(scene) and s.result == first,
          'Cancel stops the job and retains the previous output')
    np.testing.assert_array_equal(addon.read_image(first), snapshot)
    check(addon.jobs.start(scene), 'a new job can start after cancellation')
    s.colors = 8
    check(not s.busy and not addon.jobs.active(scene), 'changing settings cancels an obsolete background job')
    check(addon.jobs.start(scene), 'final background job starts')
    started = time.monotonic()

    def finish():
        try:
            if s.busy:
                if time.monotonic() - started > 30:
                    raise AssertionError('Background job timed out')
                return .1
            check(not s.last_error and not s.dirty and s.result == first,
                  'background job commits its result on the main thread')
            check(s.progress == 1 and s.progress_stage == 'Ready', 'background job reports completion progress')
            check(node.image == first, 'background completion preserves material links')
            config, images, key = addon.prepare(scene)
            check(addon.processing.cached(key) is not None, 'background result enters the content cache')
            check(not addon.jobs.start(scene) and 'cached' in s.last_summary, 'identical requests reuse the cached result')
            LOG.write_text('\n'.join([f'Blender {bpy.app.version_string}', f'Module: {addon.__file__}', *checks,
                                      f'PASS: {sum(c.startswith("PASS") for c in checks)} workflow checks']) + '\n')
            print(LOG.read_text())
            cleanup()
            return None
        except Exception:
            failed()
            raise

    bpy.app.timers.register(finish, first_interval=.2)
    print('PixelC3 workflow checks are finishing in the background; report:', LOG)
except Exception:
    failed()
    raise
