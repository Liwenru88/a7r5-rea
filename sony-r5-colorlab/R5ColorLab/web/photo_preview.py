"""Offline photo comparison using the task's fitted color subchain.

The LUT side uses LibRaw linear demosaic, not RawAlchemy's RCD decoder.
No image is admitted as training data. Historical collectors stay unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np  # Must precede historical imports with their audit path.
from PIL import Image, PngImagePlugin
import core
import white_balance
from edit_native_recipe import read
from raw_slog3_reference import RawSLog3Reference, Cube

FRONTEND_REVISION = 'itp-native-sscs-v2'

def raw_camera_identity(source):
    """Read TIFF Make/Model rather than use a version-dependent LibRaw matrix as ID."""
    import struct
    with Path(source).open('rb') as f:
        header=f.read(8)
        if header[:2] not in (b'II',b'MM'):raise ValueError('RAW不是受支持的TIFF/ARW容器')
        endian='<' if header[:2]==b'II' else '>'
        if struct.unpack(endian+'H',header[2:4])[0]!=42:raise ValueError('不支持的RAW容器')
        f.seek(struct.unpack(endian+'I',header[4:])[0]);count=struct.unpack(endian+'H',f.read(2))[0]
        if count>4096:raise ValueError('RAW IFD过大')
        entries=f.read(count*12);result={}
        for i in range(count):
            record=entries[i*12:i*12+12];tag,kind,n=struct.unpack(endian+'HHI',record[:8])
            if tag not in (271,272) or kind!=2:continue
            if not 1<=n<=256:raise ValueError('RAW机型字段无效')
            if n<=4:value=record[8:8+n]
            else:
                f.seek(struct.unpack(endian+'I',record[8:])[0]);value=f.read(n)
            result[tag]=value.rstrip(b'\0').decode('ascii',errors='strict').strip()
        if result.get(271)!='SONY' or result.get(272)!='ILCE-7RM5':
            raise ValueError('当前RAW预览需要SONY ILCE-7RM5，实际：'+str(result))
        return dict(make=result[271],model=result[272])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def approximate_front(camera_rgb, wb, reference_model):
    """Approximate photograph front, not the verified flatfield ITP branch.

    Reference-context green gain sets native units; this RAW supplies WB.
    Apply native SSCS after ITP gains: the color model expects post-SSCS
    input, matching the measured training samples. Demosaic/Vatr/lens/noise
    behavior of textured photographs remains approximate.
    """
    import struct
    from edit_raw_front import as_shot_wb
    gains = as_shot_wb(reference_model.raw, reference_model.settings).astype(float)
    scale = struct.unpack_from('<H', reference_model.raw, 0x40)[0]
    green_gain = scale/32768*gains[1]/16
    wb = np.asarray(wb, dtype=float)
    if wb.shape != (3,) or not np.isfinite(wb).all() or np.any(wb <= 0) or green_gain <= 0:
        raise ValueError('Invalid approximate frontend gains')
    native_wb = np.trunc(gains[1]*(wb/wb[1]))
    channel_gains = np.float32(scale)*np.float32(1/32768)*native_wb.astype(np.float32)*np.float32(1/16)
    itp = np.trunc(np.clip(np.asarray(camera_rgb,dtype=np.float32)*channel_gains, 0, 16383)).astype('<u2')
    return reference_model.sscs(itp.reshape(-1,3)).reshape(itp.shape)


def quantize(rgb):
    return np.floor(np.clip(rgb, 0, 1)*255+.5).astype(np.uint8)


def raster(keys, rgb, bounds):
    y0, y1, x0, x1 = bounds
    image = np.zeros((y1-y0+1, x1-x0+1, 4), dtype=np.uint8)
    colors = quantize(rgb)
    for (y, x), color in zip(keys, colors):
        image[y-y0, x-x0, :3] = color
        image[y-y0, x-x0, 3] = 255
    return image


PREVIEW_LONG_EDGE = 3840
MAX_PHOTO_PIXELS = 110_000_000


def raster_photo(source):
    """读取普通照片，保留 TIFF 的 16 位精度并按嵌入 ICC 转换。"""
    from exact_icc import to_srgb
    with source.open('rb') as stream:
        header = stream.read(32)
    if header[:4] in (b'II*\0', b'MM\0*', b'II+\0', b'MM\0+'):
        import tifffile
        with tifffile.TiffFile(source) as file:
            page = file.pages[0]
            if (page.imagewidth*page.imagelength > MAX_PHOTO_PIXELS or page.axes not in ('YXS', 'SYX')
                    or page.samplesperpixel != 3 or int(page.photometric) != 2
                    or page.dtype.kind != 'u' or page.dtype.itemsize not in (1, 2)):
                raise ValueError('请选择 1.1 亿像素以内的 8／16 位 RGB TIFF')
            profile = page.tags.get('InterColorProfile')
            icc = profile.value if profile else None
            orientation = page.tags.get('Orientation')
            orientation = int(orientation.value) if orientation else 1
            pixels = page.asarray(maxworkers=8)
            if page.axes == 'SYX':
                pixels = np.moveaxis(pixels, 0, -1)
        kind = 'tiff'
    else:
        with Image.open(source) as image:
            if image.format not in ('JPEG', 'MPO', 'PNG') or image.width*image.height > MAX_PHOTO_PIXELS:
                raise ValueError('请选择 1.1 亿像素以内的 JPG、PNG 或 RGB TIFF')
            # 索尼直出 JPG 可附带第二张缩略图。预览只读取首张主图。
            if image.format == 'MPO':
                image.seek(0)
            if (image.mode != 'RGB' or 'transparency' in image.info
                    or (image.format == 'PNG' and getattr(image, 'is_animated', False))):
                raise ValueError('请选择不含透明通道的单张 RGB JPG 或 PNG')
            kind = 'png' if image.format == 'PNG' else 'jpg'
            icc = image.info.get('icc_profile')
            orientation = int(image.getexif().get(274, 1))
            if kind == 'png' and header[24:25] == b'\x10':
                from imagecodecs import png_decode
                pixels = png_decode(source.read_bytes())
            else:
                pixels = np.array(image)
    if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.dtype.kind != 'u' or pixels.dtype.itemsize not in (1, 2):
        raise ValueError('照片须为 8／16 位无透明通道的 RGB 图像')
    bits = pixels.dtype.itemsize*8
    width, height = pixels.shape[1], pixels.shape[0]
    ratio = min(1, PREVIEW_LONG_EDGE/max(width, height))
    size = max(1, round(width*ratio)), max(1, round(height*ratio))
    channels = []
    transposes = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                  4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                  6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                  8: Image.Transpose.ROTATE_90}
    for channel in range(3):
        plane = Image.fromarray(pixels[:, :, channel].astype(np.float32))
        if size != (width, height):
            plane = plane.resize(size, Image.Resampling.LANCZOS)
        if orientation in transposes:
            plane = plane.transpose(transposes[orientation])
        channels.append(np.asarray(plane))
    del pixels
    rgb, color = to_srgb(np.clip(np.stack(channels, axis=-1)/(2**bits-1), 0, 1), icc)
    return np.clip(rgb, 0, 1), dict(source_format=kind, bits_per_channel=bits, icc_conversion=color)

def preview_coordinates(sizes):
    """4K long edge, original aspect, common sensor samples for both paths."""
    width = min(sizes.crop_width-16, PREVIEW_LONG_EDGE)
    height = min(sizes.crop_height-16, round(width*sizes.crop_height/sizes.crop_width))
    xs = np.rint(np.linspace(sizes.crop_left_margin+8,
        sizes.crop_left_margin+sizes.crop_width-9, width)).astype(int)
    ys = np.rint(np.linspace(sizes.crop_top_margin+8,
        sizes.crop_top_margin+sizes.crop_height-9, height)).astype(int)
    return xs, ys


def apply_rows(rgb, transform, rows=8, progress=None):
    """Bound temporary memory for high-resolution color transformations."""
    out = np.empty_like(rgb)
    for start in range(0, len(rgb), rows):
        out[start:start+rows] = transform(rgb[start:start+rows])
        if progress: progress(min(start+rows,len(rgb))/len(rgb))
    return out


def report_progress(output, phase, fraction=0):
    path = output/'progress.json'
    temporary = output/'progress.tmp'
    temporary.write_text(json.dumps(dict(phase=phase, percent=round(fraction*100))))
    temporary.replace(path)


def response_identity(job, pc=False, grid_key=None):
    """Record the exact saved response, including R5 calibration source hash."""
    if grid_key:
        from grid_distillation import load_result
        value,_,_=load_result(job,grid_key)
        return value['identity']['response']
    if pc:
        import pc_compensation
        value,_=pc_compensation.load(job)
        return value.get('curves',{}).get('response')
    return None


def compensation(job, output, rgb, pc, grid_key, grid_enabled=True):
    """Load/verify a frozen transform once, apply the exact function in rows."""
    from photo_backend import enable
    if grid_key:
        from grid_distillation import load_result, evaluate
        value, grid, _ = load_result(job, grid_key)
        response = value['identity']['response']
        if not grid_enabled:
            return rgb.copy()
        enable(response)
        def transform(a):
            from gpu_runtime import available
            if available() and isinstance(response,dict) and response.get('preset','').startswith('r5-paired-'):
                from gpu_color import paired_numpy
                return paired_numpy(a.reshape(-1,3),grid,response,exact_display=True).reshape(a.shape)
            return evaluate(a.reshape(-1,3),grid,response).reshape(a.shape)
    elif pc:
        import pc_compensation
        import pc_stages
        value, grid = pc_compensation.load(job)
        if value['schema'] == 'r5-PC-compensation/2':
            curves = value['curves']
            if grid_enabled:
                enable(curves.get('response'))
            def transform(a):
                flat = a.reshape(-1,3)
                if not grid_enabled:
                    return np.clip(pc_stages.curves(flat,curves)[1],0,1).reshape(a.shape)
                return pc_stages.render(flat,curves,grid).reshape(a.shape)
        else:
            if not grid_enabled:
                return rgb.copy()
            from residual_grid import evaluate
            def transform(a):
                return evaluate(a.reshape(-1,3),grid,np.eye(3)).reshape(a.shape)
    else:
        return rgb
    phase = '应用压缩网格（精确计算）' if grid_key else '应用 PC 补偿' if grid_enabled else '仅应用 PC 曲线（网格关闭）'
    report_progress(output,phase)
    return apply_rows(rgb,transform,progress=lambda f:report_progress(output,phase,f))


def raw_photo(source, job, output, recipe, model, audit, has_lut, *, reference_model=None):
    from compute_backend import render_native
    from baseline import for_job
    from edit_color_pipeline import RuntimeColor

    report_progress(output,"解码 RAW")
    from rawpy import _rawpy as rawpy
    raw = rawpy.RawPy()
    raw.open_file(str(source))
    raw.unpack()
    try:
        profile = json.loads(core.PROFILE.read_text())
        camera_identity=raw_camera_identity(source)
        decoder_matrix_matches_reference=bool(np.allclose(raw.rgb_xyz_matrix,profile['xyz_to_camera'],atol=1e-6))
        sizes = raw.sizes
        if ((sizes.raw_width, sizes.raw_height) != (9728, 6656) or
                (sizes.crop_left_margin, sizes.crop_top_margin,
                 sizes.crop_width, sizes.crop_height) != (32, 20, 9504, 6336) or
                not np.array_equal(raw.raw_pattern, [[0, 1], [3, 2]])):
            details=dict(raw_size=[sizes.raw_width,sizes.raw_height],crop=[sizes.crop_left_margin,sizes.crop_top_margin,sizes.crop_width,sizes.crop_height],pattern=np.asarray(raw.raw_pattern).tolist(),matrix_matches=bool(np.allclose(raw.rgb_xyz_matrix,profile['xyz_to_camera'],atol=1e-6)))
            raise ValueError('RAW解码信息与已验证格式不匹配：'+json.dumps(details,ensure_ascii=False))
        black = np.array(raw.black_level_per_channel)[[0, 1, 2]]
        white = raw.white_level
        if len(set(raw.black_level_per_channel)) != 1 or not np.all(white > black):
            raise ValueError('Unsupported RAW levels')
        wb = np.array(raw.camera_whitebalance[:3], dtype=float)
        if not np.isfinite(wb).all() or np.any(wb <= 0):
            raise ValueError('Invalid as-shot white balance')
        profile['camera_wb_rgb'] = (wb/wb[1]).tolist()
        # Unit-WB, black-subtracted camera-native RGB in original sensor units.
        camera = raw.postprocess(output_color=rawpy.ColorSpace.raw,
            user_wb=[1, 1, 1, 1], use_camera_wb=False, use_auto_wb=False,
            no_auto_bright=True, no_auto_scale=True, gamma=(1, 1),
            output_bps=16, user_flip=0, demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR)
    finally:
        raw.close()
    wb_shift=white_balance.from_recipe(recipe)
    wb_ratio=white_balance.photo_gains(model,wb,wb_shift)
    xs, ys = preview_coordinates(sizes)
    if has_lut:
        reference = RawSLog3Reference(profile, Cube(job/'input.cube'), audit['gamut'],
                                     mode='raw-alchemy-v0.6.2-fused')
    else:
        base_model = reference_model if reference_model is not None else RuntimeColor.from_capture(*for_job(job))
    target = np.empty((len(ys), len(xs), 3), dtype=float)
    predicted = np.empty_like(target)
    for row, y in enumerate(ys):
        if row % 32 == 0:
            report_progress(output, '渲染同一张 RAW 的参考图和拟合图', row/len(ys))
        neighborhoods = camera[y, xs[:, None]+np.arange(-4, 5)[None, :]]
        front = approximate_front(neighborhoods, wb, model)
        fitted_front = (approximate_front(neighborhoods*wb_ratio, wb, model)
                        if white_balance.active(wb_shift) else front)
        predicted[row] = render_native(model,fitted_front)[:, 4]/16383
        if has_lut:
            target[row] = reference(camera[y, xs].astype(float)/(white-black))
        else:
            target[row] = render_native(base_model,front)[:, 4]/16383
    return target, predicted, dict(source_format='arw', reference_kind='lut' if has_lut else 'baseline',
        gamut=audit.get('gamut'), camera_wb=profile['camera_wb_rgb'],
        raw_camera_identity=camera_identity, decoder_matrix_matches_reference=decoder_matrix_matches_reference,
        sampling='rounded-uniform-sensor-coordinates', orientation='sensor landscape')


def raster_native(source, output, recipe, model):
    from compute_backend import render_native
    from edit_raw_front import itp_flatfield
    from sensor_encoding import encode_reference

    report_progress(output,'解码照片并转换到 sRGB')
    target, metadata = raster_photo(source)
    wb = white_balance.from_recipe(recipe)
    settings = white_balance.settings_for(model,wb) if white_balance.active(wb) else model.settings

    def simulate(rows):
        flat = rows.reshape(-1,3)
        linear = np.where(flat<=.04045,flat/12.92,((flat+.055)/1.055)**2.4)
        codes = encode_reference(np.rint(512+linear*15871).astype('<u2'),model)
        front = model.sscs(itp_flatfield(codes,model.raw,settings))
        inputs = np.repeat(front[:,None,:],9,axis=1)
        return (render_native(model,inputs)[:,4]/16383).reshape(rows.shape)

    predicted = apply_rows(target,simulate,progress=lambda f:report_progress(output,'模拟滤镜效果',f))
    metadata.update(reference_kind='source-image', sampling='resized-srgb', orientation='embedded orientation')
    return target, predicted, metadata


def save_preview_images(output, target, predicted):
    report_progress(output,'保存参考图和拟合图')
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text('Color interpretation', '8-bit output RGB displayed as sRGB; no extra gamma or black subtraction')
    for name, rgb in [('lut', target), ('model', predicted)]:
        Image.fromarray(quantize(rgb)).save(output/(name+'.png'), pnginfo=png_info)


def render_slot(source, output, config, grid_enabled=True, raster_input=False):
    from baseline import resolve, V45_ID
    from edit_parameter_context import ParameterContext, RuntimeColor
    from grid_models import default_response
    from residual_grid import evaluate

    binary = core.compiler.pack(config)
    entry, = core.compiler.unpack(binary)['entries']
    context = ParameterContext(RuntimeColor.from_capture(*resolve(V45_ID)))
    model = context.build(**core.slot_native_parameters(context, entry))
    if raster_input:
        target, predicted, metadata = raster_native(source, output, {}, model)
    else:
        target, predicted, metadata = raw_photo(source, None, output, {}, model, {}, False,
                                                reference_model=context.base)
        metadata['reference_kind'] = 'slot-baseline'
    response = default_response()
    if grid_enabled:
        report_progress(output, '应用槽位整数网格')
        grid = np.asarray(entry['grid_5x9x9']['coefficients']).reshape(3,405).T
        predicted = apply_rows(predicted, lambda rows: evaluate(
            rows.reshape(-1, 3), grid, response).reshape(rows.shape),
            progress=lambda fraction:report_progress(output, '应用槽位整数网格', fraction))
    save_preview_images(output, target, predicted)
    height, width = target.shape[:2]
    result = dict(schema='r5-slot-photo-preview/1', source_sha256=digest(source),
        **metadata, width=width, height=height, slot=entry['number'], slot_name=entry['full_name'],
        slot_bin_sha256=core.sha(binary), endpoint=0, baseline_dataset=V45_ID,
        grid_effect_enabled=grid_enabled, grid_response=response, frontend_approximate=True)
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def render(source, job, output, pc=False, grid_key=None, grid_enabled=True, raster_input=False):
    output.mkdir(parents=True, exist_ok=True)
    pc = bool(pc or grid_key)
    pc_sha = digest(job/'pc_compensation.json') if pc else None
    grid_sha = native_variant = None
    from baseline import read_job
    recipe, model = read_job(job)
    if grid_key:
        from grid_distillation import load_result, model_for_config
        grid_report, _, grid_sha = load_result(job,grid_key)
        native_variant = grid_report['identity'].get('selected_bin_sha256')
        if 'selected_config' in grid_report:
            model = model_for_config(job,grid_report['selected_config'])
    audit = json.loads((job/'input_audit.json').read_text())
    from core import target_identity
    identity = target_identity(job)
    lut_sha = identity['sha256'] if identity['kind']=='lut' else None
    recipe_sha = digest(job/'fit/recipe.json')
    source_sha = digest(source)
    if raster_input:
        target, predicted, metadata = raster_native(source, output, recipe, model)
    else:
        target, predicted, metadata = raw_photo(source,job,output,recipe,model,audit,lut_sha is not None)
    if identity != target_identity(job) or recipe_sha != digest(job/'fit/recipe.json'):
        raise ValueError('任务配方或目标在渲染期间发生变化，请重新生成预览')
    np.savez_compressed(output/'render_inputs.npz',native=predicted,target=target)
    if grid_key:
        predicted=compensation(job,output,predicted,pc,grid_key,grid_enabled)
        if grid_sha!=load_result(job,grid_key)[2]:raise ValueError('压缩参数在渲染期间发生变化')
    elif pc:
        predicted=compensation(job,output,predicted,pc,None,grid_enabled)
    if pc and pc_sha!=digest(job/'pc_compensation.json'):
        raise ValueError('PC 补偿参数在渲染期间发生变化，请重新生成预览')
    save_preview_images(output, target, predicted)
    height, width = target.shape[:2]
    result = dict(schema='r5-photo-preview/3', source_sha256=source_sha, **metadata,
        frontend_revision=FRONTEND_REVISION, target_source=identity,
        lut_sha256=lut_sha, recipe_sha256=recipe_sha, samples=width*height,
        width=width, height=height, coverage=1.0,
        raw_unchanged=digest(source)==source_sha if not raster_input else None,
        edit_runtime_used=False, frontend_approximate=True, white_balance=recipe.get('white_balance'),
        grid_key=grid_key,grid_sha256=grid_sha,native_variant=native_variant,
        algorithm=('compressed' if grid_key else 'pc' if pc else 'native'),
        grid_effect_enabled=bool(grid_enabled),grid_effect_applied=bool(pc and grid_enabled),pc_compensation_enabled=pc,
        pc_compensation_sha256=pc_sha, grid_response=response_identity(job,pc,grid_key),
        preview_long_edge=PREVIEW_LONG_EDGE,
        limits=(['普通照片已渲染成 RGB；由 sRGB 近似映射到训练前端，仅供效果参考。']
                if raster_input else ['RAW 使用 LibRaw 双线性去马赛克及近似前端；实机及 Edit 输出需另作对照。']))
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def reuse(source,job,output,pc=False,grid_key=None,grid_enabled=True):
    """对同一份照片缓存重新应用所选网格。"""
    from grid_distillation import load_result
    value=json.loads((source/'result.json').read_text())
    if value.get('frontend_revision') != FRONTEND_REVISION:
        raise ValueError('历史 RAW 预览使用旧版前端，请重新上传 RAW 生成包含 SSCS 的预览')
    identity = value.get('target_source') or dict(kind='lut',sha256=value.get('lut_sha256'))
    if value['recipe_sha256']!=digest(job/'fit/recipe.json') or not core.target_matches({'target_source':identity},job):
        raise ValueError('照片缓存与当前任务不一致')
    with np.load(source/'render_inputs.npz',allow_pickle=False) as data:
        native=data['native'];target=data['target']
    output.mkdir(parents=True,exist_ok=True)
    pc=bool(pc or grid_key)
    pc_sha=digest(job/'pc_compensation.json') if pc else None
    grid_sha=None
    native_variant=None
    if grid_key:
        grid_report,_,grid_sha=load_result(job,grid_key)
        native_variant=grid_report['identity'].get('selected_bin_sha256')
    if native_variant != value.get('native_variant'):
        raise ValueError('所选配方的原生参数与缓存不同，请重新上传同一张照片')
    predicted=compensation(job,output,native,pc,grid_key,grid_enabled)
    if pc and pc_sha!=digest(job/'pc_compensation.json'):raise ValueError('PC参数发生变化')
    if grid_key and grid_sha!=load_result(job,grid_key)[2]:raise ValueError('压缩参数发生变化')
    np.savez_compressed(output/'render_inputs.npz',native=native,target=target)
    report_progress(output,'保存参考图和拟合图')
    for name,rgb in [('lut',target),('model',predicted)]:
        Image.fromarray(quantize(rgb)).save(output/(name+'.png'))
    value.update(grid_effect_enabled=bool(grid_enabled),grid_effect_applied=bool(pc and grid_enabled),pc_compensation_enabled=pc,pc_compensation_sha256=pc_sha,
        grid_response=response_identity(job,pc,grid_key),
                 grid_key=grid_key,grid_sha256=grid_sha,
                 algorithm='compressed' if grid_key else 'pc' if pc else 'native',
                 decoded_samples_reused=True,raw_rechecked_this_render=False)
    (output/'result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('job', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--pc',action='store_true')
    parser.add_argument('--grid')
    parser.add_argument('--reuse',action='store_true')
    parser.add_argument('--raster-input',action='store_true')
    parser.add_argument('--no-grid-effect',action='store_true')
    parser.add_argument('--slot-config',type=Path)
    args = parser.parse_args()
    options = {} if args.reuse else {'raster_input': args.raster_input}
    if args.slot_config:
        render_slot(args.source, args.output, json.loads(args.slot_config.read_text()),
                    not args.no_grid_effect, args.raster_input)
    else:
        (reuse if args.reuse else render)(args.source, args.job, args.output,args.pc,args.grid,not args.no_grid_effect,**options)
