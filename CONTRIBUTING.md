# Contributing

For a bug report, include your Blender version, operating system, PixelC3
version, and steps to reproduce. A small shareable image or exported style JSON
can help reproduce a processing problem.

## Test and build

Use Python 3.11 or newer. The standalone processing tests need NumPy. Blender
provides NumPy for the installed extension.

```sh
python3 -m venv .venv
# Activate .venv for your shell before running the remaining commands.
python -m pip install "numpy>=1.26,<3"
python -m unittest discover -s tests -p test_processing.py
python tools/build.py
blender --command extension validate dist/pixelc3-0.4.3-extension.zip
```

The processing tests cover palette values, dithering, resampling, caching and
the standalone worker. For UI, image datablock, and project workflow changes,
install the extension archive in Blender and run the relevant integration
script from `tests/` in the Python Console. The script headers describe their
entry points. Timer-driven checks report their results in a local test log.

To generate the procedural example, open a new Blender project. In the Python
Console, run `import runpy` followed by
`runpy.run_path("/path/to/pixel4ever/tools/blender_demo.py")`. The script saves
its output under `exports/demo/`.

Source changes are distributed under [GPL-3.0-or-later](LICENSE). Include
provenance and license details for any palette data or assets you add.
