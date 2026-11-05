"""导出原厂网格、绑定的压缩结果或经严格解码的导入BIN。

v4／v5均严格验证配方，网格来源属于网页工程字段，打包前单独校验。
"""
import copy
import re
from pathlib import Path
import core

PARAMETERS = ('cc1_delta', 'block13', 'gamma_native_129', 'grid_5x9x9')


def import_binary(data, runs):
    """先完整校验，再按摘要保留原始BIN；不覆盖已有来源文件。"""
    value = core.compiler.unpack(data)
    digest = core.sha(data)
    folder = Path(runs) / '_bin_imports'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest + '.bin')
    try:
        with target.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        if target.stat().st_size != len(data) or target.read_bytes() != data:
            raise ValueError('已保存的BIN来源损坏，请保留原始文件并检查导入缓存')
    value['export_sources'] = {str(e['number']): dict(kind='imported-bin', sha256=digest,
                              source_number=e['number']) for e in value['entries']}
    return dict(project=value, audit=dict(binary_sha256=digest, bytes=len(data),
                format_version=core.compiler.format_version(value),
                slots=[e['number'] for e in value['entries']], color_accuracy_accepted=False))


def imported_entries(source, runs, cache):
    digest = source.get('sha256')
    number = source.get('source_number')
    if (set(source) != {'kind', 'sha256', 'source_number'} or
            type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest) or
            type(number) is not int or not 1 <= number <= core.compiler.SLOT_LIMIT):
        raise ValueError('导入BIN来源标识无效')
    if digest not in cache:
        path = Path(runs) / '_bin_imports' / (digest + '.bin')
        if not path.is_file():
            raise ValueError('找不到原始BIN来源，请重新导入同一R5NATIVE.BIN')
        if not core.compiler.HEADER <= path.stat().st_size <= core.compiler.MAXIMUM:
            raise ValueError('原始BIN来源大小不符')
        data = path.read_bytes()
        if core.sha(data) != digest:
            raise ValueError('原始BIN来源摘要不符')
        cache[digest] = {e['number']: e for e in core.compiler.unpack(data)['entries']}
    expected = cache[digest].get(number)
    if expected is None:
        raise ValueError('原始BIN中不存在此来源槽位')
    return expected


def configuration(project):
    if type(project) is not dict:
        raise ValueError('请选择 v4／v5 自定义滤镜配置')
    value = copy.deepcopy(project)
    value.pop('export_sources', None)
    core.compiler.pack(value)  # Reject all old schemas, flags and fields.
    return value


def validate(project, runs):
    value = configuration(project)
    sources = project.get('export_sources', {})
    if type(sources) is not dict or set(sources) != {str(e['number']) for e in value['entries']}:
        raise ValueError('每项配置必须选择原厂网格、绑定压缩结果或已校验的导入BIN')
    from stock_grids import catalog
    stock = {e['id']: e for e in catalog()}
    receipts, imported = [], {}
    for entry in value['entries']:
        source = sources[str(entry['number'])]
        if type(source) is not dict:
            raise ValueError('网格来源无效')
        if source.get('kind') == 'stock' and set(source) == {'kind', 'id'}:
            preset = stock.get(source['id'])
            if preset is None or entry['grid_5x9x9'] != preset['grid_5x9x9']:
                raise ValueError('原厂网格已修改或来源失效，请重新选择')
            receipts.append(dict(number=entry['number'], **source, provenance=preset['provenance']))
        elif source.get('kind') == 'compressed' and set(source) == {'kind', 'job', 'key'}:
            if not isinstance(source['job'], str) or not re.fullmatch('[0-9a-f]{32}', source['job']):
                raise ValueError('压缩任务编号无效')
            from grid_distillation import firmware_config, load_result
            job = Path(runs) / source['job']
            expected = firmware_config(job, source['key'], configuration_only=True)['entries'][0]
            if any(entry[k] != expected[k] for k in PARAMETERS):
                raise ValueError('参数与压缩结果不一致，请重新压缩或选择原厂网格')
            report, _, digest = load_result(job, source['key'])
            receipts.append(dict(number=entry['number'], **source, compression_report_sha256=digest,
                                 identity=report['identity']))
        elif source.get('kind') == 'imported-bin':
            expected = imported_entries(source, runs, imported)
            if any(entry[k] != expected[k] for k in PARAMETERS):
                raise ValueError('色彩参数与导入BIN不一致，请恢复原参数、重新压缩或选择原厂网格')
            receipts.append(dict(number=entry['number'], **source,
                                 verification='binary-format-and-unchanged-color-parameters'))
        else:
            raise ValueError('只允许原厂网格、已完成的压缩结果或已校验的导入BIN')
    return value, receipts
