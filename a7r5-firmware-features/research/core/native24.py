"""组合模式只构建一次 AP、CP、图标和 WBI，并沿用 4.19 的文件系统校验。"""
import os
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def prepare_wbi_marker(source, output, *, source_sha256, target_sha256):
    """从精确 WBI2 前像生成 WBI3；校验完成后才发布，禁止覆盖。"""
    source, output = Path(source), Path(output)
    require(source.is_file() and not source.is_symlink() and source.stat().st_size >= 512,
            'WBI 前像长度或路径无效')
    require(digest(source) == source_sha256, 'WBI 完整前像不符')
    with source.open('rb') as stream:
        header = stream.read(512)
        require(header[:4] == b'WBI2', 'WBI 前像必须为 WBI2，拒绝全零或未知头')
        with tempfile.TemporaryDirectory(prefix='.wbi-marker-', dir=output.parent) as temporary:
            staged = Path(temporary) / 'wbi.bin'
            with staged.open('xb') as target:
                target.write(b'WBI3' + header[4:])
                shutil.copyfileobj(stream, target, 1 << 20)
            require(staged.stat().st_size == source.stat().st_size
                    and digest(staged) == target_sha256, 'WBI3 完整目标摘要或长度不符')
            os.link(staged, output)

from .plan import FEATURES, ROOT, WBI_IMAGE, digest, read_json, require, sha
from . import capture

NATIVE = FEATURES / 'firmware-runtime'
REFERENCE = FEATURES / 'independent/profiles/native24-stock'
RUNTIME_COMPONENTS = FEATURES / 'look24/runtime-components.json'
MATERIALS = FEATURES / 'materials'
AP = 'usr/lib/appFw.so'
CP = 'cpapp-b.bin'


def resources(plan):
    paths = [*sorted(NATIVE.glob('*.py')), *sorted((NATIVE / 'runtime').glob('*')),
             NATIVE / 'layout.json', NATIVE / 'derive-matches.json', NATIVE / 'runtime-inputs.json',
             NATIVE / 'release417/container_package.py', REFERENCE / 'components.json',
             REFERENCE / 'resources.json', RUNTIME_COMPONENTS, MATERIALS / 'recipes.json']
    if plan['native24']['companion']:
        paths.append(REFERENCE / plan['native24']['companion'])
    if plan['native24'].get('sound_layout') == 'custom-dual-full':
        sound = FEATURES / 'photo-electronic-shutter-sound'
        paths += [p for p in sorted(sound.rglob('*')) if p.is_file()
                  and ('verification' not in p.relative_to(sound).parts)
                  and p.suffix in ('.py', '.c', '.h', '.S', '.ld', '.json', '.txt')]
    return paths


def color_resources():
    history = MATERIALS / 'source'
    historical_code = history / 'analysis/custom-features-20261021-03/research-materials-v3/code'
    dependency = NATIVE / 'dependencies/native12-combined'
    six = FEATURES / 'look-factory-six/src'
    return [ROOT / 'a7r5-desktop/scripts/feature_builder.py', NATIVE / 'build_stock_color.py',
            six / 'build_legacy_six.py', six / 'legacy_six.py', six / 'legacy_six_cp.S',
            *sorted((FEATURES / 'look-fl2-fl3/raw').glob('*.py')),
            *sorted((FEATURES / 'look-fl2-fl3/raw').glob('*.S')),
            FEATURES / 'photo-electronic-shutter-sound/bindings/upstream/src/lib/thumb_link.py',
            dependency / 'upstream/firmware/r5/src/lib/thumb_ops.py',
            MATERIALS / 'reproduce.py', MATERIALS / 'recipes.json', MATERIALS / 'matrix-inline.json',
            MATERIALS / 'joint-layout.json', MATERIALS / 'six-looks.json',
            *sorted((MATERIALS / 'upstream-default-six').glob('*.a7look')),
            historical_code / 'assembler.py', historical_code / 'cp_runtime.py',
            history / 'a7r5-qemu/source/guest/look-joint.S',
            *(dependency / name for name in ('patches.py', 'selection.S', 'integration.S', 'integration.ld')),
            dependency / 'upstream/UPSTREAM_SNAPSHOT.json']


