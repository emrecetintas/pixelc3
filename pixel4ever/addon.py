# SPDX-FileCopyrightText: 2026 PixelC3 contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender RNA, sidebar UI, image I/O, and explicit material integration."""
from dataclasses import asdict, fields, replace
from contextlib import contextmanager
import json
from os.path import isfile
from pathlib import Path
from tempfile import NamedTemporaryFile
import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, IntVectorProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
import numpy as np

from . import core, jobs, processing
from .palettes import PALETTE_ITEMS

_pending = {}
_suspended = set()


@contextmanager
def suspend_updates(settings):
    pointer = settings.id_data.as_pointer()
    already = pointer in _suspended
    _suspended.add(pointer)
    try:
        yield
    finally:
        if not already:
            _suspended.discard(pointer)


def output_binding(settings, source, create=False):
    if source is None:
        return None
    match = next((row for row in settings.outputs if row.source == source), None)
    if match is None and create:
        match = settings.outputs.add()
        match.source = source
    return match


def migrate_output(settings):
    """Associate legacy results once, using the recorded source name."""
    image = settings.result
    if image and image.get('pixel4ever_generated'):
        original = bpy.data.images.get(image.get('pixel4ever_source', ''))
        if original and original != image:
            binding = output_binding(settings, original, create=True)
            if binding.result is None:
                binding.result = image


_CUSTOM_INPUTS = ('custom_dither', 'custom_mask', 'custom_palette', 'custom_lut')


def remember_source(settings, source=None):
    """Persist controls and local image pointers without serializing image names."""
    source = settings.source if source is None else source
    binding = output_binding(settings, source, create=True)
    if binding is not None:
        binding.settings_json = json.dumps(presets.recipe(settings))
        for key in _CUSTOM_INPUTS:
            setattr(binding, key, getattr(settings, key))


def initialize_sources(settings):
    migrate_output(settings)
    # Current RNA controls include any edits made after the last generation.
    remember_source(settings)
    settings.active_source = settings.source
    for binding in settings.outputs:
        if binding.settings_json or not binding.result:
            continue
        try:
            document = presets.recipe(settings)
            document['settings'].update(json.loads(binding.result.get('pixel4ever_settings', '{}')))
            presets.validate(settings, document)
            binding.settings_json = json.dumps(document)
            for key in _CUSTOM_INPUTS:
                setattr(binding, key, getattr(settings, key))
        except (ValueError, TypeError):
            pass


def source_changed(self, context):
    if self.id_data.as_pointer() in _suspended:
        return
    migrate_output(self)
    if self.active_source and self.active_source != self.source:
        remember_source(self, self.active_source)
    binding = output_binding(self, self.source)
    restore_error = ''
    if binding and binding.settings_json:
        try:
            values = presets.validate(self, json.loads(binding.settings_json))
            with suspend_updates(self):
                for key, value in values.items():
                    setattr(self, key, value)
                for key in _CUSTOM_INPUTS:
                    setattr(self, key, getattr(binding, key))
        except (ValueError, TypeError):
            restore_error = 'Saved image settings could not be restored; current controls retained'
    self.active_source = self.source
    self.result = binding.result if binding else None
    self.last_summary = ''
    self.last_error = restore_error
    queue_update(self, context)


def user_preset_items(self, context):
    from .presets import preset_items
    return preset_items()


def queue_update(self, context):
    if self.id_data.as_pointer() in _suspended:
        return
    self.dirty = True
    remember_source(self)
    scene = self.id_data
    if jobs.active(scene):
        jobs.cancel(scene, 'Settings changed — generate again')
    if self.auto_update and self.source and isinstance(scene, bpy.types.Scene):
        _pending[scene.name] = time.monotonic() + .4
        if not bpy.app.timers.is_registered(update_timer):
            bpy.app.timers.register(update_timer, first_interval=.4)


def update_timer():
    now = time.monotonic()
    for name, deadline in list(_pending.items()):
        if deadline > now:
            continue
        _pending.pop(name, None)
        scene = bpy.data.scenes.get(name)
        if scene and scene.pixel4ever.auto_update and scene.pixel4ever.source:
            s = scene.pixel4ever
            if source_status(s.source) != 'READY':
                continue
            if (s.output_lut and s.quantize == "GENERATE") or (s.default_lut and s.quantize == "PALETTE"):
                s.last_error = "Use Generate for a 4096 × 4096 LUT; automatic LUT generation is disabled."
                continue
            try:
                jobs.start(scene)
            except (ValueError, RuntimeError, MemoryError) as error:
                s.last_error = str(error)
    return .2 if _pending else None


