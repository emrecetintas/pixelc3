# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Serial background workers with progress, cancellation and batch exports."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import bpy
import numpy as np
from . import core, processing

_jobs = {}
_ready = {}


def python_binary():
    prefix = Path(sys.prefix)
    candidates = [prefix / 'bin' / f'python{sys.version_info.major}.{sys.version_info.minor}',
                  prefix / 'bin' / 'python.exe', prefix / 'python.exe']
    if Path(sys.executable).name.lower().startswith('python'):
        candidates.insert(0, Path(sys.executable))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError('Cannot find Blender’s bundled Python for background generation')


def active(scene):
    return scene.as_pointer() in _jobs


def _launch(scene, config, images, key, area=None, batch=None):
    from . import addon
    hit = processing.cached(key)
    job = {'scene': scene, 'source': scene.pixel4ever.source, 'config': config,
           'scene_config': addon.settings_from(scene.pixel4ever), 'key': key,
           'process': None, 'temp': None, 'log': None, 'cached': hit,
           'started': time.perf_counter(), 'area': area, 'identity': uuid.uuid4().hex,
           'batch': batch}
    try:
        if hit is None:
            job['temp'] = tempfile.TemporaryDirectory(prefix='pixel4ever-job-')
            root = Path(job['temp'].name)
            np.savez(root / 'inputs.npz', **images)
            (root / 'settings.json').write_text(json.dumps(asdict(config)))
            job['log'] = (root / 'worker.log').open('w')
            environment = dict(os.environ)
            environment.update(PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2')
            job['process'] = subprocess.Popen([python_binary(), str(Path(__file__).with_name('worker.py')), str(root)],
                                              stdout=job['log'], stderr=job['log'], env=environment)
        _jobs[scene.as_pointer()] = job
        s = scene.pixel4ever
        s.busy = True
        _progress(job, 0, 'Starting generation')
        if batch is None:
            s.last_error = ''
        if not bpy.app.timers.is_registered(poll):
            bpy.app.timers.register(poll, first_interval=.1)
    except Exception:
        _dispose(job)
        raise


def start(scene, area=None):
    from . import addon
    if active(scene):
        raise RuntimeError('Generation or batch export is already running for this scene')
    addon._pending.pop(scene.name, None)
    config, images, key = addon.prepare(scene)
    hit = processing.cached(key)
    if hit is not None:
        image = addon.commit_result(scene, hit, config, time.perf_counter(), cache_hit=True)
        if area and area.type == 'IMAGE_EDITOR':
            area.spaces.active.image = image
        return False
    _launch(scene, config, images, key, area)
    return True


def _progress(job, fraction, stage):
    s = job['scene'].pixel4ever
    batch = job['batch']
    if batch:
        total = len(batch['sources'])
        s.progress = (batch['index'] + fraction) / total
        name = batch['names'][batch['index']]
        s.progress_stage = f"{batch['index'] + 1}/{total} · {name} · {stage}"
    else:
        s.progress = fraction
        s.progress_stage = stage


def _dispose(job):
    process = job['process']
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    if job['log'] and not job['log'].closed:
        job['log'].close()
    if job['temp']:
        job['temp'].cleanup()


def _batch_report(scene, batch, status):
    s = scene.pixel4ever
    written, failed = len(batch['written']), len(batch['failed'])
    s.batch_summary = f'{status}: {written} exported, {failed} failed'
    s.batch_report = json.dumps({'status': status, 'directory': str(batch['directory']),
                                 'written': batch['written'], 'failed': batch['failed'],
                                 'remaining': len(batch['sources']) - batch['index']})


def _next_batch(scene, batch):
    from . import addon
    while batch['index'] < len(batch['sources']):
        source = batch['sources'][batch['index']]
        try:
            config, images, key = addon.prepare(scene, for_export=True, source=source)
            _launch(scene, config, images, key, batch=batch)
            return
        except (ValueError, OSError, RuntimeError, MemoryError, ReferenceError) as error:
            batch['failed'].append(f"{batch['names'][batch['index']]}: {error}")
            batch['index'] += 1
    s = scene.pixel4ever
    s.busy = False
    s.progress = 1
    s.progress_stage = 'Batch finished'
    _batch_report(scene, batch, 'Finished')


def start_batch(scene, sources, directory):
    from . import addon
    if active(scene):
        raise RuntimeError('Generation or batch export is already running for this scene')
    if not sources:
        raise ValueError('Add and check at least one source image in Batch Export')
    if any(image.get('pixel4ever_generated') for image in sources):
        raise ValueError('Batch entries must be original sources, not generated results')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise ValueError('Choose an output folder')
    addon._pending.pop(scene.name, None)
    batch = {'sources': list(sources), 'names': [image.name for image in sources],
             'directory': directory, 'index': 0, 'written': [], 'failed': []}
    scene.pixel4ever.batch_directory = str(directory)
    scene.pixel4ever.batch_summary = f'Exporting {len(sources)} images'
    _next_batch(scene, batch)


def cancel(scene, message='Generation cancelled'):
    job = _jobs.pop(scene.as_pointer(), None)
    if job:
        _dispose(job)
        if job['batch']:
            _batch_report(scene, job['batch'], 'Cancelled')
    s = scene.pixel4ever
    s.busy = False
    s.progress = 0
    s.progress_stage = message
    if not job or job['batch'] is None:
        s.dirty = True


def take_ready(identity):
    return _ready.pop(identity)


def poll():
    from . import addon, batch as batch_io
    for pointer, job in list(_jobs.items()):
        scene = job['scene']
        try:
            s = scene.pixel4ever
            if s.source != job['source'] or addon.settings_from(s) != job['scene_config']:
                cancel(scene, 'Settings changed — generate again')
                continue
            result = job['cached']
            if result is None:
                root = Path(job['temp'].name)
                status_path = root / 'status.json'
                if status_path.exists():
                    status = json.loads(status_path.read_text())
                    _progress(job, status['fraction'], status['stage'])
                code = job['process'].poll()
                if code is None:
                    continue
                if code:
                    error = root / 'error.txt'
                    raise RuntimeError(error.read_text() if error.exists() else 'The background process stopped unexpectedly')
                pixels = np.load(root / 'pixels.npy', allow_pickle=False)
                meta = json.loads((root / 'result.json').read_text())
                palette = np.asarray(meta['palette'], np.float32) if meta['palette'] is not None else None
                result = core.Result(pixels, palette, tuple(meta['grid']), meta['kind'])
                processing.remember(job['key'], result)
            _jobs.pop(pointer, None)
            if job['batch']:
                batch = job['batch']
                path = batch_io.save_result(result, batch['directory'], batch['names'][batch['index']])
                batch['written'].append(path)
                batch['index'] += 1
                _dispose(job)
                _next_batch(scene, batch)
            else:
                _ready[job['identity']] = (job, result)
                bpy.ops.pixel4ever.commit_job(identity=job['identity'])
                s.busy = False
                s.progress = 1
                s.progress_stage = 'Ready'
                _dispose(job)
        except (ValueError, OSError, RuntimeError, MemoryError, ReferenceError, KeyError) as error:
            _jobs.pop(pointer, None)
            _ready.pop(job['identity'], None)
            _dispose(job)
            try:
                if job['batch']:
                    batch = job['batch']
                    batch['failed'].append(f"{batch['names'][batch['index']]}: {error}")
                    batch['index'] += 1
                    _next_batch(scene, batch)
                else:
                    scene.pixel4ever.busy = False
                    scene.pixel4ever.last_error = str(error)
                    scene.pixel4ever.dirty = True
            except ReferenceError:
                pass
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                area.tag_redraw()
    return .1 if _jobs else None


def shutdown():
    for job in list(_jobs.values()):
        try:
            cancel(job['scene'])
        except ReferenceError:
            _dispose(job)
    _jobs.clear()
    _ready.clear()
    if bpy.app.timers.is_registered(poll):
        bpy.app.timers.unregister(poll)