def run_builder(work, plan, output, script, *options):
    command = [str(ROOT / '.venv/bin/python'), '-B', str(NATIVE / script), '--stock', str(work),
               '--output', str(output), *options]
    for name, enabled in plan.get('color_modules', {}).items():
        if enabled:
            command.append('--' + name.replace('_', '-'))
    result = subprocess.run(command, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    require(result.returncode == 0, '色彩组件构建失败\n' + result.stderr)


def build_runtime(work, plan, scratch):
    output = scratch / 'native24'
    options = []
    for name in plan['native24']['disabled']:
        options += ['--disable', name]
    sound_layout = plan['native24'].get('sound_layout')
    if sound_layout == 'relocated-fl23':
        options.append('--relocated-sound')
    elif sound_layout == 'custom-dual-full':
        options.append('--custom-sound')
    run_builder(work, plan, output, 'build.py', *options)
    receipt = read_json(output / 'build.json')
    require(receipt['profile'] == 'native24-stock' and receipt['base_DAT_sha256'] == plan['base']['dat']['sha256']
            and receipt['disabled_modules'] == plan['native24']['disabled']
            and receipt.get('sound_layout') == sound_layout
            and receipt.get('color_modules') == plan.get('color_modules'), '24 槽构建身份不符')
    for name, pin in receipt['components'].items():
        path = output / name
        require(path.stat().st_size == pin['bytes'] and digest(path) == pin['sha256'], '24 槽组件摘要不符 ' + name)
    if not plan['native24']['disabled'] and not plan.get('color_modules'):
        expected = read_json(RUNTIME_COMPONENTS)
        require(expected['base_DAT_sha256'] == plan['base']['dat']['sha256']
                and receipt['components'] == expected['components'],
                '24 槽全开构建与当前修订的固定组件摘要不符')
    return output, receipt


def module_strings(work, output, plan):
    if not plan.get('color_modules', {}).get('factory_six'):
        return {}
    spec = importlib.util.spec_from_file_location('compose_historical_strings', MATERIALS / 'reproduce.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recipe = read_json(MATERIALS / 'recipes.json')
    require(len(recipe['resources']) == 68, '六款名称银行数量不符')
    pins = {}
    for row in recipe['resources']:
        name = row['path'].removeprefix('components/usr')
        original = module.path_in(work, row['path']).read_bytes()
        target = module.resource(original, row, recipe['names'])
        (output / Path(name).name).write_bytes(target)
        pins[name] = row['before_sha256']
    return pins


def apply_usr(work, manifest, plan, scratch, apply_rows, output, capture_output, capture_receipt, pins):
    sys.path.insert(0, str(NATIVE / 'release417'))
    try:
        from container_package import AppendImagePatch, ImageBinding, prepare_usr, reader
    finally:
        sys.path.remove(str(NATIVE / 'release417'))
    usr_image = manifest['components'][AP]['image']
    source_usr = work / 'archive' / usr_image
    require(digest(source_usr) == pins['stock_partitions']['nflasha15'], 'USR 分区前像不符')
    aspect = capture_receipt.get('aspect', False)
    usr_pins = pins['stock_USR_files'] if plan.get('native24') or aspect else {
        '/lib/appFw.so': pins['stock_USR_files']['/lib/appFw.so']}
    if aspect:
        strings = {name.removeprefix('usr'): row['sha256'] for name, row in manifest['components'].items()
                   if name.startswith('usr/share/app/string_')}
        usr_pins |= strings
        require({Path(path).name for path in usr_pins if path != '/lib/appFw.so'} ==
                set(capture_receipt['resources']), '比例资源集合与原厂 USR 不符')
        usr_pins[capture.MPR_PATH] = capture_receipt['MPR']['source_sha256']
        output = capture_output
    else:
        usr_pins |= module_strings(work, output, plan)

    fs = reader(source_usr.read_bytes())
    bindings = {}
    staged = scratch / 'usr-components'
    staged.mkdir()
    for target, original_pin in usr_pins.items():
        file = output / Path(target).name
        raw = file.read_bytes()
        if target == '/lib/appFw.so' and AP in plan['component_patches']:
            raw = apply_rows(raw, plan['component_patches'][AP], AP,
                             factory_six=plan.get('color_modules', {}).get('factory_six', False))
        (staged / Path(target).name).write_bytes(raw)
        inode = fs.walk(target)
        old = fs.read_inode(inode)
        bindings[target] = ImageBinding(inode, len(old), len(raw), original_pin, sha(raw))
    del fs, old, raw
    patch_type = type('Native24ComposePatch', (AppendImagePatch,), {'_bindings': bindings})
    new_usr = scratch / 'usr.bin'
    prepare_usr(source_usr, new_usr, scratch, staged, patch_type, source_sha=pins['stock_partitions']['nflasha15'])
    new_usr.replace(source_usr)
    result = {AP: dict(manifest['components'][AP], bytes=bindings['/lib/appFw.so'].target_bytes,
                       sha256=bindings['/lib/appFw.so'].target_sha256)}
    if aspect:
        mpr = bindings[capture.MPR_PATH]
        result[capture.MPR] = dict(image=usr_image, path=capture.MPR_PATH,
                                   bytes=mpr.target_bytes, sha256=mpr.target_sha256)
    result.update({f'usr{name}': dict(manifest['components'][f'usr{name}'], bytes=binding.target_bytes,
                                     sha256=binding.target_sha256)
                   for name, binding in bindings.items() if name.startswith('/share/app/string_')})
    return result


def apply(work, manifest, plan, scratch, apply_rows):
    sys.path.insert(0, str(NATIVE / 'release417'))
    try:
        from container_package import prepare_cp
    finally:
        sys.path.remove(str(NATIVE / 'release417'))
    native = plan.get('native24')
    colors = plan.get('color_modules')
    output = None
    if native:
        output, _ = build_runtime(work, plan, scratch)
    elif colors:
        output = scratch / 'stock-color'
        run_builder(work, plan, output, 'build_stock_color.py')
    capture_output = scratch / 'capture'
    capture_receipt = capture.build(work, plan, capture_output, output) if plan.get('capture_modules') else {}
    pins = read_json(REFERENCE / 'components.json')
    aspect = capture_receipt.get('aspect', False)
    result = {}
    if native or colors or aspect:
        result = apply_usr(work, manifest, plan, scratch, apply_rows, output, capture_output, capture_receipt, pins)
    cp = (capture_output if capture_receipt else output) / CP
    shutil.copyfile(cp, work / 'components' / CP)
    result[CP] = dict(manifest['components'][CP], sha256=digest(cp))
    if aspect:
        result[capture.AVCAM] = capture.apply_avcam(work, capture_output, scratch, prepare_cp)
    if not (native or capture_receipt):
        return result
    source_wbi = work / 'archive' / WBI_IMAGE
    require(digest(source_wbi) == pins['stock_partitions']['nflasha5'], 'WBI 分区前像不符')
    new_wbi = scratch / 'wbi.bin'
    wbi_recipe = read_json(MATERIALS / 'recipes.json')['WBI']
    require(pins['stock_partitions']['nflasha5'] == wbi_recipe['before_sha256'],
            'WBI 配方与原厂分区前像不一致')
    prepare_wbi_marker(source_wbi, new_wbi,
                       source_sha256=wbi_recipe['before_sha256'],
                       target_sha256=wbi_recipe['after_sha256'])
    new_wbi.replace(source_wbi)
    return result


def companion(plan):
    name = plan.get('native24', {}).get('companion')
    if not name:
        return None
    pin = read_json(REFERENCE / 'resources.json')['companion']
    file = REFERENCE / name
    require(pin['file'] == name and digest(file) == pin['sha256'], '随包配方摘要不符')
    return file