def enum(items, name, default):
    return EnumProperty(name=name, items=items, default=default, update=queue_update)


def choice(key, label, description=""):
    return (key, label, description or label)


_SPACES = [choice("RGB", "RGB"), choice("LAB", "CIELAB"), choice("OKLAB", "Oklab")]


class Pixel4everOutput(bpy.types.PropertyGroup):
    source: PointerProperty(type=bpy.types.Image)
    result: PointerProperty(type=bpy.types.Image)
    settings_json: StringProperty(options={'HIDDEN'})
    custom_dither: PointerProperty(type=bpy.types.Image)
    custom_mask: PointerProperty(type=bpy.types.Image)
    custom_palette: PointerProperty(type=bpy.types.Image)
    custom_lut: PointerProperty(type=bpy.types.Image)


class Pixel4everBatchItem(bpy.types.PropertyGroup):
    source: PointerProperty(type=bpy.types.Image, name='Image')
    enabled: BoolProperty(name='Export', default=True)


class Pixel4everSettings(bpy.types.PropertyGroup):
    ui_workspace: EnumProperty(name='Workspace', description='Choose a part of your texture workflow',
                               items=[choice('LOOK', 'Look', 'Shape pixels, color and dithering'),
                                      choice('STYLES', 'Styles', 'Save, load and share processing styles'),
                                      choice('EXPORT', 'Export', 'Save textures, apply to materials or export a batch')],
                               default='LOOK')
    outputs: CollectionProperty(type=Pixel4everOutput)
    active_source: PointerProperty(type=bpy.types.Image, options={'HIDDEN'})
    batch_items: CollectionProperty(type=Pixel4everBatchItem)
    batch_index: IntProperty(default=0)
    batch_directory: StringProperty(name='Output Folder', subtype='DIR_PATH')
    batch_summary: StringProperty(options={'HIDDEN'})
    batch_report: StringProperty(options={'HIDDEN'})
    source: PointerProperty(type=bpy.types.Image, name="Source", description="Original image; never overwritten", update=source_changed)
    result: PointerProperty(type=bpy.types.Image, name="Result")
    comparison: PointerProperty(type=bpy.types.Image, name="Comparison")
    busy: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'})
    progress: FloatProperty(default=0, min=0, max=1, options={'SKIP_SAVE', 'HIDDEN'})
    progress_stage: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    user_preset: EnumProperty(name="Saved Preset", items=user_preset_items)
    auto_update: BoolProperty(name="Auto Update", default=False, description="Regenerate after changing controls; image painting still needs Generate", update=queue_update)
    dirty: BoolProperty(default=True, options={"HIDDEN"})
    last_error: StringProperty(options={"HIDDEN"})
    last_summary: StringProperty(options={"HIDDEN"})
    input_encoding: EnumProperty(name="Input Encoding", default="AUTO", items=[choice("AUTO", "From Image Color Space"), choice("SRGB", "sRGB Values"), choice("LINEAR", "Linear Rec.709 Values")], update=queue_update)
    separate_xy: BoolProperty(name="Separate XY Pixel Count", default=False, update=queue_update)
    pixel_count: IntProperty(name="Square Pixel Count", description="Count across the smallest image dimension", default=256, min=1, max=2048, update=queue_update)
    pixel_x: IntProperty(name="Pixel Count X", default=256, min=1, max=2048, update=queue_update)
    pixel_y: IntProperty(name="Pixel Count Y", default=256, min=1, max=2048, update=queue_update)
    downscale: enum([choice("NEAREST", "Crisp / Nearest"), choice("SOFTER", "Smooth / Bilinear", "Sample the center of each pixel with bilinear interpolation")], "Sampling", "NEAREST")
    preview_filter: enum([choice("NONE", "None"), choice("BILINEAR", "Bilinear"), choice("N64", "N64 3-Point")], "Preview Texture Filtering", "NONE")
    output_size: enum([choice("SOURCE", "Source Resolution", "Upscale pixel blocks to the source dimensions"), choice("PIXELS", "Pixel Resolution", "Keep the reduced image dimensions; use Closest texture filtering")], "Output Size", "SOURCE")
    dither: enum([choice("NONE", "None"), choice("WHITE", "White Noise"), choice("BLUE", "Blue Noise (Approx.)"), choice("BAYER", "Bayer 4 × 4"), choice("PATTERN", "Pattern"), choice("CUSTOM", "Custom Dither Pattern"), choice("AMOGUS", "Diamond Tile", "Repeat a geometric 5 × 5 tile"), choice('FLOYD_STEINBERG', 'Floyd–Steinberg', 'Serpentine error diffusion into palette colors or channel levels')], "Dither Type", "NONE")
    dither_method: enum([choice("BLEND", "Blend Texture", "Preserve the previous Overlay / Soft Light workflow"), choice("QUANTIZATION", "Quantization Aware", "Ordered selection between palette colors or channel levels")], "Dither Method", "BLEND")
    custom_resolution: IntVectorProperty(name="Custom Dither Resolution", description="Texture dimensions as powers of two; 8 means 256 pixels", size=2, default=(8, 8), min=0, max=10, update=queue_update)
    custom_dither: PointerProperty(type=bpy.types.Image, name="Dither Pattern", update=queue_update)
    blend_mode: enum([choice("OVERLAY", "Overlay"), choice("OVERLAY_LINEAR", "Overlay [Linear Space]"), choice("SOFT_LIGHT", "Soft Light"), choice("SOFT_LIGHT_LINEAR", "Soft Light [Linear Space]")], "Blend Mode", "SOFT_LIGHT")
    grayscale_dither: BoolProperty(name="Grayscale Dither (Red Channel)", default=False, update=queue_update)
    strength: FloatProperty(name="Blend Strength", default=.25, min=0, max=1, update=queue_update)
    saturation: FloatProperty(name="Blend Saturation", default=.5, min=0, max=1, update=queue_update)
    mask_type: enum([choice("NONE", "None"), choice("EDGES", "Dither by Edges"), choice("FLATS", "Dither by Flats"), choice("CUSTOM", "Custom Dither Mask Texture")], "Dither Mask Type", "NONE")
    custom_mask: PointerProperty(type=bpy.types.Image, name="Mask Image", update=queue_update)
    mask_strength: FloatProperty(name="Dither Mask Strength", default=0, min=0, max=1, update=queue_update)
    mask_gamma: FloatProperty(name="Dither Mask Gamma", default=1, min=.1, max=4, update=queue_update)
    preview_mask: BoolProperty(name="Preview Dither Mask", default=False, update=queue_update)
    show_mask_controls: BoolProperty(name="Show Mask Threshold Weights", default=False)
    mask_weights: FloatVectorProperty(name="Threshold Weights", size=7, default=(1, 1, .8, .6, .4, .2, .2), min=0, max=1, update=queue_update)
    quantize: enum([choice("NONE", "Source Colors"), choice("GENERATE", "Build Palette"), choice("CHANNELS", "Channel Levels"), choice("PALETTE", "Palette / LUT")], "Color Mode", "NONE")
    initialize: enum([choice('1', 'Weighted Spread'), choice('2', 'Farthest First'),
                      choice('3', 'Brightness Spread'), choice('4', 'Random Samples')], "Starting Colors", "1")
    creation_space: enum(_SPACES, "Palette Creation Color Space", "RGB")
    palette_preset: enum(PALETTE_ITEMS, "LUT / Palette", "AMIGA")
    custom_palette: PointerProperty(type=bpy.types.Image, name="Palette Image", update=queue_update)
    custom_lut: PointerProperty(type=bpy.types.Image, name="Hald LUT Image", update=queue_update)
    apply_space: enum(_SPACES, "Palette Apply Color Space", "RGB")
    quality: IntProperty(name="Quality", default=2, min=0, max=8, update=queue_update)
    colors: IntProperty(name="Number of Colors", default=32, min=2, max=256, update=queue_update)
    gamma: FloatProperty(name="Gamma Adjust", description="Expand the dark range during palette training", default=1, min=.1, max=4, update=queue_update)
    force_colors: enum([choice("NONE", "None"), choice("EXTREMES", "Darkest / Brightest"), choice("BLACK_WHITE", "Black / White")], "Force Colors", "NONE")
    output_palette: BoolProperty(name="Output Palette (16 × 16)", default=False, update=queue_update)
    output_lut: BoolProperty(name="Output Palette to Hald LUT (4096²)", default=False, update=queue_update)
    range_adaptive: BoolProperty(name="Use Range Adaptive Mode", default=False, update=queue_update)
    channel_mode: enum([choice("COLORS", "Colors Per Channel"), choice("BITS", "Bits Per Channel")], "Color Mode", "COLORS")
    channel_colors: IntProperty(name="Colors Per Channel", default=256, min=2, max=256, update=queue_update)
    channel_bits: IntProperty(name="Bits Per Channel", default=8, min=1, max=8, update=queue_update)
    default_lut: BoolProperty(name="Output Default Hald LUT (4096²)", default=False, update=queue_update)
    seed: IntProperty(name="Random Seed", default=0, min=0, max=2_147_483_647, update=queue_update)


