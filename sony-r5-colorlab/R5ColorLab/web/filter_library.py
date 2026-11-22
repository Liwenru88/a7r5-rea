"""Scan the repository filters/ catalog and pack custom 1-24 slot R5NATIVE.BIN bundles."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import core
import export_policy423

PREFERRED_CATEGORY_ORDER = [
    '富士数码',
    '理光',
    'Kodak',
    'Canon',
    'Classic BW',
    'Fuji Negative',
    'Fuji Positive',
    'Kodachrome',
    'Leica',
]

_CACHE: dict[tuple[str, int, int], dict] = {}


def filters_root() -> Path:
    override = os.environ.get('R5_FILTERS_DIR')
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2] / 'filters'


def _category_sort_key(name: str) -> tuple[int, str]:
    try:
        return (PREFERRED_CATEGORY_ORDER.index(name), name)
    except ValueError:
        return (len(PREFERRED_CATEGORY_ORDER), name.lower())


def _read_bin_entry(bin_path: Path) -> tuple[dict, str]:
    stat = bin_path.stat()
    cache_key = (str(bin_path), stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached['config'], cached['sha256']
    raw = bin_path.read_bytes()
    config = core.compiler.unpack(raw)
    if len(config.get('entries') or []) != 1:
        raise ValueError(f'{bin_path.name} 不是单款滤镜')
    digest = core.sha(raw)
    _CACHE[cache_key] = {'config': config, 'sha256': digest}
    return config, digest


def catalog(root: Path | None = None) -> dict:
    base = (root or filters_root()).resolve()
    if not base.is_dir():
        return {
            'filters_dir': str(base),
            'slot_limit': core.compiler.SLOT_LIMIT,
            'categories': [],
            'filters': [],
        }

    categories_dirs = sorted(
        [
            p for p in base.iterdir()
            if p.is_dir() and not p.name.startswith('.') and not p.name.startswith('FUJ_')
        ],
        key=lambda p: _category_sort_key(p.name),
    )

    items: list[dict] = []
    categories: list[dict] = []

    for cat_dir in categories_dirs:
        cat_items: list[dict] = []
        for bin_path in sorted(cat_dir.glob('*.bin'), key=lambda p: p.stem.lower()):
            stem = bin_path.stem
            json_path = cat_dir / f'{stem}.json'
            try:
                config, file_sha = _read_bin_entry(bin_path)
            except Exception:
                continue
            entry = config['entries'][0]
            meta = {}
            if json_path.is_file():
                try:
                    import json
                    meta = json.loads(json_path.read_text(encoding='utf-8'))
                except Exception:
                    meta = {}

            short_name = str(meta.get('short_name') or entry.get('short_name') or stem)
            full_name = str(meta.get('name') or entry.get('full_name') or short_name)
            order = meta.get('order')
            order_num = int(order) if isinstance(order, (int, float)) else 9999
            samples = []
            samples_dir = base / '_samples' / cat_dir.name
            for idx in (1, 2):
                sample_path = samples_dir / f'{stem}_{idx}.jpg'
                if sample_path.is_file():
                    from urllib.parse import quote
                    samples.append(f'/api/filter-samples/{quote(cat_dir.name)}/{quote(stem)}_{idx}.jpg')
            cat_items.append({
                'key': f'{cat_dir.name}/{stem}',
                'id': str(meta.get('id') or stem),
                'category': cat_dir.name,
                'stem': stem,
                'name': full_name,
                'short_name': short_name,
                'entry_short_name': entry.get('short_name', short_name),
                'entry_full_name': entry.get('full_name', full_name),
                'series': str(meta.get('series') or cat_dir.name),
                'description': str(meta.get('description') or ''),
                'updated': str(meta.get('updated') or ''),
                'sha256': str(meta.get('sha256') or file_sha),
                'file_sha256': file_sha,
                'camera_tested': bool(meta.get('camera_tested', False)),
                'order': order_num,
                'type': str(meta.get('type') or ''),
                'training_error': meta.get('training_error'),
                'format_version': core.compiler.format_version(config),
                'samples': samples,
            })

        cat_items.sort(key=lambda x: (x['order'], x['short_name'].lower(), x['name'].lower()))
        if cat_items:
            categories.append({'name': cat_dir.name, 'count': len(cat_items)})
            items.extend(cat_items)

    base_samples = []
    for idx in (1, 2):
        if (base / '_samples' / f'_base_{idx}.jpg').is_file():
            base_samples.append(f'/api/filter-samples/_base_{idx}.jpg')

    return {
        'filters_dir': str(base),
        'slot_limit': core.compiler.SLOT_LIMIT,
        'base_samples': base_samples,
        'categories': categories,
        'filters': items,
    }


def _resolve_entries(items: list, root: Path | None = None) -> tuple[list[dict], list[dict], dict]:
    if not isinstance(items, list) or not (1 <= len(items) <= core.compiler.SLOT_LIMIT):
        raise ValueError(f'请选择 1～{core.compiler.SLOT_LIMIT} 款滤镜')

    base = (root or filters_root()).resolve()
    cat = catalog(base)
    by_key = {item['key']: item for item in cat['filters']}

    entries: list[dict] = []
    sources_meta: list[dict] = []
    template_cfg = None

    for idx, req in enumerate(items, start=1):
        if isinstance(req, str):
            key = req
            short_override = None
            full_override = None
        elif isinstance(req, dict):
            key = req.get('key', '')
            short_override = req.get('short_name')
            full_override = req.get('full_name')
        else:
            raise ValueError('滤镜选择项格式无效')

        meta = by_key.get(key)
        if meta is None:
            raise ValueError(f'未找到滤镜：{key}')

        bin_path = (base / f'{key}.bin').resolve()
        if not bin_path.is_relative_to(base) or not bin_path.is_file():
            raise ValueError(f'滤镜文件不存在：{key}')

        cfg, file_sha = _read_bin_entry(bin_path)
        if template_cfg is None:
            template_cfg = cfg
        entry = copy.deepcopy(cfg['entries'][0])
        entry['number'] = idx
        if isinstance(short_override, str) and short_override.strip():
            entry['short_name'] = short_override.strip()
        if isinstance(full_override, str) and full_override.strip():
            entry['full_name'] = full_override.strip()
        entries.append(entry)
        sources_meta.append({
            'number': idx,
            'key': key,
            'id': meta['id'],
            'category': meta['category'],
            'short_name': entry['short_name'],
            'full_name': entry['full_name'],
            'source_bin_sha256': file_sha,
        })

    config = core.config(entries)
    if template_cfg:
        for k in ('model', 'baseline_ap_sha256', 'baseline_cp_sha256'):
            if template_cfg.get(k):
                config[k] = template_cfg[k]
    return entries, sources_meta, config


def pack_bundle(items: list, root: Path | None = None) -> tuple[bytes, dict, dict]:
    entries, sources_meta, config = _resolve_entries(items, root=root)
    payload, compiler_path, firmware, version = core.compile_config(config)
    audit = {
        'schema': 'r5-filter-library-export/1',
        'binary_sha256': core.sha(payload),
        'bytes': len(payload),
        'count': len(entries),
        'slot_limit': core.compiler.SLOT_LIMIT,
        'native_numbers': [e['number'] for e in entries],
        'firmware': firmware,
        'format_version': version,
        'sources': sources_meta,
        'compiler_sha256': core.sha(compiler_path.read_bytes()),
    }
    return payload, config, audit


def import_bundle_to_project(items: list, runs: Path, root: Path | None = None) -> dict:
    payload, _, _ = pack_bundle(items, root=root)
    return export_policy423.import_binary(payload, runs)


def sample_file(rel_path: str, root: Path | None = None) -> Path:
    samples_root = ((root or filters_root()).resolve() / '_samples').resolve()
    target = (samples_root / rel_path.lstrip('/')).resolve()
    if not target.is_relative_to(samples_root) or target.suffix.lower() != '.jpg' or not target.is_file():
        raise ValueError('样片不存在')
    return target
