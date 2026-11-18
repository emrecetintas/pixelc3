# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Content-addressed results shared by synchronous and background generation."""
from collections import OrderedDict
from dataclasses import asdict
import hashlib
import json
import numpy as np
from . import core

_cache = OrderedDict()
_cache_bytes = 0
CACHE_LIMIT = 128 * 1024 * 1024


def request_key(config, images):
    digest = hashlib.blake2b(digest_size=24)
    digest.update(json.dumps(asdict(config), sort_keys=True).encode())
    for name, array in sorted(images.items()):
        value = np.ascontiguousarray(array, dtype=np.float32)
        digest.update(name.encode())
        digest.update(str(value.shape).encode())
        digest.update(memoryview(value).cast('B'))
    return digest.hexdigest()


def cached(key):
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
    return value


def remember(key, result):
    global _cache_bytes
    size = result.pixels.nbytes + (result.palette.nbytes if result.palette is not None else 0)
    if size > CACHE_LIMIT:
        return
    old = _cache.pop(key, None)
    if old:
        _cache_bytes -= old.pixels.nbytes + (old.palette.nbytes if old.palette is not None else 0)
    while _cache and _cache_bytes + size > CACHE_LIMIT:
        _, removed = _cache.popitem(last=False)
        _cache_bytes -= removed.pixels.nbytes + (removed.palette.nbytes if removed.palette is not None else 0)
    _cache[key] = result
    _cache_bytes += size


def clear():
    global _cache_bytes
    _cache.clear()
    _cache_bytes = 0


def run(config, images, progress=None):
    return core.process(images['source'], config, progress=progress,
                        **{k: v for k, v in images.items() if k != 'source'})