def settings_from(properties):
    return core.Settings(**{field.name: tuple(getattr(properties, field.name))
                            if field.name in {"mask_weights", "custom_resolution"}
                            else getattr(properties, field.name) for field in fields(core.Settings)})


def source_status(image):
    if image is None:
        return 'EMPTY'
    if image.source not in {'FILE', 'GENERATED'}:
        return 'UNSUPPORTED'
    if image.source == 'FILE' and not image.packed_file:
        if not image.filepath or not isfile(bpy.path.abspath(image.filepath, library=image.library)):
            return 'MISSING'
    return 'READY' if min(image.size) > 0 else 'UNREADABLE'


def can_relink(image):
    return bool(image and image.source == 'FILE' and image.library is None and not image.packed_file)


def read_image(image, encoding="AUTO"):
    status = source_status(image)
    if status == 'EMPTY':
        raise ValueError("Select a source image first")
    if status == 'UNSUPPORTED':
        raise ValueError("Use a single File or Generated image; bake UDIMs, sequences and renders to a file first")
    if status == 'MISSING':
        raise ValueError(f"Source file missing for {image.name}; use Relink Source")
    if status == 'UNREADABLE':
        raise ValueError(f"Cannot read {image.name}; reload the image or check its file path")
    width, height = image.size
    if width * height > core.MAX_PIXELS:
        raise ValueError("Source exceeds 16,777,216 pixels; resize it before processing")
    count = len(image.pixels)
    channels = count // (width * height)
    if channels not in {1, 3, 4} or count != width * height * channels:
        raise ValueError(f"Unsupported image buffer: {count} values for {width} × {height}")
    flat = np.empty(count, np.float32)
    image.pixels.foreach_get(flat)
    raw = flat.reshape(height, width, channels)[::-1].copy()
    if channels == 1:
        raw = np.repeat(raw, 3, -1)
    if raw.shape[2] == 3:
        raw = np.concatenate((raw, np.ones((height, width, 1), np.float32)), -1)
    if image.alpha_mode == "NONE":
        raw[..., 3] = 1
    elif image.alpha_mode == "PREMUL":
        alpha = raw[..., 3:4]
        raw[..., :3] = np.divide(raw[..., :3], alpha, out=np.zeros_like(raw[..., :3]), where=alpha > 1e-8)
    if encoding == "AUTO":
        space = image.colorspace_settings.name.casefold()
        if space in {"linear rec.709", "linear", "linear srgb", "scene linear"}:
            encoding = "LINEAR"
        elif space in {"srgb", "non-color", "raw"}:
            encoding = "SRGB"
        else:
            raise ValueError(f"Color space '{image.colorspace_settings.name}' needs conversion to sRGB or Linear Rec.709; or select Input Encoding explicitly")
    if encoding == "LINEAR":
        raw[..., :3] = core.linear_to_srgb(raw[..., :3])
    return core.image_array(raw)


