"""本机原始镜像的分类索引；只创建.bin符号链接和清单，不移动或重写原件。"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .common import fresh, regular, safe, save, sha

GROUPS = {
    'standard-19/plaintext-17': '标准固件：明文分区',
    'standard-19/boot-2': '标准固件：启动区',
    'physical-extra-18/partitions-17': '扩展留证：物理分区视图',
    'physical-extra-18/whole-flash-1': '扩展留证：整个物理闪存',
}


def group(name):
    if re.fullmatch(r'cnflasha[0-9]+\.img', name):
        return 'standard-19/plaintext-17'
    if re.fullmatch(r'nflashaB[0-9]+\.img', name):
        return 'standard-19/boot-2'
    if re.fullmatch(r'pnflasha[0-9]+\.img', name):
        return 'physical-extra-18/partitions-17'
    if name == 'pnflasha.img':
        return 'physical-extra-18/whole-flash-1'
    raise ValueError('未知镜像类型，不自动归类：' + name)


def expectations(proof):
    value = json.loads(regular(proof).read_bytes())
    items = value['images']
    if len(items) != 37 or len({p['image'] for p in items}) != 37:
        raise ValueError('原始验收资料必须含37个唯一镜像')
    counts = {key: 0 for key in GROUPS}
    for item in items:
        counts[group(item['image'])] += 1
        if (type(item['bytes']) is not int or item['bytes'] <= 0
                or not re.fullmatch('[0-9a-f]{32}', item['md5'])
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('验收摘要或长度无效')
    if list(counts.values()) != [17, 2, 17, 1]:
        raise ValueError('镜像分类集合与标准19项加扩展18项不符')
    return items


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def verify_images(source, proof, destination):
    source = safe(source)
    if safe(destination).exists():
        raise FileExistsError('不覆盖既有校验记录')
    expected = expectations(proof)
    if {p.name for p in source.glob('*.img')} != {p['image'] for p in expected}:
        raise ValueError('本机.img集合与37项验收记录不符')
    rows = []
    for item in expected:
        path = regular(source / item['image'])
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size != item['bytes']:
                raise ValueError('原件类型或长度不符：' + item['image'])
            md5, digest = hashlib.md5(), hashlib.sha256()
            while block := os.read(fd, 8 << 20):
                md5.update(block)
                digest.update(block)
            if (identity(before) != identity(os.fstat(fd)) or md5.hexdigest() != item['md5']
                    or digest.hexdigest() != item['sha256']):
                raise ValueError('原件在读取时变化或摘要不符：' + item['image'])
            rows.append({**item, 'st_dev': before.st_dev, 'st_ino': before.st_ino,
                         'st_mtime_ns': before.st_mtime_ns})
        finally:
            os.close(fd)
    record = {'status': '37-original-images-currently-match-accepted-length-md5-sha256',
              'images_root': str(source), 'images': rows, 'image_count': 37,
              'total_bytes': sum(p['bytes'] for p in rows), 'original_files_modified': False,
              'camera_or_sd_accessed': False, 'proof_sha256': sha(proof)}
    save(destination, record)
    return record


def classify_verified(source, proof, checked_report, destination):
    """复用刚完成的摘要核验，并核对每个原件身份/长度/mtime未变，不重复扫描5.69GB。"""
    source = safe(source)
    expected = expectations(proof)
    checked = json.loads(regular(checked_report).read_bytes())
    if (checked.get('status') != '37-original-images-currently-match-accepted-length-md5-sha256'
            or checked.get('images_root') != str(source) or checked.get('image_count') != 37):
        raise ValueError('没有该目录的完整37项当前校验记录')
    actual = {item['image']: item for item in checked['images']}
    if len(actual) != 37 or set(actual) != {p['image'] for p in expected}:
        raise ValueError('当前校验记录集合不符')
    for item in expected:
        row = actual[item['image']]
        if any(row[key] != item[key] for key in ('bytes', 'md5', 'sha256')):
            raise ValueError('当前校验记录与原验收基线不符')
        info = regular(source / item['image']).stat()
        if identity(info) != (row['st_dev'], row['st_ino'], row['bytes'], row['st_mtime_ns']):
            raise ValueError('校验后原件发生变化：' + item['image'])
    output = fresh(destination)
    rows = []
    for item in expected:
        key = group(item['image'])
        folder = output / key
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        link = folder / (Path(item['image']).stem + '.bin')
        link.symlink_to(os.path.relpath(source / item['image'], folder))
        if link.resolve() != source / item['image']:
            raise ValueError('分类链接指向错误')
        rows.append({**item, 'group': key, 'link': str(link.relative_to(output)),
                     'source': str(source / item['image'])})
    totals = {key: {'label': label, 'count': sum(r['group'] == key for r in rows),
                   'bytes': sum(r['bytes'] for r in rows if r['group'] == key)} for key, label in GROUPS.items()}
    for name, selected in [('standard-19', [r for r in rows if r['group'].startswith('standard-19/')]),
                           ('physical-extra-18', [r for r in rows if r['group'].startswith('physical-extra-18/')])]:
        save(output / name / 'manifest.json', {'group': name, 'count': len(selected),
             'bytes': sum(r['bytes'] for r in selected), 'images': selected,
             'storage': 'symbolic-links-to-originals', 'originals_moved': False})
    result = {'status': 'classified-and-source-identity-unchanged',
        'images': rows, 'groups': totals, 'source': str(source), 'proof_sha256': sha(proof),
        'current_check_sha256': sha(checked_report), 'original_files_modified': False,
        'image_data_copied_bytes': 0, 'links': 37}
    (output / 'SHA256SUMS').write_text(''.join(r['sha256'] + '  ' + r['link'] + '\n' for r in rows))
    (output / 'index.tsv').write_text('group\timage\tbytes\tmd5\tsha256\tlink\tsource\n' + ''.join(
        '\t'.join(str(r[k]) for k in ('group', 'image', 'bytes', 'md5', 'sha256', 'link', 'source')) + '\n' for r in rows))
    summary = '\n'.join(f"| {item['label']} | {item['count']} | {item['bytes']:,} |" for item in totals.values())
    (output / 'README.md').write_text(f'''# A7R5 本机镜像分类

本目录是原件的分类浏览视图：只增加37个 `.bin` 符号链接和清单，没有移动、改名、删除或复制原始镜像数据。真正的数据仍在 `{source}`。

| 分类 | 数量 | 字节 |
|---|---:|---:|
{summary}

`standard-19/` 为通常固件研究使用的17个明文分区加2个启动区，与a7c2-re选择口径一致。
`physical-extra-18/` 为17个物理分区加1个整个物理闪存视图，用于扩展研究；不计入默认19项。

分类链接使用 `.bin` 后缀，避免按 `.img` 扩展名直接触发磁盘镜像打开。它们指向原件，不是独立工作副本：不要编辑这些链接、双击挂载或把它们可写挂载；需要修改分析时先制作自己的工作副本。

完整分类与摘要见 `classification.json`、`index.tsv` 和 `SHA256SUMS`。分类前已按原验收基线重算37项长度、MD5和SHA-256；创建链接前后继续核对源文件身份、长度和mtime不变。移动整套目录时应同时保留原件与相对链接的目录关系。
''')
    # 最后只看身份与元数据；不再次扫描镜像数据。
    for row in rows:
        current = actual[row['image']]
        if identity(regular(row['source']).stat()) != (current['st_dev'], current['st_ino'], current['bytes'], current['st_mtime_ns']):
            raise ValueError('分类过程中原件发生变化，停止')
    save(output / 'classification.json', result)
    return {'output': str(output), 'standard_count': 19, 'physical_extra_count': 18,
            'links': 37, 'image_data_copied_bytes': 0, 'original_files_modified': False}
