# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable, validated JSON recipes and a user preset shelf (no executable presets)."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import uuid

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

_items = [('NONE', 'Choose a saved style', 'Save your current processing settings')]
_signature = None


def preset_directory(create=False):
    path = bpy.utils.user_resource('SCRIPTS', path='presets/pixel4ever', create=create)
    if not path:
        raise RuntimeError('Blender’s user preset directory is unavailable')
    return Path(path)


def preset_items():
    global _items, _signature
    try:
        root = preset_directory()
        files = sorted(root.glob('*.json')) if root.exists() else []
        signature = tuple((p.name, p.stat().st_mtime_ns) for p in files)
        if signature != _signature:
            _items = [('NONE', 'Choose a saved style', 'Save your current processing settings')]
            for index, path in enumerate(files, 1):
                try:
                    if path.stat().st_size > 262144:
                        continue
                    name = json.loads(path.read_text()).get('name', path.stem)
                    _items.append((path.stem, str(name), 'Load these saved processing settings', index))
                except (OSError, ValueError, AttributeError):
                    continue
            _signature = signature
    except (OSError, RuntimeError):
        if _signature is not None:
            _items = [('NONE', 'Choose a saved style', 'Save your current processing settings')]
            _signature = None
    # Keep these strings alive: Blender's dynamic enum stores references to them.
    return _items


def recipe(settings, name='PixelC3 settings'):
    from .addon import settings_from
    values = asdict(settings_from(settings))
    values['input_encoding'] = settings.input_encoding
    return {'schema_version': 1, 'addon': 'pixel4ever', 'name': name, 'settings': values}


def validate(settings, document):
    if not isinstance(document, dict) or document.get('schema_version') != 1 or document.get('addon') != 'pixel4ever':
        raise ValueError('This is not a supported PixelC3 JSON preset')
    values = document.get('settings')
    if not isinstance(values, dict):
        raise ValueError('Preset settings must be an object')
    allowed = set(recipe(settings)['settings'])
    unknown = set(values) - allowed
    if unknown:
        raise ValueError('Unknown preset settings: ' + ', '.join(sorted(unknown)))
    for key, value in values.items():
        prop = settings.bl_rna.properties[key]
        sequence = value if getattr(prop, 'is_array', False) else [value]
        if getattr(prop, 'is_array', False):
            if not isinstance(value, (list, tuple)) or len(value) != prop.array_length:
                raise ValueError(f'{prop.name} requires {prop.array_length} values')
        for item in sequence:
            if prop.type == 'BOOLEAN':
                good = type(item) is bool
            elif prop.type == 'INT':
                good = type(item) is int and prop.hard_min <= item <= prop.hard_max
            elif prop.type == 'FLOAT':
                good = type(item) in (int, float) and math.isfinite(item) and prop.hard_min <= item <= prop.hard_max
            elif prop.type == 'ENUM':
                good = isinstance(item, str) and item in prop.enum_items.keys()
            else:
                good = False
            if not good:
                raise ValueError(f'Invalid value for {prop.name}')
    return values


def apply(settings, document):
    from .addon import queue_update, suspend_updates
    values = validate(settings, document)
    # Validate everything before mutating any setting. Source/result pointers and
    # custom input images aren't part of the portable recipe.
    with suspend_updates(settings):
        for key, value in values.items():
            setattr(settings, key, value)
    queue_update(settings, bpy.context)


def load_file(settings, path):
    path = Path(path)
    if path.stat().st_size > 262144:
        raise ValueError('Preset file exceeds the 256 KiB limit')
    document = json.loads(path.read_text())
    apply(settings, document)
    return document


class P4EVER_OT_save_preset(bpy.types.Operator):
    bl_idname = 'pixel4ever.save_preset'
    bl_label = 'Save Preset'
    bl_description = 'Save processing controls for use in any Blender project'
    name: StringProperty(name='Preset Name', default='My Pixel Style')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            name = self.name.strip()
            if not name:
                raise ValueError('Enter a preset name')
            root = preset_directory(create=True)
            # Unique files preserve older presets with the same display name.
            key = bpy.path.clean_name(name)[:64] + '_' + uuid.uuid4().hex[:8]
            path = root / (key + '.json')
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(recipe(context.scene.pixel4ever, name), indent=2) + '\n')
            temporary.replace(path)
            preset_items()
            context.scene.pixel4ever.user_preset = key
            self.report({'INFO'}, f'Saved preset: {name}')
            return {'FINISHED'}
        except (OSError, ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class P4EVER_OT_load_preset(bpy.types.Operator):
    bl_idname = 'pixel4ever.load_preset'
    bl_label = 'Load Preset'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            key = context.scene.pixel4ever.user_preset
            if key == 'NONE' or key not in {item[0] for item in preset_items()}:
                raise ValueError('Choose a saved style first')
            load_file(context.scene.pixel4ever, preset_directory() / (key + '.json'))
            return {'FINISHED'}
        except (OSError, ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class P4EVER_OT_export_preset(bpy.types.Operator, ExportHelper):
    bl_idname = 'pixel4ever.export_preset'
    bl_label = 'Export Settings JSON'
    filename_ext = '.json'
    filter_glob: StringProperty(default='*.json', options={'HIDDEN'})

    def execute(self, context):
        try:
            Path(bpy.path.ensure_ext(self.filepath, '.json')).write_text(json.dumps(recipe(context.scene.pixel4ever), indent=2) + '\n')
            return {'FINISHED'}
        except OSError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class P4EVER_OT_import_preset(bpy.types.Operator, ImportHelper):
    bl_idname = 'pixel4ever.import_preset'
    bl_label = 'Import Settings JSON'
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default='*.json', options={'HIDDEN'})

    def execute(self, context):
        try:
            load_file(context.scene.pixel4ever, self.filepath)
            return {'FINISHED'}
        except (OSError, ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


CLASSES = (P4EVER_OT_save_preset, P4EVER_OT_load_preset, P4EVER_OT_export_preset, P4EVER_OT_import_preset)