def prepare(scene, for_export=False, source=None):
    s = scene.pixel4ever
    source = s.source if source is None else source
    if source == s.result and source is not None:
        raise ValueError("Choose the original image as Source; the result cannot be its own source")
    config = settings_from(s)
    if for_export:
        config = replace(config, preview_filter="NONE", preview_mask=False)
    images = {'source': read_image(source, s.input_encoding)}
    texture_output = not ((config.quantize == "GENERATE" and (config.output_palette or config.output_lut))
                          or (config.quantize == "PALETTE" and config.default_lut))
    if texture_output and config.dither == "CUSTOM":
        images["custom_dither"] = read_image(s.custom_dither)
    if texture_output and config.dither != "NONE" and config.mask_type == "CUSTOM":
        images["custom_mask"] = read_image(s.custom_mask)
    if config.quantize == "PALETTE" and not config.default_lut:
        if config.palette_preset == "CUSTOM_PALETTE":
            images["custom_palette"] = read_image(s.custom_palette)
        elif config.palette_preset == "CUSTOM_LUT":
            images["custom_lut"] = read_image(s.custom_lut)
    return config, images, processing.request_key(config, images)


def compute(scene, for_export=False):
    config, images, key = prepare(scene, for_export)
    result = processing.cached(key)
    if result is None:
        result = processing.run(config, images)
        processing.remember(key, result)
    return result


