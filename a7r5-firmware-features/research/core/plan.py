"""把配置解析成与原厂基线绑定的组件修改计划。"""
import hashlib
import json
from pathlib import Path
import re

FEATURES = Path(__file__).resolve().parents[1]
ROOT = FEATURES.parent
GL = FEATURES / 'native24-combined/dependencies/native12-combined/upstream/firmware/r5/src'
GL_DATA = GL / 'dependencies/colour_fields.json'
GL_PREFIX = '0110_backup/SYSIPSX-DSLR/GL/'
PART_SUM = '0701_part_image_sum/part_image.sum'
BACKUP_SUM = '0111_backup_sum/backup.sum'
ID = re.compile(r'[a-z0-9][a-z0-9.-]*')
NATIVE24_OPTIONS = ('sd-import', 'preview', 'group-memory', 'tuning', 'selection-restore')
NATIVE24_MODULES = {'look24', 'look24-core', *('look24-' + option for option in NATIVE24_OPTIONS)}
WBI_IMAGE = '0700_part_image/dev/nflasha5'
AVCAM_IMAGE = '0700_part_image/dev/nflasha3'
COLOR_MODULES = {'look-fl2-fl3': 'fl23', 'look-factory-six': 'factory_six'}
CAPTURE_MODULES = {'lens-af-compat': 'lens_af', 'photo-aspect-ratios': 'aspect'}
FULL_OPTIONAL = {'photo-framing-markers', 'video-ntsc-prompt', 'photo-electronic-shutter-sound',
                 'color-r6-st', 'color-awb-priority'}
SOUND = 'photo-electronic-shutter-sound'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def resolve_modules(requested, modules, base):
    ordered, visiting, finished = [], set(), set()

    def visit(name):
        require(name in modules, '缺少模块或依赖 ' + name)
        require(name not in visiting, '模块依赖成环 ' + name)
        if name in finished:
            return
        item = modules[name]
        require(base in item['supported_bases'], f'模块 {name} 未适配基线 {base}')
        visiting.add(name)
        for dep in sorted(item['requires']):
            visit(dep)
        visiting.remove(name)
        finished.add(name)
        ordered.append(name)

    for name in sorted(requested):
        visit(name)
    claims = {}
    for name in ordered:
        item = modules[name]
        conflicts = sorted(finished.intersection(item['conflicts']))
        require(not conflicts, f'模块 {name} 与 {", ".join(conflicts)} 互斥')
        for claim in item['claims']:
            require(claim not in claims, f'资源 {claim} 同时由 {claims.get(claim)} 与 {name} 声明')
            claims[claim] = name
    return ordered, claims


def merge_component(rows, size):
    """合并定长修改。只有相同前像和结果的重叠字节可以去重。"""
    seen = {}
    for row in rows:
        at = row['offset']
        before, after = (bytes.fromhex(row[k]) for k in ('before', 'after'))
        require(type(at) is int and 0 <= at < size and at + len(before) <= size
                and len(before) == len(after) and before != after, '组件补丁范围或前像无效')
        for i, (old, new) in enumerate(zip(before, after)):
            previous = seen.get(at + i)
            require(previous is None or previous[:2] == (old, new),
                    f'组件补丁冲突 {at+i:#x}，当前模块 {row["module"]}，先前模块 {previous and previous[2]}')
            seen[at + i] = (old, new, row['module'])
    return seen


