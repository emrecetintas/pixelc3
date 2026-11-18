# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Numerical and worker regression tests for Python with NumPy installed."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

from pixel4ever import core, palettes, processing


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        processing.clear()
        self.image = np.ones((32, 32, 4), np.float32)
        self.image[..., :3] = .25
        self.palette = np.array([[[0, 0, 0, 1], [1, 1, 1, 1]]], np.float32)
        self.config = core.Settings(pixel_count=32, output_size='PIXELS', quantize='PALETTE',
                                    palette_preset='CUSTOM_PALETTE', dither='BAYER',
                                    dither_method='QUANTIZATION', strength=1)

    def test_ordered_palette_preserves_members_and_mean(self):
        result = core.process(self.image, self.config, custom_palette=self.palette)
        self.assertEqual(set(np.unique(result.pixels[..., :3])), {0., 1.})
        self.assertAlmostEqual(float(result.pixels[..., :3].mean()), .25, places=6)
        np.testing.assert_array_equal(result.pixels[..., 3], 1)

    def test_zero_strength_is_nearest(self):
        zero = core.process(self.image, replace(self.config, strength=0), custom_palette=self.palette)
        none = core.process(self.image, replace(self.config, dither='NONE'), custom_palette=self.palette)
        np.testing.assert_array_equal(zero.pixels, none.pixels)

    def test_mask_zero_is_nearest_and_alpha_survives(self):
        image = self.image.copy()
        image[..., 3] = .4
        config = replace(self.config, mask_type='CUSTOM', mask_strength=1)
        mask = np.zeros((4, 4, 4), np.float32)
        result = core.process(image, config, custom_palette=self.palette, custom_mask=mask)
        np.testing.assert_array_equal(result.pixels[..., :3], 0)
        np.testing.assert_array_equal(result.pixels[..., 3], image[..., 3])

    def test_ordered_channel_steps(self):
        config = replace(self.config, quantize='CHANNELS', channel_colors=2)
        result = core.process(self.image, config)
        self.assertAlmostEqual(float(result.pixels[..., :3].mean()), .25, places=6)
        self.assertEqual(set(np.unique(result.pixels[..., :3])), {0., 1.})

    def test_duplicate_palette_entries_do_not_suppress_dither(self):
        rgb = self.image[..., :3]
        duplicate = np.array([[0, 0, 0], [0, 0, 0], [1, 1, 1]], np.float32)
        texture = core.dither_texture(32, 32, self.config)
        result = core.ordered_palette(rgb, duplicate, texture, 1, np.ones((32, 32)))
        self.assertAlmostEqual(float(result.mean()), .25, places=6)

    def test_perceptual_output_is_a_palette_member(self):
        image = np.random.default_rng(4).random((16, 16, 4), dtype=np.float32)
        image[..., 3] = 1
        for space in ('LAB', 'OKLAB'):
            config = replace(self.config, palette_preset='C64', apply_space=space)
            result = core.process(image, config)
            expected = palettes.get_palette('C64')
            for color in np.unique(result.pixels[..., :3].reshape(-1, 3), axis=0):
                self.assertTrue(np.any(np.all(color == expected, axis=1)))

    def test_documented_reference_values(self):
        ntsc = palettes.get_palette('ATARI')
        self.assertEqual(ntsc.shape, (128, 3))
        np.testing.assert_array_equal(np.rint(ntsc[[0, 1, 8, 127]] * 255),
                                      [[0, 0, 0], [74, 74, 74], [72, 72, 0], [252, 224, 112]])
        nes = palettes.get_palette('NES')
        self.assertEqual(nes.shape, (64, 3))
        np.testing.assert_allclose(nes[1], [0, 1 / 7, 4 / 7])
        np.testing.assert_allclose(nes[32], 1)
        np.testing.assert_array_equal(np.rint(palettes.get_palette('C64')[[2, 5, 11]] * 255),
                                      [[129, 51, 56], [86, 172, 77], [74, 74, 74]])
        apple = palettes.get_palette('APPLE_LO')
        np.testing.assert_array_equal(np.rint(apple[[1, 5, 10]] * 255), [[227, 30, 96], [156, 156, 156], [156, 156, 156]])
        self.assertFalse(np.array_equal(palettes.get_palette('C64'), palettes.get_palette('C64_EARLY')))

    def test_color_space_roundtrip(self):
        colors = np.random.default_rng(41).random((100, 3), dtype=np.float32)
        for space in ('RGB', 'LAB', 'OKLAB'):
            np.testing.assert_allclose(core.from_space(core.to_space(colors, space), space), colors, atol=2e-5)

    def test_content_cache_invalidates_pixels_and_settings(self):
        images = {'source': self.image.copy()}
        key = processing.request_key(self.config, images)
        result = core.process(self.image, self.config, custom_palette=self.palette)
        processing.remember(key, result)
        self.assertIs(processing.cached(key), result)
        images['source'][0, 0, 0] = .75
        self.assertNotEqual(key, processing.request_key(self.config, images))
        self.assertNotEqual(key, processing.request_key(replace(self.config, strength=.5), {'source': self.image}))

    def test_background_worker_matches_direct_processing(self):
        config = replace(self.config, palette_preset='C64', apply_space='OKLAB')
        with tempfile.TemporaryDirectory(prefix='pixel4ever-worker-test-') as temporary:
            root = Path(temporary)
            np.savez(root / 'inputs.npz', source=self.image)
            (root / 'settings.json').write_text(json.dumps(asdict(config)))
            worker = Path(core.__file__).with_name('worker.py')
            completed = subprocess.run([sys.executable, str(worker), str(root)], capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            np.testing.assert_allclose(np.load(root / 'pixels.npy'), core.process(self.image, config).pixels)
            status = json.loads((root / 'status.json').read_text())
            self.assertEqual(status['fraction'], 1)
            self.assertEqual(status['stage'], 'Ready')

    def test_floyd_steinberg_worker_matches_direct_processing(self):
        config = replace(self.config, dither='FLOYD_STEINBERG', palette_preset='C64', apply_space='OKLAB')
        with tempfile.TemporaryDirectory(prefix='pixel4ever-floyd-worker-') as temporary:
            root = Path(temporary)
            np.savez(root / 'inputs.npz', source=self.image)
            (root / 'settings.json').write_text(json.dumps(asdict(config)))
            worker = Path(core.__file__).with_name('worker.py')
            completed = subprocess.run([sys.executable, str(worker), str(root)], capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            np.testing.assert_array_equal(np.load(root / 'pixels.npy'), core.process(self.image, config).pixels)
            self.assertEqual(json.loads((root / 'status.json').read_text())['fraction'], 1)

    def test_legacy_dither_mode_loads_diamond_tile(self):
        config = replace(self.config, dither='AMOGUS')
        tile = core.dither_texture(10, 10, config)[..., 0]
        expected = np.array([[.1, .1, .7, .1, .1], [.1, .7, .3, .7, .1],
                             [.7, .3, .1, .3, .7], [.1, .7, .3, .7, .1],
                             [.1, .1, .7, .1, .1]])
        np.testing.assert_allclose(tile, np.tile(expected, (2, 2)))

    def test_floyd_steinberg_matches_hand_calculated_serpentine_steps(self):
        # 0.25 gray, binary channels: a 2x4 scan has these exact decisions.
        image = np.ones((2, 4, 4), np.float32)
        image[..., :3] = .25
        config = replace(self.config, dither='FLOYD_STEINBERG', quantize='CHANNELS', channel_colors=2)
        result = core.process(image, config)
        np.testing.assert_array_equal(result.pixels[..., 0], [[0, 0, 0, 0], [1, 0, 1, 0]])

    def test_floyd_steinberg_preserves_average_and_palette(self):
        config = replace(self.config, dither='FLOYD_STEINBERG')
        result = core.process(self.image, config, custom_palette=self.palette)
        self.assertEqual(set(np.unique(result.pixels[..., :3])), {0., 1.})
        self.assertLess(abs(float(result.pixels[..., :3].mean()) - .25), .015)
        for space in ('LAB', 'OKLAB'):
            result = core.process(self.image, replace(config, palette_preset='C64', apply_space=space))
            colors = result.pixels[..., :3].reshape(-1, 3)
            expected = palettes.get_palette('C64')
            self.assertTrue(np.all(np.any(np.all(colors[:, None] == expected, axis=2), axis=1)))

    def test_floyd_steinberg_zero_strength_and_mask(self):
        config = replace(self.config, dither='FLOYD_STEINBERG')
        expected = core.process(self.image, replace(config, dither='NONE'), custom_palette=self.palette)
        zero = core.process(self.image, replace(config, strength=0), custom_palette=self.palette)
        np.testing.assert_array_equal(zero.pixels, expected.pixels)
        masked = core.process(self.image, replace(config, mask_type='CUSTOM', mask_strength=1),
                              custom_palette=self.palette, custom_mask=np.zeros((2, 2, 4), np.float32))
        np.testing.assert_array_equal(masked.pixels, expected.pixels)

    def test_floyd_steinberg_transparent_barrier_and_alpha(self):
        image = self.image.copy()
        image[:, 16, 3] = 0
        image[:, :16, 3] = .4
        config = replace(self.config, dither='FLOYD_STEINBERG', quantize='CHANNELS', channel_colors=2)
        result = core.process(image, config)
        np.testing.assert_array_equal(result.pixels[..., 3], image[..., 3])
        np.testing.assert_array_equal(result.pixels[:, 16, :3], 0)
        # Invisible RGB never sends error into visible neighbors.
        invisible = np.zeros((1, 2, 4), np.float32)
        invisible[0, 0, :3] = .4
        invisible[0, 1] = [.4, .4, .4, 1]
        out = core.process(invisible, config)
        np.testing.assert_array_equal(out.pixels[0, 1, :3], 0)

    def test_floyd_steinberg_grid_and_range_adaptive_levels(self):
        config = replace(self.config, dither='FLOYD_STEINBERG', palette_preset='AMIGA')
        result = core.process(self.image, config)
        np.testing.assert_allclose(result.pixels[..., :3] * 15, np.rint(result.pixels[..., :3] * 15), atol=2e-6)
        image = np.ones((16, 16, 4), np.float32)
        image[..., :3] = np.linspace(.2, .8, 16)[None, :, None]
        result = core.process(image, replace(config, quantize='CHANNELS', channel_colors=3, range_adaptive=True))
        self.assertTrue(np.all(np.isclose(result.pixels[..., :3, None], [.2, .5, .8], atol=1e-6).any(axis=-1)))

    def test_floyd_steinberg_rejects_unsupported_modes(self):
        for mode, profile in [('NONE', 'AMIGA'), ('PALETTE', 'CUSTOM_LUT')]:
            with self.assertRaisesRegex(ValueError, 'Floyd'):
                core.process(self.image, replace(self.config, dither='FLOYD_STEINBERG', quantize=mode, palette_preset=profile))


if __name__ == '__main__':
    unittest.main()
