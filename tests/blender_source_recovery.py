# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise source recovery in a disposable scene inside the running Blender.

From Blender's Python Console, use runpy.run_path(path), then call the returned
module's run(addon) with the enabled PixelC3 add-on module.
"""
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

import bpy


def rejected(operator, filepath, message):
    try:
        response = operator(filepath=str(filepath))
    except RuntimeError as error:
        assert message in str(error), str(error)
    else:
        assert response == {'CANCELLED'}, response


def run(addon):
    example = Path(__file__).resolve().parents[1] / 'examples' / 'source.png'
    scene = bpy.data.scenes.new('PixelC3 source recovery test')
    material = bpy.data.materials.new('PixelC3 source recovery test')
    material.use_nodes = True
    source_node = material.node_tree.nodes.new('ShaderNodeTexImage')
    result_node = material.node_tree.nodes.new('ShaderNodeTexImage')
    settings = scene.pixel4ever
    source = result = packed_source = None
    image_names = set(bpy.data.images.keys())
    checks = []
    try:
        with TemporaryDirectory(prefix='pixel4ever-recovery-') as directory:
            root = Path(directory)
            original = root / 'original.png'
            copyfile(example, original)
            source = bpy.data.images.load(str(original))
            if bpy.data.filepath:
                source.filepath_raw = bpy.path.relpath(str(original))
            source_node.image = settings.source = source
            source_path = source.filepath_raw
            settings.output_size = 'PIXELS'
            settings.pixel_count = 16
            assert addon.source_status(source) == 'READY'
            result = result_node.image = addon.generate(scene)
            packed = result.packed_file.data
            assert packed.startswith(b'\x89PNG\r\n\x1a\n')

            moved = original.rename(root / 'moved.png')
            assert addon.source_status(source) == 'MISSING'
            assert addon.source_status(result) == 'READY'
            checks.append('Moved external source is detected and its packed result stays readable')

            settings.pixel_count = 32
            recipe = addon.presets.recipe(settings)
            metadata = (result.filepath_raw, tuple(result.size))
            export = bpy.ops.pixel4ever.export_packed_result
            relink = bpy.ops.pixel4ever.relink_source
            with bpy.context.temp_override(scene=scene):
                assert export(filepath=str(root / 'stored')) == {'FINISHED'}
                assert (root / 'stored.png').read_bytes() == packed
                assert settings.dirty and settings.result == result
                assert (result.filepath_raw, tuple(result.size)) == metadata
                rejected(export, original, 'keep the source image file')
                assert not original.exists()
                checks.append('Packed export is byte-identical with pending edits and protects the source path')

                invalid = root / 'invalid.png'
                invalid.write_bytes(b'Invalid test image')
                rejected(relink, invalid, 'image')
                assert source.filepath_raw == source_path and addon.source_status(source) == 'MISSING'
                assert settings.source == source and settings.result == result
                checks.append('Unreadable replacement leaves the prior source binding intact')

                assert relink(filepath=str(moved)) == {'FINISHED'}
                assert addon.source_status(source) == 'READY'
                assert source_node.image == settings.source == source
                assert result_node.image == settings.result == result
                assert addon.presets.recipe(settings) == recipe
                assert settings.dirty and result.packed_file.data == packed
                assert addon.generate(scene) == result
                assert result_node.image == result and not settings.dirty
                assert min(result.size) == 32
                checks.append('Relinking preserves the look, result and material image references through regeneration')

            packed_path = root / 'packed-input.png'
            copyfile(example, packed_path)
            packed_source = bpy.data.images.load(str(packed_path))
            packed_source.pack()
            packed_path.unlink()
            assert addon.source_status(packed_source) == 'READY'
            addon.read_image(packed_source)
            checks.append('Packed input remains usable when its external file is absent')
            assert set(bpy.data.images.keys()) - image_names == {source.name, result.name, packed_source.name}
        return checks
    finally:
        bpy.data.materials.remove(material)
        bpy.data.scenes.remove(scene)
        for image in (result, source, packed_source):
            if image is not None:
                bpy.data.images.remove(image)
