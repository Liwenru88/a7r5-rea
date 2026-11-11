"""本机工程存储、可移植备份和固件配置导出。"""
import base64
import io
import json
import os
import re
from statistics import median
import tempfile
import time
import uuid
import zipfile

import core

LIMIT = 8 * 1024 * 1024
SCHEMA = 'r5-colorlab-project/1'
EDITABLE = ('entries', 'sources', 'drafts', 'selected', 'settings', 'jobs')
STANDARD = 'standard'
SHARED_ST = 'shared-st'
MEDIAN_OFFSET = 'median-offset'
MEDIAN_LOOKS = ('ST', 'PT', 'NT', 'VV', 'VV2', 'FL', 'IN', 'SH')


class Conflict(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def decoded(data):
    return json.loads(data, object_pairs_hook=core.compiler.unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('JSON 数字无效')))


def identifier(value, size=32):
    if not isinstance(value, str) or not re.fullmatch(f'[0-9a-f]{{{size}}}', value):
        raise ValueError('工程或来源标识无效')
    return value


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError('工程名称需为 1～80 个字符')
    return value.strip()


def empty(label):
    return dict(schema=SCHEMA, id=uuid.uuid4().hex, name=name(label), revision=0, updated=0,
                format=4, selected=1, entries=[], sources={}, drafts={}, settings={}, jobs={},
                imports={}, history={}, exports=[])


def slots(value):
    if not isinstance(value, dict) or any(k not in {str(i) for i in range(1, 25)} for k in value):
        raise ValueError('槽位映射无效')
    return value


def draft_entry(entry, number):
    # 草稿允许暂时超出编译范围，但数组结构必须始终可编辑。
    if not isinstance(entry, dict) or set(entry) != {
        'number', 'short_name', 'full_name', 'cc1_delta', 'block13', 'gamma_native_129', 'grid_5x9x9'
    } or type(entry['number']) is not int or entry['number'] != number:
        raise ValueError('草稿配方结构无效')
    for key in ('short_name', 'full_name'):
        if not isinstance(entry[key], str) or len(entry[key]) > 256:
            raise ValueError('草稿名称超出长度')
    grid = entry['grid_5x9x9']
    if not isinstance(grid, dict) or set(grid) != {'coefficients'}:
        raise ValueError('草稿网格结构无效')
    for data, shape in ((entry['cc1_delta'], [3, 8]), (entry['block13'], [3, 16, 6]),
                        (entry['gamma_native_129'], [129]), (grid['coefficients'], [3, 5, 9, 9])):
        core.compiler.integers(data, shape, -2147483648, 2147483647)


def config(value):
    entries = value['entries']
    # v5 导入库保留格式。新建库按实际使用的最高槽号选择格式。
    version = 5 if value['format'] == 5 or any(e['number'] > 12 for e in entries) else 4
    return core.compiler.config(entries, version)


def shared_endpoints(anchor, factory, lower, upper):
    """将每个系数的 B 增量限制到三个绝对端点合法范围的交集。"""
    delta = [max(lo - min(stock), min(value - stock[0], upper - max(stock)))
             for value, stock, lo in zip(anchor, zip(*factory), lower)]
    return [[value + step for value, step in zip(row, delta)] for row in factory]


def shared_entries(entries, factory):
    stock_cc1 = factory['cc1_delta']
    cc1_absolute = [stock_cc1[0], *[
        [base + step for base, step in zip(stock_cc1[0], offset)] for offset in stock_cc1[1:]
    ]]
    compiler = core.compiler
    converted, limited = {}, {'cc1': [], 'matrix': []}
    for number, entry in sorted(entries.items()):
        anchor = shared_endpoints(entry['cc1_delta'][0], cc1_absolute,
                                  compiler.CC1_ENDPOINT_MIN, compiler.CC1_ENDPOINT_MAX)[0]
        hues = [shared_endpoints(base, planes, (compiler.MATRIX_MIN,) * 6, compiler.MATRIX_MAX)
                for base, planes in zip(entry['block13'][0], zip(*factory['block13']))]
        matrix = [list(plane) for plane in zip(*hues)]
        if anchor != entry['cc1_delta'][0]:
            limited['cc1'].append(number)
        if matrix[0] != entry['block13'][0]:
            limited['matrix'].append(number)
        converted[number] = dict(entry, cc1_delta=[anchor, *stock_cc1[1:]], block13=matrix)
    return converted, limited


