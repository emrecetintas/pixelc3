# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise per-source styles, dithering and batch export in Blender.

The checks create temporary scenes, images and files. Blender timers drive the
workers and report completion in the test log.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback

import bpy
import numpy as np

addon = next(m for name, m in list(sys.modules.items())
             if name.endswith('pixel4ever.addon') and 'extensions' in getattr(m, '__file__', ''))
LOG = Path(__file__).with_suffix('.log')
checks = []
original_scene = bpy.context.window.scene
original_images = set(bpy.data.images)
scene = bpy.data.scenes.new('PixelC3 v030 temporary scene')
scenes = [scene]
images = []
material = bpy.data.materials.new('PixelC3 v030 temporary material')
material.use_nodes = True
node = material.node_tree.nodes.new('ShaderNodeTexImage')
folder = tempfile.TemporaryDirectory(prefix='pixel4ever-v030-')
root = Path(folder.name)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    checks.append('PASS: ' + message)
    LOG.write_text('\n'.join(checks) + '\nRUNNING\n')


def make_source(name, width, height, offset=0):
    array = np.ones((height, width, 4), np.float32)
    y, x = np.mgrid[:height, :width]
    array[..., 0] = ((x / width + offset) % 1)
    array[..., 1] = y / height
    array[..., 2] = .25
    image = addon.write_image(addon.core.Result(array, None, (width, height)), name)
    image['pixel4ever_generated'] = False
    images.append(image)
    return image


def cleanup():
    for entry in scenes:
        addon.jobs.cancel(entry)
        for row in entry.pixel4ever.outputs:
            for image in (row.source, row.result, row.custom_dither, row.custom_mask, row.custom_palette, row.custom_lut):
                if image and image not in original_images and image not in images:
                    images.append(image)
    bpy.data.materials.remove(material)
    for entry in scenes:
        bpy.data.scenes.remove(entry)
    for image in images:
        bpy.data.images.remove(image)
    folder.cleanup()
    assert bpy.context.window.scene == original_scene


def wait_for_job(settings):
    started = time.monotonic()
    while settings.busy:
        if time.monotonic() - started > 45:
            raise AssertionError('Background operation timed out')
        yield .1