def make_plan(config, feature_dir=FEATURES):
    require(isinstance(config, dict) and {'base', 'modules'} <= set(config)
            and set(config) <= {'base', 'modules', 'variants'}, '配置需声明 base 与 modules，可选 variants')
    base_id, requested = config['base'], config['modules']
    require(isinstance(base_id, str) and ID.fullmatch(base_id), '基线 ID 无效')
    require(isinstance(requested, list) and requested
            and all(isinstance(n, str) and ID.fullmatch(n) for n in requested)
            and len(requested) == len(set(requested)), '模块列表为空、重复或含无效 ID')
    variants = config.get('variants', {})
    require(isinstance(variants, dict) and (not variants or variants == {SOUND: 'custom-dual-full'}),
            '未知模块变体')
    dual_sound = bool(variants)
    if dual_sound:
        full_combo = {'look24', *COLOR_MODULES, *CAPTURE_MODULES, *FULL_OPTIONAL}
        selected_combo = set(requested)
        selective_combo = {'look24', 'look-fl2-fl3', 'photo-aspect-ratios',
                           *FULL_OPTIONAL, SOUND}
        require(selected_combo == full_combo or selected_combo == selective_combo,
                '双组声音变体只支持已登记的全功能或 4.23 选择性组合')
    base_path = feature_dir / 'bases' / (base_id + '.json')
    require(base_path.is_file(), '未知原厂基线 ' + base_id)
    base = read_json(base_path)
    require(base['schema'] == 1 and base['id'] == base_id and base['wbi'] == 'preserve-stock',
            '当前构建器要求已登记的原厂布局与 WBI 策略')
    modules, module_hashes = {}, {}
    manifests = [*feature_dir.glob('*/module.json'), *feature_dir.glob('look24/legacy/*/module.json')]
    for path in sorted(manifests):
        row = read_json(path)
        name = path.parent.name
        require(row['schema'] == 1 and row['id'] == name and ID.fullmatch(name), '模块清单身份不符 ' + name)
        require(name not in modules, '模块清单重复 ' + name)
        require(path.parent.parent == feature_dir or name in NATIVE24_MODULES - {'look24'},
                '历史 24 槽清单身份不符 ' + name)
        modules[name] = row
        module_hashes[name] = digest(path)
    ordered, claims = resolve_modules(requested, modules, base_id)

    component_rows, fields, owners = {}, [], {}
    native24, native_options, colors, capture = False, set(), set(), set()
    for name in ordered:
        for change in modules[name]['changes']:
            if dual_sound and name == SOUND:
                continue
            builder = change['builder']
            if builder == 'component-bytes':
                component = change['component']
                require(component in base['components'], '未知组件 ' + component)
                component_rows.setdefault(component, []).extend(dict(row, module=name) for row in change['patches'])
            elif builder == 'gl-fields':
                for field in change['fields']:
                    key, lo, length = (field[k] for k in ('property', 'offset', 'bytes'))
                    require(type(key) is int and type(lo) is int and type(length) is int
                            and 0 <= key and 0 <= lo and length > 0, '模板字段范围无效')
                    ranges = owners.setdefault(key, [])
                    require(all(lo + length <= start or lo >= end for start, end in ranges),
                            f'模板字段冲突 {key:#x}+{lo:#x}')
                    ranges.append((lo, lo + length))
                    fields.append(dict(field, module=name))
            elif builder == 'native24-runtime':
                require(name == 'look24-core' and not native24, '24 槽运行时声明重复或不符')
                native24 = True
            elif builder == 'native24-complete':
                require(name == 'look24' and not native24 and not native_options, '24 槽完整模块声明重复或不符')
                native24 = True
                native_options.update(NATIVE24_OPTIONS)
            elif builder == 'native24-option':
                option = change['option']
                require(option in NATIVE24_OPTIONS and option not in native_options
                        and name == 'look24-' + option, '24 槽开关声明不符')
                native_options.add(option)
            elif builder == 'shared-color':
                option = change['option']
                require(COLOR_MODULES.get(name) == option and option not in colors, '色彩模块声明不符')
                colors.add(option)
            elif builder == 'shared-capture':
                option = change['option']
                require(CAPTURE_MODULES.get(name) == option and option not in capture, '拍摄模块声明不符')
                capture.add(option)
            else:
                raise ValueError('未知组件构建器 ' + builder)
    selective_417 = (native24 and native_options == set(NATIVE24_OPTIONS)
                     and colors == {'fl23'}
                     and set(ordered) == {'look24', 'look-fl2-fl3', *FULL_OPTIONAL})
    if selective_417:
        for field in read_json(GL_DATA):
            if field['purpose'].startswith('FL23'):
                raw = bytes.fromhex(field['hex'])
                fields.append(dict(property=field['key'], offset=field['offset'], bytes=len(raw),
                                   value_sha256=sha(raw), module='look-fl2-fl3'))
    for component, rows in component_rows.items():
        merge_component(rows, base['components'][component]['bytes'])
    require(not native_options or native24, '24 槽选项缺少基础运行时')
    require(component_rows or fields or native24 or colors or capture, '配置没有有效修改')
    relocated_sound = False
    if capture:
        allowed = NATIVE24_MODULES | CAPTURE_MODULES.keys()
        full_capture = (native24 and native_options == set(NATIVE24_OPTIONS)
                        and colors == set(COLOR_MODULES.values())
                        and capture == set(CAPTURE_MODULES.values()))
        selective_capture = (native24 and native_options == set(NATIVE24_OPTIONS)
                             and colors == {'fl23'} and capture == {'aspect'}
                             and set(ordered) == {'look24', 'look-fl2-fl3', 'photo-aspect-ratios',
                                                  *FULL_OPTIONAL})
        if full_capture or selective_capture:
            if full_capture:
                allowed.update(COLOR_MODULES, FULL_OPTIONAL)
            else:
                allowed.update({'look-fl2-fl3'}, FULL_OPTIONAL)
            relocated_sound = SOUND in ordered and not dual_sound
        require(set(ordered) <= allowed, '拍摄模块与下列模块的组合尚未验证 ' + ', '.join(sorted(set(ordered) - allowed)))
    elif native24 or colors:
        allowed = NATIVE24_MODULES | COLOR_MODULES.keys() | {'photo-framing-markers', 'video-ntsc-prompt'}
        selective_417 = (native24 and native_options == set(NATIVE24_OPTIONS)
                         and colors == {'fl23'}
                         and set(ordered) == {'look24', 'look-fl2-fl3', *FULL_OPTIONAL})
        if selective_417:
            relocated_sound = SOUND in ordered and not dual_sound
        else:
            require(set(ordered) <= allowed, '色彩运行时与下列模块的组合尚未验证 ' + ', '.join(sorted(set(ordered) - allowed)))
    if relocated_sound:
        sound = component_rows.pop('cpapp-b.bin', [])
        require(sound and all(row['module'] == 'photo-electronic-shutter-sound' for row in sound),
                '共享 CP 的独立声音补丁声明不符')
    targets = {base['components'][name]['image'] for name in component_rows}
    if native24 or colors:
        targets.update(row['image'] for row in base['components'].values())
    if capture:
        targets.add(base['components']['cpapp-b.bin']['image'])
        if 'aspect' in capture:
            targets.update((base['components']['usr/lib/appFw.so']['image'], AVCAM_IMAGE))
    if native24 or capture:
        targets.add(WBI_IMAGE)
    targets = sorted(targets)
    if targets:
        targets.append(PART_SUM)
    if fields:
        require(base['gl_templates'] and all(name.startswith(GL_PREFIX) for name in base['gl_templates']),
                '基线缺少有效的地区模板清单')
        targets += [*base['gl_templates'], BACKUP_SUM]
    plan = dict(schema=1, base=base, base_manifest_sha256=digest(base_path), requested=sorted(requested),
                modules=[dict(id=n, label=modules[n]['label'], revision=modules[n]['revision'],
                              sha256=module_hashes[n]) for n in ordered],
                claims=claims, component_patches=component_rows, template_fields=fields,
                archive_targets=sorted(targets), camera_io=False)
    if dual_sound:
        plan['variants'] = variants.copy()
        plan['claims']['ap.custom-shutter-sound'] = SOUND
    if native24:
        plan['native24'] = dict(disabled=sorted(set(NATIVE24_OPTIONS) - native_options), wbi='marker-2-to-3',
                                companion='R5NATIVE.BIN' if 'sd-import' in native_options else None)
        if relocated_sound:
            plan['native24']['sound_layout'] = 'relocated-fl23'
        elif dual_sound:
            plan['native24']['sound_layout'] = 'custom-dual-full'
    if colors:
        plan['color_modules'] = {key: key in colors for key in COLOR_MODULES.values()}
    if capture:
        plan['capture_modules'] = {key: key in capture for key in CAPTURE_MODULES.values()}
        plan['capture_modules']['wbi'] = 'marker-2-to-3'
    return plan


def configuration(plan):
    """从构建锁恢复完整选择，避免独立复验丢掉显式声音变体。"""
    result = dict(base=plan['base']['id'], modules=plan['requested'])
    if plan.get('variants'):
        result['variants'] = plan['variants']
    return result


def require_base(path, plan):
    require(path.is_file() and not path.is_symlink() and not path.resolve().is_relative_to('/dev'),
            '原厂输入必须是普通 DAT 文件')
    pin = plan['base']['dat']
    require(path.stat().st_size == pin['bytes'] and digest(path) == pin['sha256'],
            '原厂 DAT 摘要或长度不匹配')
