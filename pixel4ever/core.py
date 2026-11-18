# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic NumPy image processing. Images are H x W x RGBA, straight sRGB.

Array row zero is the top row. The Blender adapter flips its buffers.
"""
from dataclasses import dataclass
from functools import lru_cache
import numpy as np
from .palettes import get_palette

MAX_PIXELS = 16_777_216  # 4K square, including Hald-16 LUT export


@dataclass
class Settings:
    separate_xy: bool = False
    pixel_count: int = 256
    pixel_x: int = 256
    pixel_y: int = 256
    downscale: str = "NEAREST"
    preview_filter: str = "NONE"
    dither: str = "NONE"
    dither_method: str = "BLEND"
    custom_resolution: tuple = (8, 8)
    blend_mode: str = "SOFT_LIGHT"
    grayscale_dither: bool = False
    strength: float = 0.25
    saturation: float = 0.5
    mask_type: str = "NONE"
    mask_strength: float = 0.0
    mask_gamma: float = 1.0
    preview_mask: bool = False
    mask_weights: tuple = (1.0, 1.0, 0.8, 0.6, 0.4, 0.2, 0.2)
    quantize: str = "NONE"
    initialize: str = "1"
    creation_space: str = "RGB"
    palette_preset: str = "AMIGA"
    apply_space: str = "RGB"
    quality: int = 2
    colors: int = 32
    gamma: float = 1.0
    force_colors: str = "NONE"
    output_palette: bool = False
    output_lut: bool = False
    range_adaptive: bool = False
    channel_mode: str = "COLORS"
    channel_colors: int = 256
    channel_bits: int = 8
    default_lut: bool = False
    seed: int = 0
    output_size: str = "SOURCE"


@dataclass
class Result:
    pixels: np.ndarray
    palette: np.ndarray | None
    grid: tuple
    kind: str = "TEXTURE"


def image_array(value):
    a = np.asarray(value, dtype=np.float32)
    if a.ndim != 3 or a.shape[2] not in (3, 4) or min(a.shape[:2]) < 1:
        raise ValueError("Expected a nonempty H × W image with RGB or RGBA channels")
    if a.shape[0] * a.shape[1] > MAX_PIXELS:
        raise ValueError("Images are limited to 16,777,216 pixels (4096 × 4096)")
    if not np.isfinite(a).all():
        raise ValueError("Image contains NaN or infinite values")
    if a.shape[2] == 3:
        a = np.concatenate((a, np.ones((*a.shape[:2], 1), np.float32)), -1)
    return np.clip(a, 0, 1)


def srgb_to_linear(rgb):
    x = np.maximum(np.asarray(rgb), 0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb):
    x = np.maximum(np.asarray(rgb), 0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


_OK1 = np.array([[.4122214708, .5363325363, .0514459929],
                 [.2119034982, .6806995451, .1073969566],
                 [.0883024619, .2817188376, .6299787005]], dtype=np.float32)
_OK2 = np.array([[.2104542553, .7936177850, -.0040720468],
                 [1.9779984951, -2.4285922050, .4505937099],
                 [.0259040371, .7827717662, -.8086757660]], dtype=np.float32)
_XYZ = np.array([[.4124564, .3575761, .1804375],
                 [.2126729, .7151522, .0721750],
                 [.0193339, .1191920, .9503041]], dtype=np.float32)
_WHITE = np.array([.95047, 1.0, 1.08883], dtype=np.float32)


def to_space(rgb, space):
    x = np.asarray(rgb, dtype=np.float32)
    if space == "RGB":
        return x
    linear = srgb_to_linear(x)
    if space == "OKLAB":
        return np.cbrt(linear @ _OK1.T) @ _OK2.T
    if space == "LAB":
        xyz = (linear @ _XYZ.T) / _WHITE
        f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
        return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                         200 * (f[..., 1] - f[..., 2])), -1) / 100
    raise ValueError(f"Unknown color space: {space}")


def from_space(value, space):
    x = np.asarray(value, dtype=np.float32)
    if space == "RGB":
        return np.clip(x, 0, 1)
    if space == "OKLAB":
        linear = (x @ np.linalg.inv(_OK2).T) ** 3 @ np.linalg.inv(_OK1).T
    elif space == "LAB":
        x = x * 100
        fy = (x[..., 0] + 16) / 116
        f = np.stack((fy + x[..., 1] / 500, fy, fy - x[..., 2] / 200), -1)
        xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * _WHITE
        linear = xyz @ np.linalg.inv(_XYZ).T
    else:
        raise ValueError(f"Unknown color space: {space}")
    return np.clip(linear_to_srgb(linear), 0, 1)


def grid_size(width, height, settings):
    if settings.separate_xy:
        x, y = settings.pixel_x, settings.pixel_y
    else:
        count = max(1, int(settings.pixel_count))
        unit = min(width, height) / count
        x, y = round(width / unit), round(height / unit)
    # Counts above source resolution are clamped rather than creating empty cells.
    return max(1, min(width, int(x))), max(1, min(height, int(y)))


def resize(image, width, height, mode="NEAREST"):
    """Center-aligned resampling with clamped edges and premultiplied alpha."""
    h, w = image.shape[:2]
    width, height = int(width), int(height)
    if min(width, height) < 1 or width * height > MAX_PIXELS:
        raise ValueError("Invalid or excessively large output resolution")
    if (width, height) == (w, h):
        return image.copy()
    xs = (np.arange(width, dtype=np.float32) + .5) * w / width - .5
    ys = (np.arange(height, dtype=np.float32) + .5) * h / height - .5
    if mode == "NEAREST":
        xi = np.clip(np.floor(xs + .5).astype(int), 0, w - 1)
        yi = np.clip(np.floor(ys + .5).astype(int), 0, h - 1)
        return image[yi[:, None], xi[None, :]].copy()
    if mode not in {"BILINEAR", "N64"}:
        raise ValueError(f"Unknown resampling mode: {mode}")
    # Process row stripes so a 4K preview doesn't create many full-size temporaries.
    out = np.empty((height, width, 4), np.float32)
    x0 = np.floor(xs).astype(int)
    fx = (xs - x0)[None, :, None]
    xa, xb = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    source = image.copy()
    source[..., :3] *= source[..., 3:4]
    for start in range(0, height, 128):
        sy = ys[start:start + 128]
        y0 = np.floor(sy).astype(int)
        fy = (sy - y0)[:, None, None]
        ya, yb = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
        a, b = source[ya[:, None], xa], source[ya[:, None], xb]
        c, d = source[yb[:, None], xa], source[yb[:, None], xb]
        if mode == "N64":
            part = np.where(fx + fy <= 1, a + fx * (b - a) + fy * (c - a),
                            d + (1 - fx) * (c - d) + (1 - fy) * (b - d))
        else:
            part = (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy
        alpha = part[..., 3:4]
        part[..., :3] = np.divide(part[..., :3], alpha, out=np.zeros_like(part[..., :3]), where=alpha > 1e-8)
        out[start:start + len(sy)] = part
    return np.clip(out, 0, 1)


def nearest_indices(points, centers):
    """Bound distance matrices to ~8 MB; never allocate pixels × palette × RGB."""
    points = np.asarray(points, np.float32).reshape(-1, 3)
    centers = np.asarray(centers, np.float32).reshape(-1, 3)
    if not len(centers):
        raise ValueError("Palette is empty")
    result = np.empty(len(points), np.int32)
    step = max(16, min(8192, 2_000_000 // len(centers)))
    norm = np.sum(centers * centers, axis=1)
    for begin in range(0, len(points), step):
        p = points[begin:begin + step]
        distances = np.sum(p * p, axis=1)[:, None] + norm - 2 * (p @ centers.T)
        result[begin:begin + len(p)] = np.argmin(distances, axis=1)
    return result


def apply_palette(rgb, palette, space="RGB", progress=None):
    shape = rgb.shape
    flat = rgb.reshape(-1, 3)
    centers = to_space(palette, space)
    out = np.empty_like(flat)
    for start in range(0, len(flat), 65536):
        part = flat[start:start + 65536]
        out[start:start + len(part)] = palette[nearest_indices(to_space(part, space), centers)]
        if progress:
            progress((start + len(part)) / len(flat))
    return out.reshape(shape)


def ordered_palette(rgb, palette, texture, strength, mask, space="RGB", progress=None):
    """Dither between the two nearest palette colors using their projected mix.

    Every result is a palette member, including with partially masked dithering.
    At zero strength this is exactly nearest-palette assignment.
    """
    palette = np.unique(palette, axis=0)
    if len(palette) < 2:
        return np.broadcast_to(palette[0], rgb.shape).copy()
    points = rgb.reshape(-1, 3)
    thresholds = texture[..., 0].ravel()
    amounts = (np.clip(strength, 0, 1) * mask).ravel()
    centers = to_space(palette, space)
    norms = np.sum(centers * centers, axis=1)
    step = max(16, min(8192, 2_000_000 // len(centers)))
    output = np.empty_like(points)
    for begin in range(0, len(points), step):
        p = to_space(points[begin:begin + step], space)
        distance = np.sum(p * p, axis=1)[:, None] + norms - 2 * (p @ centers.T)
        rows = np.arange(len(p))
        first = distance.argmin(axis=1)
        distance[rows, first] = np.inf
        second = distance.argmin(axis=1)
        a, b = centers[first], centers[second]
        direction = b - a
        denominator = np.sum(direction * direction, axis=1)
        fraction = np.divide(np.sum((p - a) * direction, axis=1), denominator,
                             out=np.zeros(len(p), np.float32), where=denominator > 1e-12)
        amount = np.clip(fraction, 0, 1) * amounts[begin:begin + len(p)]
        ids = np.where(thresholds[begin:begin + len(p)] < amount, second, first)
        output[begin:begin + len(p)] = palette[ids]
        if progress:
            progress((begin + len(p)) / len(points))
    return output.reshape(rgb.shape)


def palette_from_image(image):
    a = image_array(image)
    visible = a[..., :3][a[..., 3] > .01]
    if not len(visible):
        raise ValueError("Custom palette image is fully transparent")
    # Palette images are swatches, not photographs. Reject excessive colors explicitly.
    colors = np.unique(np.round(visible * 255).astype(np.uint8), axis=0)
    if len(colors) > 256:
        raise ValueError("Custom palette must contain at most 256 distinct visible colors")
    return colors.astype(np.float32) / 255


def generate_palette(image, settings, progress=None):
    a = image_array(image)
    pixels = a[..., :3].reshape(-1, 3)
    alpha = a[..., 3].ravel()
    pixels = pixels[alpha > .01]
    if not len(pixels):
        return np.zeros((1, 3), np.float32)
    rng = np.random.default_rng(settings.seed)
    limit = 4096 + max(0, min(8, settings.quality)) * 1024
    if len(pixels) > limit:
        pixels = pixels[rng.choice(len(pixels), limit, replace=False)]
    unique = np.unique(np.round(pixels * 255).astype(np.uint8), axis=0).astype(np.float32) / 255
    k = max(2, min(256, int(settings.colors)))
    fixed = []
    if settings.force_colors == "BLACK_WHITE":
        fixed = [np.zeros(3), np.ones(3)]
    elif settings.force_colors == "EXTREMES":
        brightness = srgb_to_linear(pixels) @ np.array([.2126, .7152, .0722])
        fixed = [pixels[np.argmin(brightness)], pixels[np.argmax(brightness)]]
    elif settings.force_colors != "NONE":
        raise ValueError("Unknown forced-color mode")
    gamma = max(.1, min(4, settings.gamma))
    encode = lambda x: to_space(np.power(x, 1 / gamma), settings.creation_space)
    if len(unique) <= k and not fixed:
        return unique
    data = encode(pixels)
    fixed_count = len(fixed)
    centers = [c for c in encode(np.asarray(fixed).reshape(-1, 3))] if fixed else []
    if not centers:
        centers.append(data[rng.integers(len(data))])
    # Seeded initialization keeps palette training reproducible.
    minimum = np.full(len(data), np.inf, dtype=np.float32)
    for c in centers:
        minimum = np.minimum(minimum, np.sum((data - c) ** 2, axis=1))
    while len(centers) < k:
        if settings.initialize == "2":
            idx = int(np.argmax(minimum))
        elif settings.initialize == "3":
            order = np.argsort(np.sum(data, axis=1), kind="stable")
            idx = order[min(len(data) - 1, int((len(centers) + .5) * len(data) / k))]
        elif settings.initialize == "4":
            idx = int(rng.integers(len(data)))
        else:
            probabilities = minimum.astype(np.float64)
            total = probabilities.sum()
            idx = int(rng.choice(len(data), p=probabilities / total)) if total > 1e-12 else int(rng.integers(len(data)))
        c = data[idx]
        centers.append(c)
        minimum = np.minimum(minimum, np.sum((data - c) ** 2, axis=1))
    centers = np.asarray(centers, np.float32)
    iterations = 2 + max(0, min(8, settings.quality)) * 2
    for iteration in range(iterations):
        labels = nearest_indices(data, centers)
        counts = np.bincount(labels, minlength=k)
        updated = centers.copy()
        for channel in range(3):
            sums = np.bincount(labels, weights=data[:, channel], minlength=k)
            np.divide(sums, counts, out=updated[:, channel], where=counts > 0)
        updated[:fixed_count] = centers[:fixed_count]
        if np.max(np.abs(updated - centers)) < 1e-5:
            centers = updated
            break
        centers = updated
        if progress:
            progress((iteration + 1) / iterations)
    palette = np.power(from_space(centers, settings.creation_space), gamma)
    if fixed:
        palette[:fixed_count] = fixed
    return np.unique(np.round(np.clip(palette, 0, 1) * 255).astype(np.uint8), axis=0).astype(np.float32) / 255


def bayer_matrix(size=4):
    if size < 2 or size & (size - 1):
        raise ValueError("Bayer size must be a power of two, at least two")
    a = np.zeros((1, 1), np.float32)
    while len(a) < size:
        a = np.block([[4 * a, 4 * a + 2], [4 * a + 3, 4 * a + 1]])
    return (a + .5) / (size * size)


@lru_cache(maxsize=8)
def blue_noise_tile(seed):
    """High-pass spectral rank noise, an approximation rather than void-and-cluster."""
    rng = np.random.default_rng(seed)
    data = rng.random((64, 64))
    fy, fx = np.meshgrid(np.fft.fftfreq(64), np.fft.fftfreq(64), indexing="ij")
    high = np.fft.ifft2(np.fft.fft2(data) * np.sqrt(fx * fx + fy * fy)).real
    order = np.argsort(high, axis=None)
    rank = np.empty(4096, np.float32)
    rank[order] = (np.arange(4096) + .5) / 4096
    return rank.reshape(64, 64)


def dither_texture(width, height, settings, custom=None):
    kind = settings.dither
    rng = np.random.default_rng(settings.seed)
    if kind == "WHITE":
        result = rng.random((height, width, 3), dtype=np.float32)
    elif kind == "NONE":
        result = np.full((height, width, 3), .5, np.float32)
    else:
        if kind == "BAYER":
            tile = bayer_matrix(4)[..., None]
        elif kind == "BLUE":
            tile = np.stack([blue_noise_tile(settings.seed + c) for c in range(3)], -1)
        elif kind == "PATTERN":
            tile = np.array([[.125, .625], [.875, .375]], np.float32)[..., None]
        elif kind == "AMOGUS":
            # Keep the saved-style identifier for the 5 × 5 pattern slot.
            tile = np.array([[.1, .1, .7, .1, .1], [.1, .7, .3, .7, .1],
                             [.7, .3, .1, .3, .7], [.1, .7, .3, .7, .1],
                             [.1, .1, .7, .1, .1]], np.float32)[..., None]
        elif kind == "CUSTOM":
            if custom is None:
                raise ValueError("Select a Custom Dither Pattern image")
            ex, ey = settings.custom_resolution
            tile = resize(image_array(custom), 2 ** int(ex), 2 ** int(ey))[..., :3]
        else:
            raise ValueError(f"Unknown dither type: {kind}")
        th, tw = tile.shape[:2]
        y, x = np.arange(height) % th, np.arange(width) % tw
        result = tile[y[:, None], x[None, :]]
        if result.shape[2] == 1:
            result = np.repeat(result, 3, axis=2)
    if settings.grayscale_dither:
        return np.repeat(result[..., :1], 3, -1)
    gray = np.mean(result, axis=2, keepdims=True)
    return gray + (result - gray) * settings.saturation


def _box_blur(a, radius):
    if radius == 0:
        return a
    p = np.pad(a, ((radius, radius), (radius, radius)), mode="edge")
    s = np.pad(p, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    k = radius * 2 + 1
    return (s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]) / (k * k)


def dither_mask(image, settings, custom=None):
    h, w = image.shape[:2]
    if settings.mask_type == "NONE":
        return np.ones((h, w), np.float32)
    if settings.mask_type == "CUSTOM":
        if custom is None:
            raise ValueError("Select a Custom Dither Mask image")
        mask = resize(image_array(custom), w, h, "BILINEAR")[..., 0]
    elif settings.mask_type in {"EDGES", "FLATS"}:
        luma = image[..., :3] @ np.array([.2126, .7152, .0722], np.float32)
        weighted = np.zeros((h, w), np.float32)
        total = 0.0
        for radius, weight in zip((32, 16, 8, 4, 2, 1, 0), settings.mask_weights):
            if weight <= 0:
                continue
            blur = _box_blur(luma, radius)
            dx = np.abs(np.diff(blur, axis=1, append=blur[:, -1:]))
            dy = np.abs(np.diff(blur, axis=0, append=blur[-1:, :]))
            weighted = np.maximum(weighted, np.clip((dx + dy) * (radius + 1) * 4, 0, 1) * weight)
            total = max(total, weight)
        mask = weighted / max(total, 1e-8)
        if settings.mask_type == "FLATS":
            mask = 1 - mask
    else:
        raise ValueError(f"Unknown dither mask type: {settings.mask_type}")
    mask = np.clip(mask, 0, 1) ** (1 / max(.1, settings.mask_gamma))
    return (1 - settings.mask_strength) + settings.mask_strength * mask


def blend_dither(rgb, texture, settings, mask):
    linear = settings.blend_mode.endswith("_LINEAR")
    a, b = (srgb_to_linear(rgb), srgb_to_linear(texture)) if linear else (rgb, texture)
    if settings.blend_mode.startswith("OVERLAY"):
        mixed = np.where(a <= .5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    elif settings.blend_mode.startswith("SOFT_LIGHT"):
        d = np.where(a <= .25, ((16 * a - 12) * a + 4) * a, np.sqrt(a))
        mixed = np.where(b <= .5, a - (1 - 2 * b) * a * (1 - a), a + (2 * b - 1) * (d - a))
    else:
        raise ValueError(f"Unknown dither blend mode: {settings.blend_mode}")
    strength = np.clip(settings.strength * mask[..., None], 0, 1)
    out = a * (1 - strength) + mixed * strength
    return np.clip(linear_to_srgb(out) if linear else out, 0, 1)


def quantize_channels(rgb, settings, texture=None, mask=None):
    levels = 2 ** settings.channel_bits if settings.channel_mode == "BITS" else settings.channel_colors
    levels = max(2, min(256, int(levels)))
    threshold = .5
    if texture is not None:
        threshold = .5 + (texture - .5) * settings.strength * mask[..., None]
    if settings.range_adaptive:
        low, high = rgb.min(axis=(0, 1)), rgb.max(axis=(0, 1))
        span = high - low
        normalized = np.divide(rgb - low, span, out=np.zeros_like(rgb), where=span > 1e-8)
        return np.clip(np.floor(normalized * (levels - 1) + threshold), 0, levels - 1) / (levels - 1) * span + low
    return np.clip(np.floor(np.clip(rgb, 0, 1) * (levels - 1) + threshold), 0, levels - 1) / (levels - 1)


def floyd_steinberg(rgb, alpha, settings, palette=None, mask=None, progress=None):
    """Serpentine Floyd–Steinberg diffusion in sRGB, retaining palette members.

    Rows alternate direction. Errors use 7/16, 3/16, 5/16, 1/16 weights,
    mirrored on reverse rows. Strength scales propagated error; masks gate
    incoming/outgoing error. Fully transparent pixels stop propagation.
    """
    height, width = rgb.shape[:2]
    mask = np.ones((height, width), np.float32) if mask is None else mask
    if palette is None:
        levels = 2 ** settings.channel_bits if settings.channel_mode == 'BITS' else settings.channel_colors
        levels = max(2, min(256, int(levels))) - 1
        low = rgb.min(axis=(0, 1)) if settings.range_adaptive else np.zeros(3, np.float32)
        span = rgb.max(axis=(0, 1)) - low if settings.range_adaptive else np.ones(3, np.float32)
        inverse = np.divide(levels, span, out=np.zeros(3, np.float32), where=span > 1e-8)
        step = span / levels
    else:
        palette = np.asarray(palette, np.float32)
        centers = to_space(palette, settings.apply_space)
    output = np.empty_like(rgb)
    current = np.zeros((width + 2, 3), np.float32)
    following = np.zeros_like(current)
    strength = float(np.clip(settings.strength, 0, 1))
    for y in range(height):
        direction = 1 if y % 2 == 0 else -1
        columns = range(width) if direction == 1 else range(width - 1, -1, -1)
        for x in columns:
            if alpha[y, x] <= 1e-8:
                output[y, x] = 0
                continue
            index = x + 1
            value = rgb[y, x] + current[index] * mask[y, x]
            if palette is None:
                q = np.minimum(np.maximum(np.floor((value - low) * inverse + .5), 0), levels) * step + low
            else:
                point = to_space(np.minimum(np.maximum(value, 0), 1), settings.apply_space)
                q = palette[np.argmin(np.sum((centers - point) ** 2, axis=1))]
            output[y, x] = q
            error = (value - q) * (strength * mask[y, x] * alpha[y, x] / 16)
            current[index + direction] += error * 7
            following[index - direction] += error * 3
            following[index] += error * 5
            following[index + direction] += error
        current, following = following, current
        following.fill(0)
        if progress:
            progress((y + 1) / height)
    return output


def apply_hald(rgb, lut):
    """Hald level N: side N³, cube side N², red-fastest RGB indexing.

    LUT rows are top-down. Nearest lookup preserves palette colors.
    """
    h, w = lut.shape[:2]
    level = round(w ** (1 / 3))
    if w != h or level < 2 or level ** 3 != w:
        raise ValueError("LUT must be a square Hald image (e.g. 64, 512 or 4096 px)")
    cube = level * level
    q = np.floor(np.clip(rgb, 0, 1) * (cube - 1) + .5).astype(np.int32)
    index = q[..., 0] + cube * q[..., 1] + cube * cube * q[..., 2]
    return lut[..., :3].reshape(-1, 3)[index]


def make_hald(palette=None, space="RGB", level=16, progress=None):
    side, cube = level ** 3, level ** 2
    if level < 2 or side * side > MAX_PIXELS:
        raise ValueError("Hald level must be between 2 and 16")
    output = np.ones((side * side, 4), np.float32)
    for start in range(0, side * side, 65536):
        ids = np.arange(start, min(side * side, start + 65536))
        rgb = np.stack((ids % cube, (ids // cube) % cube, ids // (cube * cube)), -1).astype(np.float32) / (cube - 1)
        output[start:start + len(ids), :3] = apply_palette(rgb, palette, space) if palette is not None else rgb
        if progress:
            progress((start + len(ids)) / (side * side))
    return output.reshape(side, side, 4)


def process(image, settings=None, *, custom_dither=None, custom_mask=None,
            custom_palette=None, custom_lut=None, progress=None):
    settings = settings or Settings()
    def report(fraction, stage):
        if progress:
            progress(fraction, stage)
    report(.01, "Reading pixels")
    source = image_array(image)
    height, width = source.shape[:2]
    gw, gh = grid_size(width, height, settings)
    mode = "NEAREST" if settings.downscale == "NEAREST" else "BILINEAR"
    small = resize(source, gw, gh, mode)
    report(.08, "Sampling pixel grid")
    if settings.default_lut and settings.quantize == "PALETTE":
        return Result(make_hald(progress=lambda f: report(.1 + .88 * f, "Building identity LUT")), None, (gw, gh), "LUT")
    palette = None
    if settings.quantize == "GENERATE":
        report(.1, "Generating palette")
        palette = generate_palette(small, settings, lambda f: report(.1 + .3 * f, "Generating palette"))
    elif settings.quantize == "PALETTE" and settings.palette_preset != "CUSTOM_LUT":
        if settings.palette_preset == "CUSTOM_PALETTE":
            if custom_palette is None:
                raise ValueError("Select a Custom Palette image")
            palette = palette_from_image(custom_palette)
        else:
            palette = get_palette(settings.palette_preset)
    if settings.quantize == "GENERATE" and settings.output_lut:
        return Result(make_hald(palette, settings.apply_space, progress=lambda f: report(.4 + .58 * f, "Building palette LUT")), palette, (gw, gh), "LUT")
    if settings.quantize == "GENERATE" and settings.output_palette:
        swatch = np.ones((16, 16, 4), np.float32)
        swatch[..., :3] = palette[0]
        swatch.reshape(-1, 4)[:len(palette), :3] = palette
        return Result(swatch, palette, (gw, gh), "PALETTE")
    diffusion = settings.dither == 'FLOYD_STEINBERG'
    if diffusion and settings.quantize != 'CHANNELS' and palette is None:
        raise ValueError('Floyd–Steinberg needs Per Channel, Generate Custom Palette, or a palette profile; custom Hald LUTs are not supported')
    report(.42, "Computing dither mask")
    mask = dither_mask(small, settings, custom_mask) if settings.dither != "NONE" else np.ones((gh, gw), np.float32)
    if settings.dither != "NONE" and settings.preview_mask:
        small[..., :3] = mask[..., None]
    elif diffusion:
        levels = {'AMIGA': 16, 'GBC': 32, 'MASTER': 4, 'WEB': 6}.get(settings.palette_preset)
        config = settings
        diffusion_palette = palette
        if settings.quantize == 'PALETTE' and settings.apply_space == 'RGB' and levels:
            config = Settings(channel_colors=levels, strength=settings.strength)
            diffusion_palette = None
        small[..., :3] = floyd_steinberg(small[..., :3], small[..., 3], config, diffusion_palette, mask,
                                        lambda f: report(.5 + .38 * f, 'Floyd–Steinberg dithering'))
    else:
        aware = settings.dither != "NONE" and settings.dither_method == "QUANTIZATION"
        texture = None
        if settings.dither != "NONE":
            texture = dither_texture(gw, gh, settings, custom_dither)
            if not aware or (palette is None and settings.quantize != "CHANNELS"):
                small[..., :3] = blend_dither(small[..., :3], texture, settings, mask)
        report(.5, "Applying colors")
        if settings.quantize == "CHANNELS":
            small[..., :3] = quantize_channels(small[..., :3], settings, texture if aware else None, mask)
        elif palette is not None:
            # Hardware RGB grids can be quantized directly in RGB space, avoiding
            # unnecessary searches through palettes of 4096 or 32768 entries.
            levels = {"AMIGA": 16, "GBC": 32, "MASTER": 4, "WEB": 6}.get(settings.palette_preset)
            if settings.quantize == "PALETTE" and settings.apply_space == "RGB" and levels:
                grid_config = Settings(channel_colors=levels, strength=settings.strength)
                small[..., :3] = quantize_channels(small[..., :3], grid_config, texture if aware else None, mask)
            elif aware:
                small[..., :3] = ordered_palette(small[..., :3], palette, texture, settings.strength,
                                                mask, settings.apply_space,
                                                lambda f: report(.5 + .38 * f, "Dithering palette colors"))
            else:
                small[..., :3] = apply_palette(small[..., :3], palette, settings.apply_space,
                                              lambda f: report(.5 + .38 * f, "Applying palette"))
        elif settings.quantize == "PALETTE" and settings.palette_preset == "CUSTOM_LUT":
            if custom_lut is None:
                raise ValueError("Select a Custom Hald LUT image")
            small[..., :3] = apply_hald(small[..., :3], image_array(custom_lut))
        elif settings.quantize != "NONE":
            raise ValueError(f"Unknown quantization mode: {settings.quantize}")
    small[..., :3][small[..., 3] <= 1e-8] = 0
    report(.9, "Preparing output")
    if settings.output_size == "SOURCE":
        interpolation = {"NONE": "NEAREST", "BILINEAR": "BILINEAR", "N64": "N64"}[settings.preview_filter]
        pixels = resize(small, width, height, interpolation)
    else:
        pixels = small
    report(1.0, "Ready")
    return Result(np.clip(pixels, 0, 1).astype(np.float32), palette, (gw, gh))
