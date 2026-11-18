#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build Blender install archives from the redistributable source files."""
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'pixel4ever'
DESTINATION = ROOT / 'dist'
MANIFEST = SOURCE / 'blender_manifest.toml'
MODULES = (
    '__init__.py', 'addon.py', 'batch.py', 'core.py', 'jobs.py', 'palettes.py',
    'presets.py', 'processing.py', 'ui.py', 'worker.py',
)
DOCUMENTATION = (
    'README.md', 'LICENSE', 'NOTICE', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'docs/PALETTE_REFERENCES.md', 'examples/source.png', 'examples/pixelc3.png',
)


def main():
    DESTINATION.mkdir(exist_ok=True)
    with MANIFEST.open('rb') as stream:
        version = tomllib.load(stream)['version']
    for mode in ('extension', 'legacy'):
        target = DESTINATION / f'pixelc3-{version}-{mode}.zip'
        package_dir = '' if mode == 'extension' else 'pixel4ever/'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for filename in MODULES:
                archive.write(SOURCE / filename, package_dir + filename)
            if mode == 'extension':
                archive.write(MANIFEST, MANIFEST.name)
            for filename in DOCUMENTATION:
                archive.write(ROOT / filename, package_dir + filename)
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None
        print(target)


if __name__ == '__main__':
    main()
