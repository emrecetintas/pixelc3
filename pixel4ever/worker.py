# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated NumPy worker. Never imports bpy or touches the open Blender file."""
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np


def main(directory):
    package_dir = Path(__file__).resolve().parent
    name = '_pixel4ever_worker'
    spec = importlib.util.spec_from_file_location(name, package_dir / '__init__.py',
                                                submodule_search_locations=[str(package_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    core = __import__(name + '.core', fromlist=['Settings'])
    processing = __import__(name + '.processing', fromlist=['run'])
    root = Path(directory)
    last_write = 0.0

    def status(fraction, stage, force=False):
        nonlocal last_write
        now = time.monotonic()
        if force or now - last_write > .1:
            temporary = root / 'status.tmp'
            temporary.write_text(json.dumps({'fraction': fraction, 'stage': stage}))
            temporary.replace(root / 'status.json')
            last_write = now

    try:
        config = core.Settings(**json.loads((root / 'settings.json').read_text()))
        with np.load(root / 'inputs.npz', allow_pickle=False) as inputs:
            images = {key: inputs[key] for key in inputs.files}
        result = processing.run(config, images, status)
        status(.99, 'Transferring result', True)
        np.save(root / 'pixels.npy', result.pixels, allow_pickle=False)
        (root / 'result.json').write_text(json.dumps({'grid': result.grid, 'kind': result.kind,
                                                   'palette': result.palette.tolist() if result.palette is not None else None}))
        status(1.0, 'Ready', True)
    except Exception as error:
        (root / 'error.txt').write_text(f'{type(error).__name__}: {error}')
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main(sys.argv[1])
