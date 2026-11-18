# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Named digital and reference-display palettes. See docs/PALETTE_REFERENCES.md.

Atari NTSC/SECAM reference data: Stella, Copyright (c) 1995-2026 Bradford
W. Mott, Stephen Anthony and the Stella Team, GPL-2.0-or-later.
https://github.com/stella-emu/stella/blob/master/src/common/PaletteHandler.cxx
The remaining transforms are independent implementations of documented values.
"""
from functools import lru_cache
import numpy as np


def hex_colors(value):
    return np.array([[int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
                     for c in value.split()], dtype=np.float32)


def rgb_cube(levels):
    return np.stack(np.meshgrid(levels, levels, levels, indexing="ij"), -1).reshape(-1, 3).astype(np.float32)


PALETTE_ITEMS = (
    ("AMIGA", "Amiga OCS / RGB444 (Digital)", "4096 ideal digital RGB colors; no analog monitor simulation", 0),
    ("APPLE_LO", "Apple II LoRes / Munafo NTSC", "Robert Munafo's published NTSC-to-RGB reference; duplicate gray entries retained", 1),
    ("APPLE_HI", "Apple II HiRes / Munafo NTSC", "Six HiRes colors from the same Munafo NTSC reference", 2),
    ("APPLE_IIGS", "Apple IIgs / Mega II RGB", "Documented 16-color RGB444 compatibility palette, TechNote 63", 12),
    ("ATARI", "Atari 2600 / Stella NTSC", "Exact 128 RGB entries of Stella's standard NTSC reference palette", 3),
    ("ATARI_SECAM", "Atari 2600 / Stella SECAM", "Eight RGB colors from Stella's SECAM reference palette", 13),
    ("C64", "Commodore 64 / Colodore PAL", "Colodore model, common VIC-II revision; brightness/contrast/saturation 50/100/50", 4),
    ("C64_EARLY", "Commodore 64 / Early VIC-II PAL", "Colodore model with the first revision's luminance levels", 14),
    ("NES", "NES / 2C03 RGB", "NESdev's documented 64-entry RGB PPU DAC table; not a 2C02 composite palette", 5),
    ("GAMEBOY", "Game Boy / LCD Green (Stylized)", "Popular four-shade green interpretation; not a measured LCD reference", 6),
    ("GB_GRAY", "Game Boy / 2-bit Gray (Digital)", "Four equally spaced digital gray shades, not an LCD simulation", 15),
    ("GBC", "Game Boy Color / RGB555 (Digital)", "32768 ideal digital RGB colors; no CGB LCD color correction", 7),
    ("MASTER", "Master System / RGB222 (Digital)", "64 ideal digital RGB colors; no analog monitor simulation", 8),
    ("WEB", "Web Color / RGB216", "The standard 216-color web-safe RGB cube", 9),
    ("CUSTOM_PALETTE", "Custom Palette Image", "Read up to 256 distinct visible colors from an image", 10),
    ("CUSTOM_LUT", "Custom Hald LUT", "Hald layout, RGB order with red varying fastest", 11),
)


_ATARI_NTSC = """
000000 4a4a4a 6f6f6f 8e8e8e aaaaaa c0c0c0 d6d6d6 ececec
484800 69690f 86861d a2a22a bbbb35 d2d240 e8e84a fcfc54
7c2c00 904811 a26221 b47a30 c3903d d2a44a dfb755 ecc860
901c00 a33915 b55328 c66c3a d5824a e39759 f0aa67 fcbc74
940000 a71a1a b83232 c84848 d65c5c e46f6f f08080 fc9090
840064 97197a a8308f b846a2 c659b3 d46cc3 e07cd2 ec8ce0
500084 68199a 7d30ad 9246c0 a459d0 b56ce0 c57cee d48cfc
140090 331aa3 4e32b5 6848c6 7f5cd5 956fe3 a980f0 bc90fc
000094 181aa7 2d32b8 4248c8 545cd6 656fe4 7580f0 8490fc
001c88 183b9d 2d57b0 4272c2 548ad2 65a0e1 75b5ef 84c8fc
003064 185080 2d6d98 4288b0 54a0c5 65b7d9 75cceb 84e0fc
004030 18624e 2d8169 429e82 54b899 65d1ae 75e7c2 84fcd4
004400 1a661a 328432 48a048 5cba5c 6fd26f 80e880 90fc90
143c00 355f18 527e2d 6e9c42 87b754 9ed065 b4e775 c8fc84
303800 505916 6d762b 88923e a0ab4f b7c25f ccd86e e0ec7c
482c00 694d14 866a26 a28638 bb9f47 d2b656 e8cc63 fce070
"""
_NES_2C03 = """
333 014 006 326 403 503 510 420 320 120 031 040 022 000 000 000
555 036 027 407 507 704 700 630 430 140 040 053 044 000 000 000
777 357 447 637 707 737 740 750 660 360 070 276 077 000 000 000
777 567 657 757 747 755 764 772 773 572 473 276 467 000 000 000
"""
_APPLE_NTSC = """000000 e31e60 604ebd ff44fd 00a360 9c9c9c 14cffd d0c3ff
607203 ff6a3c 9c9c9c ffa0d0 14f53c d0dd8d 72ffd0 ffffff"""
_APPLE_IIGS = "000 d03 009 d2d 072 555 22f 6af 850 f60 aaa f98 1d0 ff0 4f9 fff"


def colodore(early=False):
    """Pepto/Colodore PAL reference, default display controls (50,100,50)."""
    luma = np.array([0, 32, 10, 20, 12, 16, 8, 24, 12, 8, 16, 10, 15, 24, 15, 20], np.float64)
    if early:
        luma = np.array([0, 32, 8, 24, 16, 16, 8, 24, 16, 8, 16, 8, 16, 24, 16, 24], np.float64)
    sectors = np.array([0, 0, 4, 12, 2, 10, 15, 7, 5, 6, 4, 0, 0, 10, 15, 0])
    angles = np.deg2rad(11.25 + sectors * 22.5)
    u = np.where(sectors == 0, 0, np.cos(angles) * 40) * 1.2
    v = np.where(sectors == 0, 0, np.sin(angles) * 40) * 1.2
    y = luma * 8 * 1.2
    encoded = np.stack((y + 1.140 * v, y - .396 * u - .581 * v, y + 2.029 * u), -1)
    corrected = np.clip(encoded / 255, 0, 1) ** (2.8 / 2.2)
    return np.floor(corrected * 255 + .5).astype(np.float32) / 255


@lru_cache(maxsize=24)
def get_palette(name):
    if name in {"AMIGA", "GBC", "MASTER", "WEB"}:
        levels = {"AMIGA": 16, "GBC": 32, "MASTER": 4, "WEB": 6}[name]
        result = rgb_cube(np.linspace(0, 1, levels))
    elif name == "APPLE_LO":
        result = hex_colors(_APPLE_NTSC)
    elif name == "APPLE_HI":
        result = hex_colors(_APPLE_NTSC)[[0, 3, 6, 9, 12, 15]]
    elif name == "APPLE_IIGS":
        result = np.array([[int(c, 16) / 15 for c in triplet] for triplet in _APPLE_IIGS.split()], np.float32)
    elif name == "ATARI":
        result = hex_colors(_ATARI_NTSC)
    elif name == "ATARI_SECAM":
        result = hex_colors("000000 2121ff f03c79 ff50ff 7fff00 7fffff ffff3f ffffff")
    elif name in {"C64", "C64_EARLY"}:
        result = colodore(name == "C64_EARLY")
    elif name == "NES":
        result = np.array([[int(c) / 7 for c in triplet] for triplet in _NES_2C03.split()], np.float32)
    elif name == "GAMEBOY":
        result = hex_colors("0f380f 306230 8bac0f 9bbc0f")
    elif name == "GB_GRAY":
        result = np.repeat(np.linspace(0, 1, 4, dtype=np.float32)[:, None], 3, axis=1)
    else:
        raise ValueError(f"Unknown built-in palette: {name}")
    result.flags.writeable = False
    return result