def run():
    s = scene.pixel4ever
    a = make_source('PixelC3 v030 A.png', 64, 32)
    b = make_source('PixelC3 v030 collision.jpg', 48, 24, .3)
    pattern = make_source('PixelC3 v030 pattern', 4, 4)
    mask = make_source('PixelC3 v030 mask', 4, 4, .5)
    s.source = a
    s.pixel_count = 16
    s.output_size = 'PIXELS'
    s.quantize = 'PALETTE'
    s.palette_preset = 'C64'
    s.dither = 'FLOYD_STEINBERG'
    s.strength = 1
    s.input_encoding = 'SRGB'
    s.mask_weights = (.1, .2, .3, .4, .5, .6, .7)
    s.custom_dither = pattern
    s.custom_mask = mask
    s.custom_palette = b
    s.custom_lut = pattern
    style_a = addon.presets.recipe(s)['settings']
    first = addon.generate(scene)
    node.image = first
    original_result = addon.read_image(first).copy()
    s.source = b
    check(s.pixel_count == 16 and s.dither == 'FLOYD_STEINBERG' and s.custom_mask == mask,
          'new images inherit the current style and custom inputs once')
    s.pixel_count = 12
    s.quantize = 'CHANNELS'
    s.channel_colors = 3
    s.dither = 'NONE'
    s.input_encoding = 'LINEAR'
    s.custom_dither = None
    s.custom_mask = pattern
    s.custom_palette = None
    s.custom_lut = None
    second = addon.generate(scene)
    style_b = addon.presets.recipe(s)['settings']
    a.name = 'PixelC3 v030 collision.png'
    s.source = a
    check(addon.presets.recipe(s)['settings'] == style_a, 'switching to a renamed image restores every processing control and encoding')
    check((s.custom_dither, s.custom_mask, s.custom_palette, s.custom_lut) == (pattern, mask, b, pattern),
          'switching restores each custom input Image pointer')
    check(s.result == first and node.image == first, 'per-image controls retain separate outputs and material references')
    s.source = None
    s.pixel_count = 44
    s.source = a
    check(s.pixel_count == 16 and s.result == first, 'clearing Source does not replace its remembered controls')
    s.source = b
    check(addon.presets.recipe(s)['settings'] == style_b, 'second image restores its own independent style')
    addon.reset_settings(s, 'DIMENSIONS')
    s.source = a
    check(s.pixel_count == 16 and s.output_size == 'PIXELS', 'section reset affects the selected image only')
    s.source = b
    document = addon.presets.recipe(s)
    document['settings']['pixel_count'] = 8
    addon.presets.apply(s, document)
    s.source = a
    check(s.pixel_count == 16 and s.palette_preset == 'C64', 'loading a style into one image leaves another image’s controls intact')
    s.source = b
    check(s.pixel_count == 8, 'preset edits are remembered for the selected image')
    s.source = a
    addon.generate(scene)  # Update the legacy metadata after the rename.

    library = root / 'per_image.blend'
    LOG.write_text('\n'.join(checks) + '\nRUNNING: writing a temporary .blend library\n')
    bpy.data.libraries.write(str(library), {scene})
    LOG.write_text('\n'.join(checks) + '\nRUNNING: reloading a temporary .blend library\n')
    with bpy.data.libraries.load(str(library), link=False) as (data_from, data_to):
        data_to.scenes = [scene.name]
    restored = data_to.scenes[0]
    scenes.append(restored)
    rs = restored.pixel4ever
    row_a, row_b = list(rs.outputs)[:2]
    rs.source = row_b.source
    check(rs.pixel_count == 8 and rs.input_encoding == 'LINEAR', 'per-image settings survive .blend serialization')
    rs.source = row_a.source
    check(rs.pixel_count == 16 and rs.custom_mask == row_a.custom_mask and rs.result == row_a.result,
          'restored .blend keeps local custom inputs and source/output identities')

    legacy = bpy.data.scenes.new('PixelC3 v030 legacy migration temporary')
    scenes.append(legacy)
    ls = legacy.pixel4ever
    with addon.suspend_updates(ls):
        ls.source = a
        ls.result = first
        ls.pixel_count = 20
        ls.quantize = 'CHANNELS'
        ls.outputs.clear()
        ls.active_source = None
    addon.initialize_sources(ls)
    check(ls.pixel_count == 20 and addon.output_binding(ls, a).result == first,
          '0.2.0 migration retains ungenerated current controls and existing result')
    with addon.suspend_updates(ls):
        ls.source = b
        ls.result = second
        ls.pixel_count = 22
    addon.initialize_sources(ls)
    ls.source = a
    check(ls.pixel_count == 20, 'migration creates independently restorable image settings')

    addon.processing.clear()
    check(addon.jobs.start(scene), 'Floyd–Steinberg starts in the background worker')
    yield from wait_for_job(s)
    check(not s.last_error and not s.dirty and s.result == first, 'background Floyd–Steinberg commits to the existing output')
    np.testing.assert_array_equal(addon.read_image(first), original_result)
    check(node.image == first, 'background dithering retains material links')

    check(addon.batch.add_image(s, a) and addon.batch.add_image(s, b), 'batch queue accepts multiple original sources')
    check(not addon.batch.add_image(s, a) and not addon.batch.add_image(s, first),
          'batch queue excludes duplicates and generated outputs')
    # A direct queue edit can contain an unsupported image: report it and continue.
    bad = bpy.data.images.new('PixelC3 v030 unsupported sequence', width=1, height=1)
    images.append(bad)
    bad.source = 'SEQUENCE'
    s.batch_items.clear()
    for source in (a, bad, b):
        s.batch_items.add().source = source
    skipped = s.batch_items.add()
    skipped.source = pattern
    skipped.enabled = False
    s.preview_filter = 'BILINEAR'
    s.preview_mask = True
    s.mask_type = 'CUSTOM'
    s.mask_strength = 1
    snapshot_style = addon.presets.recipe(s)
    snapshot_bindings = [(row.source, row.result, row.settings_json) for row in s.outputs]
    snapshot_result = addon.read_image(first).copy()
    snapshot_dirty = s.dirty
    stem = bpy.path.clean_name('PixelC3 v030 collision')
    existing = root / f'{stem}_pixelc3.png'
    existing.write_bytes(b'keep this older export')
    with bpy.context.temp_override(scene=scene):
        outcome = bpy.ops.pixel4ever.batch_export(directory=str(root))
    check(outcome == {'FINISHED'} and s.busy, 'batch export operator starts an asynchronous queue')
    yield from wait_for_job(s)
    report = json.loads(s.batch_report)
    check(len(report['written']) == 2 and len(report['failed']) == 1 and report['remaining'] == 0,
          'batch reports invalid inputs and continues exporting later images')
    check(existing.read_bytes() == b'keep this older export', 'batch never replaces an existing file')
    check({Path(p).name for p in report['written']} == {
        f'{stem}_pixelc3_002.png', f'{stem}_pixelc3_003.png'},
        'duplicate file stems receive unique numbered output names')
    check(s.source == a and s.result == first and addon.presets.recipe(s) == snapshot_style,
          'batch retains the selected source, output and current controls')
    check([(row.source, row.result, row.settings_json) for row in s.outputs] == snapshot_bindings,
          'batch leaves all saved per-image styles intact')
    np.testing.assert_array_equal(addon.read_image(first), snapshot_result)
    check(node.image == first and s.dirty == snapshot_dirty, 'batch retains material links, output pixels and dirty state')
    exported = bpy.data.images.load(report['written'][0], check_existing=False)
    images.append(exported)
    expected = addon.compute(scene, for_export=True).pixels
    np.testing.assert_allclose(addon.read_image(exported), expected, atol=1 / 255 + 1e-5)
    check(tuple(exported.size) == (32, 16), 'batch writes real PNGs with preview filtering and mask preview disabled')
    check(s.progress == 1 and not addon.jobs.active(scene), 'batch finishes with complete progress and no active worker')

    # Both valid inputs are cached now. Advance exactly one item, then cancel.
    addon.jobs.start_batch(scene, [a, b], root)
    addon.jobs.poll()
    check(addon.jobs.active(scene), 'cached batches advance one image at a time')
    addon.jobs.cancel(scene)
    partial = json.loads(s.batch_report)
    check(partial['status'] == 'Cancelled' and len(partial['written']) == 1 and partial['remaining'] == 1,
          'Cancel retains completed PNGs and stops the remaining queue')
    check(Path(partial['written'][0]).is_file() and not s.busy, 'partial batch files remain readable after cancellation')
    addon.jobs.start_batch(scene, [a, b], root)
    s.colors += 1
    check(not s.busy and not addon.jobs.active(scene) and json.loads(s.batch_report)['status'] == 'Cancelled',
          'control changes cancel an obsolete batch')

    # Multi-file loading uses the actual file selection operator execute path.
    s.batch_items.clear()
    paths = [Path(p) for p in report['written']]
    with bpy.context.temp_override(scene=scene):
        outcome = bpy.ops.pixel4ever.batch_load(directory=str(root), files=[{'name': p.name} for p in paths])
    for row in s.batch_items:
        if row.source not in images:
            images.append(row.source)
    check(outcome == {'FINISHED'} and len(s.batch_items) == 2, 'Load Files adds a multi-file selection to the batch queue')
    check(bpy.context.window.scene == original_scene, 'all checks retain the user’s active scene')


flow = run()


def tick():
    try:
        return next(flow)
    except StopIteration:
        LOG.write_text('\n'.join([f'Blender {bpy.app.version_string}', f'Module: {addon.__file__}', *checks,
                                  f'PASS: {len(checks)} new workflow checks']) + '\n')
        print(LOG.read_text())
        cleanup()
        return None
    except Exception:
        LOG.write_text('\n'.join(checks) + '\n' + traceback.format_exc())
        cleanup()
        raise


# Run synchronous datablock/library operations from the Console invocation.
# Only resume the background-wait portion through timers.
delay = tick()
if delay is not None:
    bpy.app.timers.register(tick, first_interval=delay)
    print('PixelC3 0.3.0 checks running; report:', LOG)