def write_image(result, name, image=None, pack=True):
    height, width = result.pixels.shape[:2]
    if image is None:
        image = bpy.data.images.new(name, width=width, height=height, alpha=True, float_buffer=False)
    # Color-space and alpha updates can reload a packed image from its previous
    # contents, undoing a buffer resize. Configure first, then resize the loaded
    # buffer. Avoid reloads entirely when the settings are already correct.
    if image.colorspace_settings.name != "sRGB":
        image.colorspace_settings.name = "sRGB"
    if image.alpha_mode != "STRAIGHT":
        image.alpha_mode = "STRAIGHT"
    if tuple(image.size) != (width, height):
        image.scale(width, height)
    pixels = np.ascontiguousarray(result.pixels[::-1]).ravel()
    if len(image.pixels) != pixels.size:
        raise RuntimeError(f"Cannot allocate the {width} × {height} RGBA output buffer; generate into a new result image")
    image.pixels.foreach_set(pixels)
    image.update()
    image["pixel4ever_generated"] = True
    image["pixel4ever_kind"] = result.kind
    if pack:
        image.pack()
    return image


def generate(scene):
    _pending.pop(scene.name, None)
    start = time.perf_counter()
    result = compute(scene)
    return commit_result(scene, result, settings_from(scene.pixel4ever), start)


def commit_result(scene, result, config, started, cache_hit=False):
    s = scene.pixel4ever
    migrate_output(s)
    binding = output_binding(s, s.source, create=True)
    if binding is None:
        raise ValueError('Select a source image first')
    existing = binding.result
    if existing and (not existing.get("pixel4ever_generated") or existing.is_float):
        existing = None
    image = write_image(result, f"PixelC3 - {s.source.name}", existing)
    image["pixel4ever_source"] = s.source.name
    image["pixel4ever_settings"] = json.dumps(asdict(config))
    binding.result = image
    s.result = image
    s.dirty = False
    s.last_error = ""
    count = f" · {len(result.palette)} colors" if result.palette is not None else ""
    suffix = ' · cached' if cache_hit else f' · {time.perf_counter() - started:.2f}s'
    s.last_summary = f"{result.grid[0]} × {result.grid[1]} grid{count}{suffix}"
    remember_source(s)
    return image


RESET_GROUPS = {
    'DIMENSIONS': {'separate_xy', 'pixel_count', 'pixel_x', 'pixel_y', 'downscale', 'output_size', 'preview_filter'},
    'QUANTIZATION': {'quantize', 'initialize', 'creation_space', 'palette_preset', 'apply_space', 'quality',
                     'colors', 'gamma', 'force_colors', 'output_palette', 'output_lut', 'range_adaptive',
                     'channel_mode', 'channel_colors', 'channel_bits', 'default_lut'},
    'DITHERING': {'dither', 'dither_method', 'custom_resolution', 'blend_mode', 'grayscale_dither', 'strength',
                  'saturation', 'mask_type', 'mask_strength', 'mask_gamma', 'preview_mask', 'mask_weights',
                  'show_mask_controls'},
}


def reset_settings(settings, group='ALL'):
    keys = set().union(*RESET_GROUPS.values()) | {'seed', 'input_encoding'} if group == 'ALL' else RESET_GROUPS[group]
    with suspend_updates(settings):
        for key in keys:
            settings.property_unset(key)
    settings.last_error = ''
    queue_update(settings, bpy.context)


class P4EVER_OT_reset(bpy.types.Operator):
    bl_idname = 'pixel4ever.reset_defaults'
    bl_label = 'Reset to Defaults'
    bl_description = 'Reset processing controls; retain sources, outputs, custom images and saved presets'
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=[choice('ALL', 'All Settings'), choice('DIMENSIONS', 'Dimensions'),
                               choice('QUANTIZATION', 'Quantization'), choice('DITHERING', 'Dithering')], default='ALL')

    def execute(self, context):
        reset_settings(context.scene.pixel4ever, self.group)
        return {'FINISHED'}


