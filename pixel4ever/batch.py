# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An explicit image queue and collision-safe PNG exports using one style."""
from pathlib import Path

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper


def add_image(settings, image):
    if image is None or image.source not in {'FILE', 'GENERATED'} or image.get('pixel4ever_generated'):
        return False
    if any(row.source == image for row in settings.batch_items):
        return False
    settings.batch_items.add().source = image
    settings.batch_index = len(settings.batch_items) - 1
    return True


def reserve_output(directory, name):
    """Reserve a unique path atomically; never replace an existing export."""
    stem = bpy.path.clean_name(Path(name).stem).strip(' .')[:160] or 'texture'
    number = 1
    while True:
        suffix = '' if number == 1 else f'_{number:03d}'
        path = Path(directory) / f'{stem}_pixelc3{suffix}.png'
        try:
            # Exclusive creation handles both prior exports and duplicate stems.
            with path.open('xb'):
                pass
            return path
        except FileExistsError:
            number += 1


def save_result(result, directory, name):
    from .addon import write_image
    image = None
    path = reserve_output(directory, name)
    try:
        image = write_image(result, 'PixelC3 batch export temporary', pack=False)
        image.file_format = 'PNG'
        image.filepath_raw = str(path)
        image.save()
        return str(path)
    except Exception:
        # Remove only the new reservation; older exports are never touched.
        path.unlink(missing_ok=True)
        raise
    finally:
        if image:
            bpy.data.images.remove(image)


class P4EVER_UL_batch(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.use_property_split = False
        row.prop(item, 'enabled', text='')
        row.prop(item, 'source', text='', emboss=False)


class P4EVER_OT_batch_add(bpy.types.Operator):
    bl_idname = 'pixel4ever.batch_add'
    bl_label = 'Add Images to Batch'
    bl_options = {'REGISTER', 'UNDO'}
    mode: EnumProperty(items=[('CURRENT', 'Current Source', ''), ('ALL', 'All Source Images', '')], default='CURRENT')

    def execute(self, context):
        s = context.scene.pixel4ever
        images = [s.source] if self.mode == 'CURRENT' else list(bpy.data.images)
        count = sum(add_image(s, image) for image in images)
        self.report({'INFO'}, f'Added {count} image(s); generated results and duplicates are excluded')
        return {'FINISHED'}


class P4EVER_OT_batch_load(bpy.types.Operator, ImportHelper):
    bl_idname = 'pixel4ever.batch_load'
    bl_label = 'Load Images into Batch'
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default='*.png;*.jpg;*.jpeg;*.tga;*.tif;*.tiff;*.bmp;*.exr;*.hdr', options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        paths = [Path(self.directory) / entry.name for entry in self.files] or [Path(self.filepath)]
        added, failed = 0, 0
        for path in paths:
            try:
                image = bpy.data.images.load(str(path), check_existing=True)
                added += add_image(context.scene.pixel4ever, image)
            except RuntimeError:
                failed += 1
        self.report({'WARNING'} if failed else {'INFO'}, f'Added {added} image(s), {failed} could not be loaded')
        return {'FINISHED'} if added or not failed else {'CANCELLED'}


class P4EVER_OT_batch_remove(bpy.types.Operator):
    bl_idname = 'pixel4ever.batch_remove'
    bl_label = 'Remove from Batch'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.pixel4ever
        if s.batch_items:
            s.batch_items.remove(min(max(0, s.batch_index), len(s.batch_items) - 1))
            s.batch_index = max(0, min(s.batch_index, len(s.batch_items) - 1))
        return {'FINISHED'}


class P4EVER_OT_batch_export(bpy.types.Operator):
    bl_idname = 'pixel4ever.batch_export'
    bl_label = 'Export Batch PNGs'
    bl_description = 'Apply current controls to checked images; export unique PNGs without changing source settings or materials'
    directory: StringProperty(subtype='DIR_PATH')
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        if not self.directory:
            self.directory = context.scene.pixel4ever.batch_directory
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        from . import jobs
        try:
            s = context.scene.pixel4ever
            sources = list(dict.fromkeys(row.source for row in s.batch_items if row.enabled and row.source))
            if not self.directory:
                raise ValueError('Choose an output folder')
            directory = Path(bpy.path.abspath(self.directory)).expanduser().resolve()
            jobs.start_batch(context.scene, sources, directory)
            s.batch_directory = str(directory)
            return {'FINISHED'}
        except (ValueError, OSError, RuntimeError, MemoryError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class P4EVER_OT_batch_report(bpy.types.Operator):
    bl_idname = 'pixel4ever.batch_report'
    bl_label = 'Batch Export Report'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        import json
        import textwrap
        report = json.loads(context.scene.pixel4ever.batch_report or '{}')
        self.layout.label(text=context.scene.pixel4ever.batch_summary)
        for entry in report.get('written', []):
            self.layout.label(text=Path(entry).name, icon='CHECKMARK')
        for entry in report.get('failed', []):
            for line in textwrap.wrap(entry, width=75):
                self.layout.label(text=line, icon='ERROR')

    def execute(self, context):
        return {'FINISHED'}


def draw(layout, settings):
    header, box = layout.panel('pixel4ever_batch', default_closed=True)
    header.label(text='Batch Export', icon='RENDERLAYERS')
    if box is None:
        return
    box.label(text='One look for every checked image')
    box.template_list('P4EVER_UL_batch', '', settings, 'batch_items', settings, 'batch_index', rows=3)
    row = box.row(align=True)
    row.operator('pixel4ever.batch_add', text='Current', icon='ADD').mode = 'CURRENT'
    row.operator('pixel4ever.batch_add', text='All Sources').mode = 'ALL'
    row.operator('pixel4ever.batch_remove', text='', icon='REMOVE')
    box.operator('pixel4ever.batch_load', text='Load Files…', icon='FILE_FOLDER')
    button = box.row()
    button.enabled = any(row.enabled and row.source for row in settings.batch_items)
    button.scale_y = 1.2
    button.operator('pixel4ever.batch_export', text='Export Checked Images', icon='EXPORT')
    if settings.batch_summary:
        box.label(text=settings.batch_summary)
        box.operator('pixel4ever.batch_report', text='View Report', icon='TEXT')
        if settings.batch_directory:
            box.operator('wm.path_open', text='Open Output Folder', icon='FILE_FOLDER').filepath = settings.batch_directory


CLASSES = (P4EVER_UL_batch, P4EVER_OT_batch_add, P4EVER_OT_batch_load, P4EVER_OT_batch_remove,
           P4EVER_OT_batch_export, P4EVER_OT_batch_report)
