"""预构建功能补丁和原DAT引擎；运行时不调用编译器。"""
import gzip
import html
import json
from pathlib import Path
import tempfile
from common import ROOT, digest, load, progress, safe, save, sha
import component_recipe as recipe_engine

KEYS = ('fl23', 'looks', 'ntsc', 'sound')


def selection(flags):
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


def build(request, job):
    from a7r5dat import tool
    source = safe(request['source'], file=True);output = safe(request['output'])
    key = selection(request['features'])
    if sha(source) != load(ROOT/'recipes.json')['official_DAT_sha256']:raise ValueError('请选择本工具适配的官方4.00原包')
    guide = output.with_suffix('.更新说明.html')
    if any(p.exists() or p.is_symlink() for p in (output, output.with_suffix(output.suffix+'.json'), guide)):
        raise FileExistsError('输出或说明已存在，请选择新的文件名')
    if not output.parent.is_dir():raise ValueError('输出目录不存在')
    with tempfile.TemporaryDirectory(prefix='firmware-', dir=job) as temporary:
        work = Path(temporary)/'work'
        progress('验证并解包官方4.00固件')
        tool.unpack(source, work)
        progress('应用所选功能：'+key)
        apply(work, request['features'], job/'components.json')
        progress('签名封装，并独立解密核对全部输出帧')
        result = tool.pack(work, output, request.get('version') or None,
                           ROOT/'keys/research-signing-private.pem', ROOT/'keys/research-public.pem')
    with guide.open('x') as stream:
        stream.write((ROOT/'card-guide.html').read_text().replace('{{PACKAGE}}', html.escape(str(output))))
    result.update(output=str(output), guide=str(guide), features=request['features'], camera_IO=False,
                  device_acceptance_verified=False)
    save(job/'result.json', result)
    progress('更新包与使用说明已生成；尚未在相机上执行更新')
    return result