def median_offsets(presets):
    by_name = {entry['short_name']: entry for entry in presets}
    looks = [by_name[name] for name in MEDIAN_LOOKS]
    cc1, matrix = [], []
    for endpoint in (1, 2):
        cc1.append([round(median(values)) for values in
                    zip(*(look['cc1_delta'][endpoint] for look in looks))])
        plane = []
        for sector in range(16):
            differences = [
                [value - base for value, base in zip(look['block13'][endpoint][sector],
                                                     look['block13'][0][sector])]
                for look in looks
            ]
            plane.append([round(median(values)) for values in zip(*differences)])
        matrix.append(plane)
    return cc1, matrix


def median_entries(entries, offsets):
    """以原配方的 B 为锚，只限幅新生成的 A1／A2。"""
    cc1_offsets, matrix_offsets = offsets
    compiler = core.compiler
    converted, limited = {}, {'cc1': [], 'matrix': []}
    for number, entry in sorted(entries.items()):
        base_cc1 = entry['cc1_delta'][0]
        cc1 = [
            [min(compiler.CC1_ENDPOINT_MAX - base, max(lower - base, step))
             for base, lower, step in zip(base_cc1, compiler.CC1_ENDPOINT_MIN, delta)]
            for delta in cc1_offsets
        ]
        base_matrix = entry['block13'][0]
        proposed = [[[base + step for base, step in zip(sector, steps)]
                     for sector, steps in zip(base_matrix, delta)] for delta in matrix_offsets]
        matrix = [[[min(compiler.MATRIX_MAX, max(compiler.MATRIX_MIN, value)) for value in sector]
                   for sector in plane] for plane in proposed]
        if cc1 != cc1_offsets:
            limited['cc1'].append(number)
        if matrix != proposed:
            limited['matrix'].append(number)
        converted[number] = dict(entry, cc1_delta=[base_cc1, *cc1], block13=[base_matrix, *matrix])
    return converted, limited


def validate_state(value):
    if type(value['format']) is not int or value['format'] not in (4, 5):
        raise ValueError('工程 BIN 格式无效')
    if type(value['selected']) is not int or not 1 <= value['selected'] <= 24:
        raise ValueError('当前槽位无效')
    core.compiler.config(value['entries'])
    core.compile_config(config(value))
    for key, item in slots(value['drafts']).items():
        if not isinstance(item, dict) or set(item) != {'entry', 'source'}:
            raise ValueError('槽位草稿无效')
        draft_entry(item['entry'], int(key))
        validate_source(item['source'], value['imports'])
    if set(slots(value['sources'])) - {str(e['number']) for e in value['entries']}:
        raise ValueError('来源对应的配方不存在')
    for source in value['sources'].values():
        validate_source(source, value['imports'])
    settings = value['settings']
    if (not isinstance(settings, dict) or len(settings) > 60 or
        any(not isinstance(k, str) or not isinstance(v, (str, bool)) or
            isinstance(v, str) and len(v) > 1024 for k, v in settings.items())):
        raise ValueError('训练选项无效')
    if not isinstance(value['jobs'], dict) or len(value['jobs']) > 96:
        raise ValueError('工程任务记录无效')
    for job, slot in value['jobs'].items():
        identifier(job)
        if type(slot) is not int or not 1 <= slot <= 24:
            raise ValueError('任务槽位无效')


def validate_source(source, imports):
    if source is None:
        return
    if not isinstance(source, dict) or len(encoded(source)) > 1024:
        raise ValueError('配方来源无效')
    if source.get('kind') == 'imported-bin':
        identifier(source.get('sha256'), 64)
        if source['sha256'] not in imports:
            raise ValueError('找不到工程内保存的原始 BIN')
        number = source.get('source_number')
        if type(number) is not int or not 1 <= number <= 24:
            raise ValueError('原始 BIN 槽号无效')