class P4EVER_OT_commit(bpy.types.Operator):
    bl_idname = 'pixel4ever.commit_job'
    bl_label = 'Finish PixelC3 Generation'
    bl_options = {'INTERNAL', 'UNDO'}
    identity: StringProperty()

    def execute(self, context):
        job, result = jobs.take_ready(self.identity)
        image = commit_result(job['scene'], result, job['config'], job['started'])
        area = job['area']
        try:
            if area and area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = image
        except ReferenceError:
            pass
        return {'FINISHED'}


class P4EVER_OT_cancel(bpy.types.Operator):
    bl_idname = 'pixel4ever.cancel_generate'
    bl_label = 'Cancel'
    bl_description = 'Stop generation or remaining batch exports; retain previous results and completed exports'

    def execute(self, context):
        jobs.cancel(context.scene)
        return {'FINISHED'}


class P4EVER_OT_load(bpy.types.Operator, ImportHelper):
    bl_idname = "pixel4ever.load_image"
    bl_label = "Load Source Image"
    bl_options = {"REGISTER", "UNDO"}
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tga;*.tif;*.tiff;*.bmp;*.exr;*.hdr", options={"HIDDEN"})

    def execute(self, context):
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
            context.scene.pixel4ever.source = image
            if context.area and context.area.type == "IMAGE_EDITOR":
                context.space_data.image = image
            return {"FINISHED"}
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class P4EVER_OT_relink_source(bpy.types.Operator, ImportHelper):
    bl_idname = 'pixel4ever.relink_source'
    bl_label = 'Relink Source'
    bl_description = 'Locate the source file and keep this image’s settings, result and material references'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene and not context.scene.pixel4ever.busy
                    and can_relink(context.scene.pixel4ever.source))

    def execute(self, context):
        s = context.scene.pixel4ever
        image = s.source
        candidate = None
        try:
            path = bpy.path.abspath(self.filepath)
            candidate = bpy.data.images.load(path, check_existing=False)
            if source_status(candidate) != 'READY':
                raise ValueError('Choose a readable image file')
            previous = image.filepath_raw
            image.filepath_raw = path
            try:
                image.reload()
                if source_status(image) != 'READY':
                    raise ValueError(f'Could not reload {image.name} from the selected file')
            except (ValueError, RuntimeError, OSError):
                image.filepath_raw = previous
                image.reload()
                raise
        except (ValueError, RuntimeError, OSError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            if candidate is not None:
                bpy.data.images.remove(candidate)
        s.last_error = ''
        queue_update(s, context)
        self.report({'INFO'}, f'Relinked {image.name}')
        return {'FINISHED'}


class P4EVER_OT_use_image(bpy.types.Operator):
    bl_idname = "pixel4ever.use_image"
    bl_label = "Use Current Image / Texture"
    bl_description = "Use the Image Editor image, selected Image Texture node, or active material's base color image"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        image = context.space_data.image if context.area and context.area.type == "IMAGE_EDITOR" else None
        if image is None:
            obj = context.active_object
            material = obj.active_material if obj else None
            tree = material.node_tree if material and material.use_nodes else None
            active = tree.nodes.active if tree else None
            if active and active.type == "TEX_IMAGE":
                image = active.image
            if image is None and tree:
                for node in tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        links = node.inputs["Base Color"].links
                        if links and links[0].from_node.type == "TEX_IMAGE":
                            image = links[0].from_node.image
                            break
        if image is None:
            self.report({"ERROR"}, "Open an image or select an Image Texture node in the active material")
            return {"CANCELLED"}
        if image == context.scene.pixel4ever.result:
            self.report({"INFO"}, "The current image is the result; the original source is already selected")
            return {"CANCELLED"}
        context.scene.pixel4ever.source = image
        return {"FINISHED"}


class P4EVER_OT_generate(bpy.types.Operator):
    bl_idname = "pixel4ever.generate"
    bl_label = "Generate"
    bl_description = "Process the original source into a separate, packed image"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        try:
            jobs.start(context.scene, context.area)
            return {'FINISHED'}
        except (ValueError, RuntimeError, MemoryError, OSError) as error:
            context.scene.pixel4ever.last_error = str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def execute(self, context):
        try:
            image = generate(context.scene)
            if context.area and context.area.type == "IMAGE_EDITOR":
                context.space_data.image = image
            self.report({"INFO"}, context.scene.pixel4ever.last_summary)
            return {"FINISHED"}
        except (ValueError, RuntimeError, MemoryError) as error:
            context.scene.pixel4ever.last_error = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class P4EVER_OT_show(bpy.types.Operator):
    bl_idname = "pixel4ever.show_image"
    bl_label = "Show Image"
    target: EnumProperty(items=[choice("SOURCE", "Source"), choice("RESULT", "Result")], default="RESULT")

    def execute(self, context):
        s = context.scene.pixel4ever
        image = s.source if self.target == "SOURCE" else s.result
        if image is None:
            return {"CANCELLED"}
        area = context.area if context.area and context.area.type == "IMAGE_EDITOR" else next((a for a in context.screen.areas if a.type == "IMAGE_EDITOR"), None)
        if area:
            area.spaces.active.image = image
            return {"FINISHED"}
        self.report({"INFO"}, "Open an Image Editor to view the image")
        return {"CANCELLED"}


class P4EVER_OT_compare(bpy.types.Operator):
    bl_idname = 'pixel4ever.compare'
    bl_label = 'Compare Side by Side'
    bl_description = 'Show source on the left and current result on the right in a separate preview image'

    def execute(self, context):
        s = context.scene.pixel4ever
        try:
            if not s.source or not s.result or s.dirty:
                raise ValueError('Generate the current settings before comparing')
            if s.result.get('pixel4ever_kind') != 'TEXTURE':
                raise ValueError('Compare is available for textures, not palette swatches or LUTs')
            area = context.area if context.area and context.area.type == 'IMAGE_EDITOR' else next(
                (a for a in context.screen.areas if a.type == 'IMAGE_EDITOR'), None)
            if area is None:
                raise ValueError('Open an Image Editor to view the comparison')
            source = read_image(s.source, s.input_encoding)
            height, width = source.shape[:2]
            ratio = min(1, 768 / max(width, height))
            width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
            left = core.resize(source, width, height, 'BILINEAR')
            right = core.resize(read_image(s.result, 'SRGB'), width, height, 'NEAREST')
            preview = np.ones((height, width * 2 + 4, 4), np.float32)
            preview[..., :3] = .12
            preview[:, :width] = left
            preview[:, width + 4:] = right
            previous = s.comparison
            if previous and previous.get('pixel4ever_kind') != 'COMPARISON':
                previous = None
            s.comparison = write_image(core.Result(preview, None, (width, height), 'COMPARISON'),
                                       'PixelC3 Compare - Source LEFT | Result RIGHT', previous, pack=False)
            area.spaces.active.image = s.comparison
            return {'FINISHED'}
        except (ValueError, RuntimeError, MemoryError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class P4EVER_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = "pixel4ever.export_png"
    bl_label = "Export PNG"
    bl_description = "Regenerate and save a PNG, with mask preview and texture preview filtering disabled"
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    def invoke(self, context, event):
        source = context.scene.pixel4ever.source
        if not self.filepath and source:
            self.filepath = bpy.path.clean_name(Path(source.name).stem) + "_pixelc3.png"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        image = None
        try:
            s = context.scene.pixel4ever
            # Reuse a ready palette/LUT output. Rebuilding a 4K LUT on Export
            # would repeat the expensive work just completed in the worker.
            if s.result and not s.dirty and s.result.get('pixel4ever_kind') in {'LUT', 'PALETTE'}:
                pixels = read_image(s.result, 'SRGB')
                result = core.Result(pixels, None, tuple(s.result.size), s.result['pixel4ever_kind'])
            else:
                result = compute(context.scene, for_export=True)
            image = write_image(result, "PixelC3 export", pack=False)
            image.file_format = "PNG"
            image.filepath_raw = bpy.path.ensure_ext(self.filepath, ".png")
            # Image.save avoids the scene's AgX/Filmic view transform.
            image.save()
            self.report({"INFO"}, f"Exported {image.filepath_raw}")
            return {"FINISHED"}
        except (ValueError, RuntimeError, MemoryError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        finally:
            if image:
                bpy.data.images.remove(image)


class P4EVER_OT_export_packed_result(bpy.types.Operator, ExportHelper):
    bl_idname = 'pixel4ever.export_packed_result'
    bl_label = 'Export Packed Result'
    bl_description = 'Save the PNG stored in this project from the last successful generation'
    filename_ext = '.png'
    filter_glob: StringProperty(default='*.png', options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        if context.scene:
            result = context.scene.pixel4ever.result
            return bool(result and result.packed_file)
        return False

    def invoke(self, context, event):
        s = context.scene.pixel4ever
        if not self.filepath:
            name = bpy.path.clean_name(Path((s.source or s.result).name).stem)
            self.filepath = f'{name}_pixelc3_packed.png'
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        s = context.scene.pixel4ever
        temporary_path = None
        try:
            if not self.filepath:
                raise ValueError('Choose a destination for the packed PNG')
            destination = Path(bpy.path.ensure_ext(bpy.path.abspath(self.filepath), '.png'))
            if s.source and s.source.source == 'FILE' and s.source.filepath:
                source_path = Path(bpy.path.abspath(s.source.filepath, library=s.source.library))
                if source_path.resolve() == destination.resolve():
                    raise ValueError('Choose a different path to keep the source image file')
            data = s.result.packed_file.data
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('The packed result does not contain a PNG')
            with NamedTemporaryFile(dir=destination.parent, prefix='.pixel4ever-', delete=False) as output:
                temporary_path = Path(output.name)
                output.write(data)
            temporary_path.replace(destination)
            temporary_path = None
        except (ValueError, RuntimeError, OSError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        self.report({'INFO'}, f'Exported {destination.name}')
        return {'FINISHED'}


class P4EVER_OT_apply(bpy.types.Operator):
    bl_idname = "pixel4ever.apply_material"
    bl_label = "Apply to Active Material"
    bl_description = "Replace matching source Image Texture nodes in the active material, using Closest filtering"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.pixel4ever
        obj = context.active_object
        material = obj.active_material if obj else None
        if not material or not material.use_nodes:
            self.report({"ERROR"}, "Select an object with a node-based material")
            return {"CANCELLED"}
        if s.result is None or s.dirty:
            self.report({"ERROR"}, "Generate the current settings first")
            return {"CANCELLED"}
        if s.result.get("pixel4ever_kind") != "TEXTURE" or s.preview_mask or s.preview_filter != "NONE":
            self.report({"ERROR"}, "Generate a texture with preview filtering and mask preview disabled first")
            return {"CANCELLED"}
        nodes = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image in {s.source, s.result}]
        if not nodes:
            self.report({"ERROR"}, "The active material has no Image Texture node using the source image")
            return {"CANCELLED"}
        for node in nodes:
            node.image = s.result
            node.interpolation = "Closest"
        self.report({"INFO"}, f"Updated {len(nodes)} texture node(s) in {material.name}")
        return {"FINISHED"}


def draw_panel(layout, context):
    from . import ui
    ui.draw(layout, context)


class P4EVER_PT_image(bpy.types.Panel):
    bl_label = "PixelC3"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "PixelC3"

    def draw(self, context):
        draw_panel(self.layout, context)


class P4EVER_PT_view(bpy.types.Panel):
    bl_label = "PixelC3"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PixelC3"

    def draw(self, context):
        draw_panel(self.layout, context)


from . import batch, presets

_CLASSES = (Pixel4everOutput, Pixel4everBatchItem, Pixel4everSettings, P4EVER_OT_reset, P4EVER_OT_commit, P4EVER_OT_cancel,
            P4EVER_OT_load, P4EVER_OT_relink_source, P4EVER_OT_use_image, P4EVER_OT_generate, P4EVER_OT_compare,
            P4EVER_OT_show, P4EVER_OT_export, P4EVER_OT_export_packed_result, P4EVER_OT_apply,
            *presets.CLASSES, *batch.CLASSES,
            P4EVER_PT_image, P4EVER_PT_view)


@persistent
def on_file_load(_):
    jobs.shutdown()
    processing.clear()
    _pending.clear()
    for scene in bpy.data.scenes:
        s = scene.pixel4ever
        s.busy = False
        initialize_sources(s)


def initialize_scenes():
    # Blender restricts bpy.data while enabling an add-on. Migrate persisted
    # bindings after registration has returned and normal data access resumes.
    for scene in bpy.data.scenes:
        scene.pixel4ever.busy = False
        initialize_sources(scene.pixel4ever)
    return None


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.pixel4ever = PointerProperty(type=Pixel4everSettings)
    bpy.app.handlers.load_post.append(on_file_load)
    bpy.app.timers.register(initialize_scenes, first_interval=.1)


def unregister():
    jobs.shutdown()
    processing.clear()
    if bpy.app.timers.is_registered(initialize_scenes):
        bpy.app.timers.unregister(initialize_scenes)
    if on_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_file_load)
    _pending.clear()
    if bpy.app.timers.is_registered(update_timer):
        bpy.app.timers.unregister(update_timer)
    del bpy.types.Scene.pixel4ever
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
