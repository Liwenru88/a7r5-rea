"""预构建功能补丁和原DAT引擎；运行时不调用编译器。"""
import gzip
import html
import json
import os
from pathlib import Path
import tempfile
from common import ROOT, digest, load, progress, safe, save, sha, write_payload
import component_recipe as recipe_engine
import native24_preset

KEYS = ('fl23', 'looks', 'ntsc', 'sound')


def selection(flags):
    if isinstance(flags, dict) and set(flags) == {'native24'} and flags['native24'] is True:
        return 'native24'
    if not isinstance(flags, dict) or set(flags) != set(KEYS) or any(type(v) is not bool for v in flags.values()):
        raise ValueError('请明确选择四项功能')
    return ''.join(str(int(flags[k])) for k in KEYS)


def apply(work, flags, receipt):
    key = selection(flags);recipes = load(ROOT/'recipes.json')
    manifest = load(work/'manifest.json')
    if manifest['source']['sha256'] != recipes['official_DAT_sha256'] or (manifest['header']['major'], manifest['header']['minor']) != (4, 0):
        raise ValueError('仅适配指定官方4.00原包')
    path = ROOT/'feature-patches'/(key+'.json.gz')
    if sha(path) != load(ROOT/'feature-patches/manifest.json')[key]['sha256']:raise ValueError('组合补丁摘要变化')
    records = json.loads(gzip.decompress(path.read_bytes()))
    prepared = []
    for name, record in records.items():
        target = recipe_engine.path_in(work, name);original = target.read_bytes()
        result = recipe_engine.patch(original, record)
        if result != original:prepared.append((target, result))
    if flags['looks']:
        for record in recipes['resources']:
            target = recipe_engine.path_in(work, record['path'])
            prepared.append((target, recipe_engine.resource(target.read_bytes(), record, recipes['names'])))
    if any(flags.values()):
        record = recipes['WBI'];target = recipe_engine.path_in(work, record['path'])
        prepared.append((target, recipe_engine.patch(target.read_bytes(), record)))
    # 这里只写新建工作副本；所有前像先验证，失败时不会进入pack。
    for path, raw in prepared:path.write_bytes(raw)
    value = dict(features=flags, files=[dict(path=str(p.relative_to(work)), sha256=digest(raw)) for p, raw in prepared],
                 camera_IO=False, device_acceptance_verified=False)
    save(receipt, value)
    return value


def build_native24(tool, work, output, guide, guide_text):
    resources = ROOT/'native24'
    filters = safe(resources/native24_preset.FILTER_NAME, file=True).read_bytes()
    if digest(filters) != native24_preset.FILTER_SHA256:
        raise ValueError('4.17 配套滤镜库摘要不符')
    native24_preset.apply(work, resources)
    destination = output.with_name(native24_preset.FILTER_NAME)
    sidecar = output.with_suffix(output.suffix+'.json')
    # 先在目标卷验证全部产物，最后发布 DAT，避免失败时留下不完整的交付。
    with tempfile.TemporaryDirectory(prefix='.a7r5-native24-', dir=output.parent) as temporary:
        folder = Path(temporary)
        staged = folder/output.name
        result = tool.pack(work, staged, native24_preset.VERSION,
                           ROOT/'keys/research-signing-private.pem', ROOT/'keys/research-public.pem')
        if result['sha256'] != native24_preset.DAT_SHA256:
            raise ValueError('封包结果与已验证的 4.17 DAT 摘要不符')
        filter_stage = write_payload(folder/destination.name, filters)
        guide_stage = write_payload(folder/guide.name, guide_text.encode())
        links = ((filter_stage, destination), (guide_stage, guide),
                 (staged.with_suffix(staged.suffix+'.json'), sidecar), (staged, output))
        published = []
        try:
            for source, target in links:
                os.link(source, target)
                published.append((source, target))
        except OSError:
            for source, target in reversed(published):
                if target.exists() and target.samefile(source):
                    target.unlink()
            raise
    return dict(result, filter_file=str(destination), filter_sha256=native24_preset.FILTER_SHA256,
                version=native24_preset.VERSION)


def build(request, job):
    from a7r5dat import tool
    source = safe(request['source'], file=True);output = safe(request['output'])
    key = selection(request['features'])
    preset = key == 'native24'
    if preset and request.get('version') != native24_preset.VERSION:
        raise ValueError('24 槽滤镜与构图标记预设的版本固定为 4.17')
    if sha(source) != load(ROOT/'recipes.json')['official_DAT_sha256']:raise ValueError('请选择本工具适配的官方4.00原包')
    guide = output.with_suffix('.更新说明.html')
    destinations = [output, output.with_suffix(output.suffix+'.json'), guide]
    if preset:
        destinations.append(output.with_name(native24_preset.FILTER_NAME))
    if len(set(destinations)) != len(destinations) or any(p.exists() or p.is_symlink() for p in destinations):
        raise FileExistsError('输出、说明或配套滤镜库路径冲突，请选择空目录和新的 DAT 文件名')
    if not output.parent.is_dir():raise ValueError('输出目录不存在')
    guide_text = (ROOT/'card-guide.html').read_text().replace('{{PACKAGE}}', html.escape(str(output)))
    if preset:
        notes = ('<section><h2>4.17 配套滤镜与构图标记</h2>'
                 '<p>随包导出的 <code>R5NATIVE.BIN</code> 包含十二款正式配方。'
                 '固件支持 24 槽，空槽可通过 Color Lab 配置。'
                 '完成固件更新后，将 BIN 放在 SD 卡根目录并关机再开机，触发滤镜库导入。</p>'
                 '<p>此预设同时包含照片 2.35:1 构图标记。已装其他 4.17 版本的机身能否接受同版本更新仍待验证。</p></section>')
        guide_text = guide_text.replace('</html>', notes+'</html>')
    with tempfile.TemporaryDirectory(prefix='firmware-', dir=job) as temporary:
        work = Path(temporary)/'work'
        progress('验证并解包官方4.00固件')
        tool.unpack(source, work)
        if preset:
            progress('重建 4.17 预设，并核对签名、输出帧与完整 DAT 摘要')
            result = build_native24(tool, work, output, guide, guide_text)
        else:
            progress('应用所选功能：'+key)
            apply(work, request['features'], job/'components.json')
            progress('签名封装，并独立解密核对全部输出帧')
            result = tool.pack(work, output, request.get('version') or None,
                               ROOT/'keys/research-signing-private.pem', ROOT/'keys/research-public.pem')
            with guide.open('x') as stream:
                stream.write(guide_text)
    result.update(output=str(output), guide=str(guide), features=request['features'], camera_IO=False,
                  device_acceptance_verified=False)
    save(job/'result.json', result)
    progress('更新包与使用说明已生成；尚未在相机上执行更新')
    return result