def restore(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != 'project.json' or infos[0].file_size > LIMIT:
                raise ValueError('备份应仅包含有效的 project.json')
            with archive.open(infos[0]) as stream:
                value = decoded(stream.read(LIMIT + 1))
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError('无法读取 .r5proj 备份') from error
    if not isinstance(value, dict) or set(value) != set(empty('工程')) or value['schema'] != SCHEMA:
        raise ValueError('备份工程格式无效')
    identifier(value['id'])
    name(value['name'])
    if not isinstance(value['imports'], dict):
        raise ValueError('备份来源无效')
    for digest, payload in value['imports'].items():
        identifier(digest, 64)
        if not isinstance(payload, str) or len(payload) > 4 * ((core.compiler.MAXIMUM + 2) // 3):
            raise ValueError('备份内 BIN 大小无效')
        binary = base64.b64decode(payload, validate=True)
        if core.sha(binary) != digest:
            raise ValueError('备份内原始 BIN 校验失败')
        core.compiler.unpack(binary)
    validate_state(value)
    for key, versions in slots(value['history']).items():
        if not isinstance(versions, list) or len(versions) > 6:
            raise ValueError('配方版本记录无效')
        for version in versions:
            if not isinstance(version, dict) or set(version) != {'entry', 'source', 'at'} or type(version['at']) is not int:
                raise ValueError('配方版本记录无效')
            entry = version['entry']
            draft_entry(entry, int(key))
            core.compiler.pack(core.compiler.config([entry]))
            validate_source(version['source'], value['imports'])
    if not isinstance(value['exports'], list) or len(value['exports']) > 20:
        raise ValueError('导出记录无效')
    for record in value['exports']:
        if (not isinstance(record, dict) or set(record) != {'at', 'sha256', 'format', 'slots'} or
                type(record['at']) is not int or record['format'] not in (4, 5) or
                not isinstance(record['slots'], list) or len(record['slots']) > 24 or
                any(type(i) is not int or not 1 <= i <= 24 for i in record['slots'])):
            raise ValueError('导出记录无效')
        identifier(record['sha256'], 64)
    value.update(id=uuid.uuid4().hex, revision=0, updated=0)
    return value


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for filename, data in files.items():
            archive.writestr(filename, data)
    return stream.getvalue()


class Store:
    # 所有变更由 HTTP 层的同一把锁串行化。
    def __init__(self, runs):
        self.root = runs / '_projects'
        self.runs = runs

    def list(self):
        items = []
        for path in self.root.glob('*.json'):
            if re.fullmatch('[0-9a-f]{32}', path.stem):
                value = self.get(path.stem)
                items.append({k: value[k] for k in ('id', 'name', 'updated')})
        return sorted(items, key=lambda item: item['updated'], reverse=True)

    def get(self, key):
        path = self.root / (identifier(key) + '.json')
        if not path.is_file():
            raise ValueError('工程不存在')
        with path.open('rb') as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('工程大小超过限制')
        return decoded(data)

    def write(self, value):
        value['revision'] += 1
        value['updated'] = time.time_ns() // 1_000_000
        data = encoded(value)
        if len(data) > LIMIT:
            raise ValueError('工程超过 8 MiB，无法保存')
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as stream:
            temporary = stream.name
            try:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                os.replace(temporary, self.root / (value['id'] + '.json'))
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return self.public(value)

    @staticmethod
    def public(value):
        return {key: item for key, item in value.items() if key != 'imports'}

    def update(self, body, action):
        value = self.get(body['id'])
        if type(body['revision']) is not int or body['revision'] != value['revision']:
            raise Conflict('工程已在另一页面更新。本页修改仍在内存，可复制参数 JSON 后重新打开工程。')
        if action == 'rename':
            value['name'] = name(body['name'])
        elif action == 'duplicate':
            value.update(id=uuid.uuid4().hex, name=name(body['name']), revision=0)
        elif action == 'save':
            before = {e['number']: e for e in value['entries']}
            sources = value['sources']
            for key in EDITABLE:
                value[key] = body[key]
            validate_state(value)
            after = {e['number']: e for e in value['entries']}
            for number, entry in before.items():
                key = str(number)
                if entry != after.get(number) or sources.get(key) != value['sources'].get(key):
                    versions = value['history'].setdefault(key, [])
                    versions.insert(0, dict(entry=entry, source=sources.get(key), at=value['updated']))
                    del versions[6:]
        elif action == 'merge':
            self.import_bin(value, body['sha256'], merge=True)
        return self.write(value)

    def import_asset(self, value, digest):
        path = self.runs / '_bin_imports' / (identifier(digest, 64) + '.bin')
        with path.open('rb') as stream:
            data = stream.read(core.compiler.MAXIMUM + 1)
        if core.sha(data) != digest:
            raise ValueError('导入来源摘要不一致')
        imported = core.compiler.unpack(data)
        value['imports'][digest] = base64.b64encode(data).decode('ascii')
        return imported

    def import_bin(self, value, digest, merge=False):
        imported = self.import_asset(value, digest)
        occupied = {e['number'] for e in value['entries']} | {int(k) for k in value['drafts']}
        if any(e['number'] in occupied for e in imported['entries']):
            raise Conflict('导入与已保存配方或草稿冲突，请导入为新工程')
        value['format'] = max(value['format'], core.compiler.format_version(imported))
        for entry in imported['entries']:
            value['entries'].append(entry)
            value['sources'][str(entry['number'])] = dict(kind='imported-bin', sha256=digest,
                                                        source_number=entry['number'])
        if not merge and imported['entries']:
            value['selected'] = imported['entries'][0]['number']

    def export_preview(self, value):
        saved = {entry['number']: entry for entry in value['entries']}
        drafts = {int(key): item['entry'] for key, item in value['drafts'].items()}
        references = {}
        for digest, data in value['imports'].items():
            entries = core.compiler.unpack(base64.b64decode(data))['entries']
            references[digest] = {entry['number']: entry for entry in entries}

        def summarize(entries):
            version = core.compiler.format_version(config({**value, 'entries': list(entries.values())}))
            differences = {}
            for digest, original in references.items():
                differences[digest] = dict(
                    added=sorted(entries.keys() - original.keys()),
                    removed=sorted(original.keys() - entries.keys()),
                    changed=sorted(n for n in original.keys() & entries.keys() if entries[n] != original[n]))
            return dict(format=version, slots=[dict(number=n, name=entries[n]['full_name']) for n in sorted(entries)],
                        differences=differences)

        with_drafts = {**saved, **drafts}
        presets, _ = core.presets()

        def endpoint_previews(convert, reference):
            result = {}
            for key, entries in (('saved', saved), ('with_drafts', with_drafts)):
                converted, limited = convert(entries, reference)
                result[key] = dict(summarize(converted), limited=limited)
            return result

        return dict(saved=summarize(saved), with_drafts=summarize(with_drafts),
                    draft_slots=sorted(drafts),
                    shared_st=endpoint_previews(shared_entries, presets[0]),
                    median_offset=endpoint_previews(median_entries, median_offsets(presets)))

    def export(self, value, allow_saved, allow_empty, mode=STANDARD):
        if mode not in (STANDARD, SHARED_ST, MEDIAN_OFFSET):
            raise ValueError('未知的端点导出方式')
        if value['drafts'] and not allow_saved:
            raise ValueError('工程含未保存草稿，请明确选择只导出已保存槽位')
        if not value['entries'] and not allow_empty:
            raise ValueError('导出空配置需确认清空机内自定义滤镜')
        recipe = config(value)
        endpoint_audit = None
        if mode != STANDARD:
            presets, _ = core.presets()
            entries = {entry['number']: entry for entry in recipe['entries']}
            if mode == SHARED_ST:
                converted, limited = shared_entries(entries, presets[0])
                endpoint_audit = dict(mode=mode, factory='ILCE-7RM5 ST', anchor='B', limited_slots=limited)
            else:
                offsets = median_offsets(presets)
                converted, limited = median_entries(entries, offsets)
                endpoint_audit = dict(mode=mode, factory='ILCE-7RM5', anchor='B', reference_looks=MEDIAN_LOOKS,
                                      method='coefficient-median-round-even-v1',
                                      offsets_sha256=core.sha(encoded(offsets)), limited_slots=limited)
            recipe['entries'] = list(converted.values())
        binary, compiler, firmware, version = core.compile_config(recipe)
        slots_used = sorted(e['number'] for e in recipe['entries'])
        record = dict(at=time.time_ns() // 1_000_000, sha256=core.sha(binary), format=version, slots=slots_used)
        audit = dict(schema='r5-colorlab-project-export/1', project_id=value['id'],
                     project_revision=value['revision'], binary_sha256=record['sha256'],
                     native_numbers=slots_used, format_version=version, firmware=firmware,
                     compiler_sha256=core.sha(compiler.read_bytes()), white_balance_in_binary=False,
                     color_accuracy_accepted=False, manual_parameters_allowed=True,
                     slot_origin_metadata=value['sources'], bytes=len(binary))
        if endpoint_audit is not None:
            audit['endpoint_export'] = endpoint_audit
        archive = zip_bytes({'R5NATIVE.BIN': binary, 'native_config.json': encoded(recipe),
                             'export_audit.json': encoded(audit)})
        value['exports'] = [record, *value['exports'][:19]]
        self.write(value)
        return archive, value
