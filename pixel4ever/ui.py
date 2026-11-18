# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PixelC3's workspace: shared source/result controls, Look, Styles, Export.

Presentation is separate from processing and portable recipes. Drawing this UI
never changes a processing setting or starts an operation.
"""
import textwrap

from . import batch, core
from .addon import can_relink, source_status


def note(layout, text, icon='NONE', width=35):
    for index, line in enumerate(textwrap.wrap(text, width=width)):
        layout.label(text=line, icon=icon if index == 0 else 'NONE')


def section(layout, key, title, icon='NONE', closed=False, reset=None):
    header, body = layout.panel('pixel4ever_' + key, default_closed=closed)
    header.label(text=title, icon=icon)
    if reset:
        header.row().operator('pixel4ever.reset_defaults', text='', icon='LOOP_BACK').group = reset
    return body


def output_kind(settings):
    if settings.quantize == 'GENERATE':
        if settings.output_lut:
            return 'LUT'
        if settings.output_palette:
            return 'PALETTE'
    if settings.quantize == 'PALETTE' and settings.default_lut:
        return 'LUT'
    return 'TEXTURE'


def grid_summary(settings):
    width, height = settings.source.size
    # grid_size reads only these four fields; no pixel buffers are accessed.
    x, y = core.grid_size(width, height, settings)
    return f'{x} × {y} pixel grid'


def draw_source(layout, s, status):
    card = layout.box()
    title = card.row(align=True)
    title.label(text='TEXTURE LAB', icon='IMAGE_DATA')
    card.prop(s, 'source', text='')
    row = card.row(align=True)
    row.operator('pixel4ever.load_image', text='Open Image', icon='FILE_FOLDER')
    row.operator('pixel4ever.use_image', text='Use Current', icon='EYEDROPPER')
    if status == 'READY':
        card.label(text=f'{s.source.size[0]} × {s.source.size[1]}  ·  {s.source.colorspace_settings.name}')
    elif status == 'EMPTY':
        card.label(text='Open an image to get started.')
    else:
        message = {'MISSING': 'Source Missing', 'UNREADABLE': 'Source Unreadable',
                   'UNSUPPORTED': 'Unsupported Source'}[status]
        warning = card.row()
        warning.alert = True
        warning.label(text=message, icon='ERROR')
        if can_relink(s.source):
            card.operator('pixel4ever.relink_source', icon='FILE_FOLDER')
        if s.result and s.result.packed_file:
            card.operator('pixel4ever.export_packed_result', icon='EXPORT')


def draw_run(layout, s, ready):
    row = layout.row(align=True)
    row.use_property_split = False
    row.scale_y = 1.35
    run = row.row(align=True)
    run.enabled = ready
    label = {'TEXTURE': 'Generate Texture', 'PALETTE': 'Generate Palette', 'LUT': 'Generate LUT'}[output_kind(s)]
    run.operator('pixel4ever.generate', text=label, icon='FILE_REFRESH')
    auto = row.row(align=True)
    auto.enabled = ready
    auto.prop(s, 'auto_update', text='Auto', toggle=True)
    if ready and s.last_error:
        error = layout.box()
        error.alert = True
        note(error, s.last_error, 'ERROR')
    elif ready:
        if s.dirty or not s.result:
            layout.label(text='Changes ready to generate' if s.result else 'Ready for your first result', icon='TIME')
        else:
            layout.label(text='Result ready', icon='CHECKMARK')
            if s.last_summary:
                note(layout, s.last_summary)
    if s.result or s.source:
        row = layout.row(align=True)
        source = row.row(align=True)
        source.enabled = ready
        source.operator('pixel4ever.show_image', text='Source').target = 'SOURCE'
        result = row.row(align=True)
        result.enabled = s.result is not None
        result.operator('pixel4ever.show_image', text='Result').target = 'RESULT'
        compare = row.row(align=True)
        compare.enabled = bool(ready and s.result and not s.dirty and s.result.get('pixel4ever_kind') == 'TEXTURE')
        compare.operator('pixel4ever.compare', text='Compare', icon='IMAGE_DATA')


def draw_grid(layout, s, ready):
    box = section(layout, 'look_grid', 'Pixel Grid', 'SNAP_GRID', reset='DIMENSIONS')
    if box is None:
        return
    box.prop(s, 'separate_xy', text='Independent X / Y')
    if s.separate_xy:
        box.prop(s, 'pixel_x', text='Across')
        box.prop(s, 'pixel_y', text='Down')
    else:
        box.prop(s, 'pixel_count', text='Short Edge')
    if ready:
        box.label(text=grid_summary(s))
    box.prop(s, 'downscale', text='Sampling')


def draw_color(layout, s):
    box = section(layout, 'look_color', 'Color', 'COLOR', reset='QUANTIZATION')
    if box is None:
        return
    box.prop(s, 'quantize', text='Mode')
    if s.quantize == 'NONE':
        note(box, 'Keep the source colors.')
    elif s.quantize == 'GENERATE':
        box.prop(s, 'colors', text='Palette Size')
        box.prop(s, 'apply_space', text='Match Colors')
        advanced = section(box, 'palette_tuning', 'Palette Tuning', closed=True)
        if advanced:
            advanced.prop(s, 'quality', text='Refinement')
            advanced.prop(s, 'creation_space', text='Build In')
            advanced.prop(s, 'initialize', text='Starting Colors')
            advanced.prop(s, 'gamma', text='Dark Detail')
            advanced.prop(s, 'force_colors', text='Keep Extremes')
    elif s.quantize == 'CHANNELS':
        box.prop(s, 'channel_mode', text='Units')
        box.prop(s, 'channel_bits' if s.channel_mode == 'BITS' else 'channel_colors', text='Per Channel')
        box.prop(s, 'range_adaptive', text='Fit Source Range')
    elif s.quantize == 'PALETTE':
        box.prop(s, 'palette_preset', text='Profile')
        if s.palette_preset == 'CUSTOM_LUT':
            box.prop(s, 'custom_lut', text='LUT Image')
        else:
            if s.palette_preset == 'CUSTOM_PALETTE':
                box.prop(s, 'custom_palette', text='Swatch Image')
            box.prop(s, 'apply_space', text='Match Colors')


def draw_dither(layout, s):
    box = section(layout, 'look_dither', 'Dither', 'TEXTURE', reset='DITHERING')
    if box is None:
        return
    box.prop(s, 'dither', text='Pattern')
    if s.dither == 'NONE':
        return
    diffusion = s.dither == 'FLOYD_STEINBERG'
    if not diffusion:
        box.prop(s, 'dither_method', text='Method')
    box.prop(s, 'strength', text='Diffusion' if diffusion else 'Amount', slider=True)
    if s.dither == 'CUSTOM':
        box.prop(s, 'custom_dither', text='Pattern Image')
        box.prop(s, 'custom_resolution', text='Tile Size (2ⁿ)')
    unsupported = s.quantize == 'NONE' or (s.quantize == 'PALETTE' and s.palette_preset == 'CUSTOM_LUT')
    if diffusion and unsupported:
        note(box, 'Choose a palette or channel levels in Color to use error diffusion.', 'ERROR')
    elif s.dither_method == 'QUANTIZATION' and unsupported and not diffusion:
        note(box, 'This color mode uses texture blending.', 'INFO')
    if not diffusion:
        details = section(box, 'dither_mix', 'Pattern Mixing', closed=True)
        if details:
            if s.dither_method == 'BLEND' or unsupported:
                details.prop(s, 'blend_mode', text='Blend')
            details.prop(s, 'grayscale_dither', text='Monochrome Pattern')
            if not s.grayscale_dither:
                details.prop(s, 'saturation', text='Color Variation', slider=True)
    mask = section(box, 'dither_mask', 'Where to Dither', closed=True)
    if mask:
        mask.prop(s, 'mask_type', text='Coverage')
        if s.mask_type != 'NONE':
            if s.mask_type == 'CUSTOM':
                mask.prop(s, 'custom_mask', text='Mask Image')
            mask.prop(s, 'mask_strength', text='Influence', slider=True)
            mask.prop(s, 'mask_gamma', text='Falloff')
            mask.prop(s, 'preview_mask', text='Show Mask')
            if s.mask_type != 'CUSTOM':
                mask.prop(s, 'show_mask_controls', text='Detail Weights')
                if s.show_mask_controls:
                    for index, label in enumerate(('Broadest', 'Broad', 'Large', 'Medium', 'Fine', 'Sharp', 'Pixel')):
                        mask.prop(s, 'mask_weights', index=index, text=label, slider=True)


def draw_look(layout, s, ready):
    draw_grid(layout, s, ready)
    draw_color(layout, s)
    draw_dither(layout, s)
    technical = section(layout, 'source_options', 'Source & Variation', closed=True)
    if technical:
        technical.prop(s, 'input_encoding', text='Read Colors As')
        technical.prop(s, 'seed', text='Variation Seed')


def draw_styles(layout, s):
    card = layout.box()
    card.label(text='Your Style Library', icon='PRESET')
    note(card, 'Save a look and reuse it on other textures.')
    card.prop(s, 'user_preset', text='')
    row = card.row(align=True)
    load = row.row(align=True)
    load.enabled = s.user_preset != 'NONE'
    load.operator('pixel4ever.load_preset', text='Load Style', icon='IMPORT')
    row.operator('pixel4ever.save_preset', text='Save New', icon='ADD')
    transfer = section(layout, 'style_transfer', 'Share a Style', closed=False)
    if transfer:
        row = transfer.row(align=True)
        row.operator('pixel4ever.import_preset', text='Import JSON', icon='IMPORT')
        row.operator('pixel4ever.export_preset', text='Export JSON', icon='EXPORT')
    reset = section(layout, 'start_over', 'Start Fresh', closed=False)
    if reset:
        reset.operator('pixel4ever.reset_defaults', text='Reset This Look', icon='LOOP_BACK')
        note(reset, 'Restores default controls for this source. Your saved styles and images are kept.')


def draw_export(layout, s, status):
    card = layout.box()
    card.label(text='Current Texture', icon='EXPORT')
    card.prop(s, 'output_size', text='Resolution')
    row = card.row()
    row.enabled = status == 'READY'
    row.scale_y = 1.25
    row.operator('pixel4ever.export_png', text='Save PNG', icon='EXPORT')
    if status in {'READY', 'EMPTY'} and s.result and s.result.packed_file:
        card.operator('pixel4ever.export_packed_result', icon='EXPORT')
    row = card.row()
    row.enabled = bool(s.result and not s.dirty and s.result.get('pixel4ever_kind') == 'TEXTURE'
                       and not s.preview_mask and s.preview_filter == 'NONE')
    row.operator('pixel4ever.apply_material', text='Use in Active Material', icon='MATERIAL')
    if s.preview_mask or s.preview_filter != 'NONE':
        note(card, 'Turn off mask and smoothing previews before applying to a material.', 'INFO')
    preview = section(layout, 'texture_preview', 'Preview Smoothing', closed=True)
    if preview:
        preview.prop(s, 'preview_filter', text='Filter')
        note(preview, 'Smoothing is for preview. PNG exports keep crisp pixel edges.')
    batch.draw(layout, s)
    tools = section(layout, 'palette_exports', 'Palette & LUT Tools', closed=True)
    if tools:
        tools.use_property_split = False
        if s.quantize == 'GENERATE':
            tools.prop(s, 'output_palette', text='Palette Swatch · 16²')
            tools.prop(s, 'output_lut', text='Palette LUT · 4096²')
            if s.output_lut and s.output_palette:
                note(tools, 'LUT output takes priority over the swatch.')
        elif s.quantize == 'PALETTE':
            tools.prop(s, 'default_lut', text='Identity LUT · 4096²')
        else:
            note(tools, 'Choose Build Palette or Palette / LUT in Look → Color to make palette assets.')
        if output_kind(s) != 'TEXTURE':
            note(tools, 'Generate and Save PNG will produce a palette asset. Disable these options to return to textures.', 'INFO')


def draw(layout, context):
    s = context.scene.pixel4ever
    status = source_status(s.source)
    ready = status == 'READY'
    layout.use_property_split = True
    layout.use_property_decorate = False
    if s.busy:
        running = layout.box()
        running.progress(factor=s.progress, type='BAR', text=s.progress_stage or 'Generating')
        running.operator('pixel4ever.cancel_generate', text='Cancel', icon='CANCEL')
    content = layout.column()
    content.enabled = not s.busy
    draw_source(content, s, status)
    draw_run(content, s, ready)
    content.separator(factor=.5)
    navigation = content.row(align=True)
    navigation.use_property_split = False
    navigation.scale_y = 1.2
    for value, label in (('LOOK', 'Look'), ('STYLES', 'Styles'), ('EXPORT', 'Export')):
        navigation.prop_enum(s, 'ui_workspace', value, text=label)
    content.separator(factor=.5)
    if s.ui_workspace == 'LOOK':
        draw_look(content, s, ready)
    elif s.ui_workspace == 'STYLES':
        draw_styles(content, s)
    elif s.ui_workspace == 'EXPORT':
        draw_export(content, s, status)
