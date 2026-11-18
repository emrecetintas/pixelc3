# Palette references

Profiles identify a particular digital representation or display model. An
exact match to a named table does not mean every original console, CRT or LCD
would display those same sRGB values. Spatial restrictions (tile palettes,
attribute blocks, artifact fringes, simultaneous-color limits) are not emulated.

| Profile | Reference and definition |
| --- | --- |
| Amiga OCS / RGB444 (Digital) | Full 16-level-per-channel RGB cube, normalized as channel/15. This describes the digital color register domain; no CRT correction. [Amiga Hardware Reference Manual, color registers](https://www.amigadev.elowar.com/read/ADCD_2.1/Hardware_Manual_guide/node0067.html). |
| Apple II LoRes / Munafo NTSC | Robert Munafo's published RGB values for all 16 COLOR indices. Both gray indices map to 156/156/156. This is his NTSC conversion model, not a universal composite-video result. [Original calculation and table](https://www.mrob.com/pub/xapple2/colors.html). |
| Apple II HiRes / Munafo NTSC | The six documented HCOLOR colors from that same reference: black, purple, blue, orange, green, white. |
| Apple IIgs / Mega II RGB | The 16 RGB444 compatibility colors listed in the IIgs table, using channel/15. The register triples are 000, d03, 009, d2d, 072, 555, 22f, 6af, 850, f60, aaa, f98, 1d0, ff0, 4f9, fff. [Table and TechNote 63 link](https://www.mrob.com/pub/xapple2/colors.html). |
| Atari 2600 / Stella NTSC | All 128 standard NTSC RGB entries from Stella's `PaletteHandler::ourNTSCPalette`; the unused alternating placeholders in its 256-entry internal array are omitted. [Stella source](https://github.com/stella-emu/stella/blob/master/src/common/PaletteHandler.cxx), [palette format documentation](https://stella-emu.github.io/docs/index.html#Palette). This reproduces the emulator reference table, not all NTSC televisions. |
| Atari 2600 / Stella SECAM | Stella's eight distinct standard SECAM RGB entries. Same source and license as NTSC. |
| Commodore 64 / Colodore PAL | Independent implementation of Colodore's published equations, common VIC-II luminance revision, brightness 50, contrast 100, saturation 50; PAL gamma 2.8 to target gamma 2.2, rounded to RGB8. [Colodore model, equations and settings](https://www.pepto.de/projects/colorvic/). |
| Commodore 64 / Early VIC-II PAL | The same model using its first-revision luminance table. |
| NES / 2C03 RGB | All 64 DAC triplets from NESdev's 2C03/2C05 table, normalized as channel/7 (rounded to RGB8 when writing PNG). Duplicate colors are retained in the reference array. This is an RGB PPU profile, not a 2C02 NTSC or 2C07 PAL composite profile. [NESdev table](https://www.nesdev.org/wiki/PPU_palettes#2C03_and_2C05). |
| Game Boy / LCD Green (Stylized) | The previous four-green aesthetic preset, explicitly labeled stylized. No measured LCD-fidelity claim. |
| Game Boy / 2-bit Gray (Digital) | Four abstract digital gray values: 0, 85, 170, 255. This is not a measured green DMG LCD. [Game Boy palette indices](https://gbdev.io/pandocs/Palettes.html). |
| Game Boy Color / RGB555 (Digital) | Full 32-level-per-channel digital RGB cube, normalized as channel/31. No CGB LCD pigment/gamma mixing correction. [Pan Docs, CGB palettes and display behavior](https://gbdev.io/pandocs/Palettes.html). |
| Master System / RGB222 (Digital) | Full four-level-per-channel digital RGB cube, normalized as channel/3. No analog display model. [Sega documentation, Color RAM](https://www.smspower.org/Development/SMSOfficialDocs), [hardware variations including nonlinear blue](https://www.smspower.org/Development/Palette). |
| Web Color / RGB216 | Full six-level-per-channel web-safe RGB cube: 00, 33, 66, 99, cc, ff. |

The shipped values and equations live in `pixel4ever/palettes.py`. See
[NOTICE](../NOTICE) for Atari table attribution and licensing.

Existing outputs remain intact after upgrading. Regenerating an Apple II,
Atari, C64 or NES preset from version 0.1.x adopts the named reference profile
and can change its colors. Game Boy green and the digital RGB grids retain
their previous definitions.
