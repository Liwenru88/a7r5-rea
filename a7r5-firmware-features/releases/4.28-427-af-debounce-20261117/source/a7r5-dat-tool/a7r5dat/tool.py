"""离线解包、局部组件替换和签名打包；不含相机或磁盘设备接口。"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import zlib

from Cryptodome.Hash import SHA256
from Cryptodome.PublicKey import RSA
from Cryptodome.Signature import pkcs1_15

from .codec import (CHUNK, Part, decoded_chunks, decrypt_to, digest, header_info,
                    inspect_dat, regular, require, sha, verify_signature)
from .encryptor import FdatStreamEncrypter
from .ext2_patch import Patch, reader
from .fat import FatImage

HOME = Path(__file__).resolve().parent.parent
AP_IMAGE = '0700_part_image/dev/nflasha15'
CP_IMAGE = '0700_part_image/dev/nflasha8'
HEADER_MAGIC = b'\x89UFU\r\n\x1a\n'


def encode(raw):
    return base64.b64encode(raw).decode('ascii')


def decode(text):
    return base64.b64decode(text, validate=True)


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
    Path(path).chmod(0o600)


def safe_name(name):
    require(isinstance(name, str) and name and not any(c in name for c in ('\\', ':', '\x00')),
            '归档路径含不支持字符')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(v not in ('', '.', '..') for v in name.split('/')),
            '归档路径越界或非规范：'+name)
    return p


def inside(root, name):
    safe_name(name)
    root = Path(root)
    require(not root.is_symlink(), '拒绝符号链接目录')
    path = root
    for part in PurePosixPath(name).parts:
        path = path/part
        require(not path.is_symlink(), '拒绝工作目录中的符号链接：'+name)
    require(not path.resolve().is_relative_to('/dev'), '拒绝设备路径')
    return path


def file_facts(path):
    path = regular(path)
    h, crc = hashlib.sha256(), 0
    with path.open('rb') as f:
        while raw := f.read(CHUNK):
            h.update(raw)
            crc = zlib.crc32(raw, crc)
    return dict(bytes=path.stat().st_size, sha256=h.hexdigest(), crc32=f'{crc:08x}')


def verify_key(dat, public=None):
    choices = [Path(public)] if public else [HOME/'keys/research-public.pem', HOME/'keys/sony-original-public.pem']
    for path in choices:
        raw = regular(path).read_bytes()
        try:
            layout, _, _ = verify_signature(dat, raw)
            return layout, dict(public_key_sha256=sha(raw), signature_verified=True)
        except (ValueError, TypeError):
            continue
    raise ValueError('DAT签名不能由指定或附带公钥验证；没有跳过验签选项')


def signing_key(private, public):
    path = regular(private)
    if os.name != 'nt':
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, '私钥权限必须为0600：'+str(path))
    key = RSA.import_key(path.read_bytes())
    other = RSA.import_key(regular(public).read_bytes())
    require(key.has_private() and key.size_in_bits() == 2048, '需要RSA-2048研究签名私钥')
    require(key.public_key().export_key() == other.public_key().export_key(), '签名私钥与验签公钥不配对')
    return key


def read_archive(clear, total, destination=None):
    clear.seek(0)
    header = clear.read(512)
    info = header_info(header, total)
    require(info['tar_bytes'] < 2 << 30, '拒绝超出本工具范围的归档')
    clear.seek(info['updater_offset'])
    updater = clear.read(info['updater_bytes'])
    archive = tarfile.open(fileobj=Part(clear, info['tar_offset'], info['tar_bytes']), mode='r:')
    members = archive.getmembers()
    require(0 < len(members) < 1000, '归档条目数异常')
    entries, cursor, seen = [], 0, set()
    for m in members:
        safe_name(m.name)
        require(m.name not in seen and not m.pax_headers, '重复路径或不支持的扩展头')
        require(m.isfile() or m.isdir() or m.issym(), '拒绝硬链接或设备归档条目')
        require(m.size == 0 or m.isfile(), '非普通文件含载荷')
        require(cursor <= m.offset_data <= cursor+65536 and m.offset_data+m.size <= info['tar_bytes'],
                '归档布局越界')
        seen.add(m.name)
        clear.seek(info['tar_offset']+cursor)
        prefix = clear.read(m.offset_data-cursor)
        row = dict(name=m.name, type=m.type.decode('ascii'), size=m.size,
                   prefix=encode(prefix), link=m.linkname)
        if m.issym():
            # 原厂的 ../proc/mounts 只保存在元数据内，不在主机创建链接。
            require(m.name == '0800_appli/tmp/mtab' and m.linkname == '../proc/mounts',
                    '拒绝未识别的归档链接')
        if m.isfile():
            stream = archive.extractfile(m)
            h, crc, count = hashlib.sha256(), 0, 0
            path = inside(destination, m.name) if destination else None
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
            output = path.open('xb') if path else None
            try:
                while raw := stream.read(CHUNK):
                    h.update(raw); crc = zlib.crc32(raw, crc); count += len(raw)
                    if output:
                        output.write(raw)
            finally:
                if output:
                    output.close()
            require(count == m.size, '归档载荷短读')
            row.update(sha256=h.hexdigest(), crc32=f'{crc:08x}')
        elif m.isdir() and destination:
            inside(destination, m.name).mkdir(parents=True, exist_ok=True)
        entries.append(row)
        cursor = m.offset_data+m.size
    require(info['tar_bytes']-cursor <= 1 << 20, '归档尾部过大')
    clear.seek(info['tar_offset']+cursor)
    tail = clear.read(info['tar_bytes']-cursor)
    archive.close()
    return header, updater, info, entries, tail


def sum_target(name, relative):
    match = re.fullmatch(r'(\d{4})_(.+)_sum/[^/]+\.sum', name)
    require(match is not None, '不支持的校验清单路径：'+name)
    safe_name(relative)
    return f'{int(match[1])-1:04d}_{match[2]}/'+relative


def checksum_updates(name, raw, originals, current):
    lines = []
    for line in raw.decode('ascii').splitlines(keepends=True):
        body, newline = (line[:-1], '\n') if line.endswith('\n') else (line, '')
        fields = body.split(',')
        if fields[0] == '0':
            require(len(fields) >= 11, '校验清单记录不完整')
            target = sum_target(name, fields[10])
            require(target in originals and target in current, '校验清单目标缺失：'+target)
            old, new = originals[target], current[target]
            require(fields[1].lower() == old['crc32'] and int(fields[2], 16) == old['size'],
                    '原校验记录与工作目录基线不符：'+target)
            require(new['bytes'] == old['size'], '仅支持归档成员定长替换')
            fields[1] = new['crc32']
            body = ','.join(fields)
        lines.append(body+newline)
    return ''.join(lines).encode('ascii')


def extract_components(work, entries):
    found = {}
    usr = inside(work/'archive', AP_IMAGE).read_bytes()
    fs = reader(usr)

    def walk(ino, prefix=''):
        for child, name, _ in fs.dir_entries(ino):
            if name in ('.', '..'):
                continue
            path = prefix+'/'+name
            mode, _, _ = fs.inode(child)
            if stat.S_ISDIR(mode):
                walk(child, path)
            elif stat.S_ISREG(mode) and (path == '/lib/appFw.so' or
                    re.fullmatch(r'/share/app/string_[a-z]+_(horizontal|vertical)\.uxc', path)):
                raw = fs.read_inode(child)
                relative = 'usr'+path
                output = inside(work/'components', relative)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(raw)
                found[relative] = dict(image=AP_IMAGE, path=path, bytes=len(raw), sha256=sha(raw))
    walk(2)
    cp = FatImage(inside(work/'archive', CP_IMAGE).read_bytes()).read('/cpapp-b.bin')
    (work/'components/cpapp-b.bin').write_bytes(cp)
    found['cpapp-b.bin'] = dict(image=CP_IMAGE, path='/cpapp-b.bin', bytes=len(cp), sha256=sha(cp))
    require('usr/lib/appFw.so' in found and len(found) == 70, '未定位预期AP、CP和68份资源')
    return found


def inspect(dat, public=None, full=False):
    dat = regular(dat)
    layout, signature = verify_key(dat, public)
    h = digest(dat)
    with tempfile.TemporaryFile() as clear:
        if full:
            facts = decrypt_to(dat, clear)
            header, _, info, entries, _ = read_archive(clear, facts['plaintext_bytes'])
            count = len(entries)
        else:
            first = next(decoded_chunks(dat, layout))
            offset, size = struct.unpack_from('<II', first, 48)
            info = header_info(first[:512], offset+size)
            facts, count = {}, None
    require(digest(dat) == h, '核对期间输入DAT发生变化')
    return dict(status='verified' if full else 'inspected', sha256=h, bytes=layout['size'],
                version=f"{info['major']:x}.{info['minor']:02x}", header=info,
                full_frame_validation=full, tar_entries=count, **facts, **signature,
                camera_io=False, device_acceptance_verified=False)


def unpack(dat, work, public=None):
    dat, work = regular(dat), Path(work).absolute()
    require(not work.exists() and not work.is_symlink(), '输出工作目录已存在，拒绝覆盖')
    layout, signature = verify_key(dat, public)
    source = file_facts(dat)
    require(shutil.disk_usage(work.parent).free > 2 << 30, '解包至少需要2GiB可用空间')
    work.mkdir(mode=0o700)
    save(work/'INCOMPLETE.json', dict(state='解包未完成，不能打包'))
    for folder in ['archive', 'format', 'components']:
        (work/folder).mkdir(mode=0o700)
    with tempfile.TemporaryFile(dir=work) as clear:
        decrypted = decrypt_to(dat, clear)
        header, updater, info, entries, tail = read_archive(clear, decrypted['plaintext_bytes'], work/'archive')
    (work/'format/header.bin').write_bytes(header)
    (work/'format/updater.bin').write_bytes(updater)
    outer = []
    with dat.open('rb') as f:
        for c in layout['chunks']:
            if c['kind'] not in ['FDAT', 'DEND']:
                f.seek(c['offset'])
                outer.append(dict(kind=c['kind'], data=encode(f.read(c['size']))))
        f.seek(layout['signature_offset']-16)
        iv = f.read(16)
    components = extract_components(work, entries)
    manifest = dict(schema=1, source=source, header=info, header_sha256=sha(header),
                    updater_sha256=sha(updater), outer=outer, iv=encode(iv),
                    tail=encode(tail), entries=entries, components=components,
                    decryption=decrypted, **signature)
    originals = {r['name']:r for r in entries if r['type'] in ['0', '\x00']}
    current = {n:dict(bytes=r['size'], crc32=r['crc32']) for n,r in originals.items()}
    for n in originals:
        if n.endswith('.sum'):
            raw = inside(work/'archive', n).read_bytes()
            require(checksum_updates(n, raw, originals, current) == raw, '原包清单不一致：'+n)
    require(file_facts(dat) == source, '解包期间输入DAT变化')
    save(work/'manifest.json', manifest)
    (work/'INCOMPLETE.json').unlink()
    return dict(status='unpacked', workspace=str(work), source=source, components=len(components),
                entries=len(entries), symbolic_links_created=False, camera_io=False)


def collect(work, manifest, temporary):
    entries = manifest['entries']
    originals = {r['name']:r for r in entries if r['type'] in ['0', '\x00']}
    require(len({r['name'] for r in entries}) == len(entries), '工作目录清单路径重复')
    expected = set(originals)
    actual = {str(p.relative_to(work/'archive')) for p in (work/'archive').rglob('*') if not p.is_dir()}
    require(expected == actual, '归档文件新增、删除或出现符号链接；仅支持现有成员定长替换')
    files = {n:inside(work/'archive', n) for n in originals}
    current = {n:file_facts(p) for n,p in files.items()}
    require(all(current[n]['bytes'] == r['size'] for n,r in originals.items()), '归档成员长度变化')
    components = manifest['components']
    actual = {str(p.relative_to(work/'components')) for p in (work/'components').rglob('*') if not p.is_dir()}
    require(set(components) == actual, '组件路径新增或缺失，拒绝静默忽略')
    groups = {}
    for n,row in components.items():
        raw = regular(inside(work/'components', n)).read_bytes()
        if sha(raw) != row['sha256']:
            groups.setdefault(row['image'], []).append((row['path'], raw))
    changed_components = []
    for image, changes in groups.items():
        require(image in [AP_IMAGE, CP_IMAGE], '未知组件分区')
        require(current[image]['sha256'] == originals[image]['sha256'], '原始分区与内部组件同时修改，拒绝覆盖冲突')
        raw = files[image].read_bytes()
        if image == CP_IMAGE:
            require(len(changes) == 1 and changes[0][0] == '/cpapp-b.bin', '未知CP组件')
            fs = FatImage(raw)
            target = bytearray(raw)
            fs.patch(target, changes[0][0], changes[0][1])
            result = bytes(target)
            require(FatImage(result).read('/cpapp-b.bin') == changes[0][1], 'CP回读失败')
        else:
            patch = Patch(raw)
            for path, data in changes:
                require(path == '/lib/appFw.so' or re.fullmatch(r'/share/app/string_[a-z]+_(horizontal|vertical)\.uxc', path),
                        '未知USR组件路径')
                if path == '/lib/appFw.so':
                    require(len(data) == components['usr'+path]['bytes'], 'AP必须定长')
                before = patch.fs.read_inode(patch.fs.walk(path))
                patch.replace(path, before, data)
            result, _ = patch.finish()
            independent = reader(result)
            for path,data in changes:
                require(independent.read_inode(independent.walk(path)) == data, 'USR组件回读失败')
        target = temporary/(Path(image).name+'.img')
        target.write_bytes(result)
        files[image], current[image] = target, file_facts(target)
        changed_components.extend(path for path,_ in changes)
    for n in originals:
        if n.endswith('.sum'):
            require(current[n]['sha256'] == originals[n]['sha256'], '校验清单由工具管理，请勿手动修改：'+n)
            raw = checksum_updates(n, files[n].read_bytes(), originals, current)
            if sha(raw) != originals[n]['sha256']:
                target = temporary/(n.replace('/', '_'))
                target.write_bytes(raw)
                files[n], current[n] = target, file_facts(target)
    return files, current, changed_components


def workspace_snapshot(work):
    result = {}
    for p in work.rglob('*'):
        require(not p.is_symlink(), '拒绝工作目录中的符号链接')
        require(p.is_dir() or p.is_file(), '拒绝工作目录中的特殊文件')
        if p.is_file():
            result[str(p.relative_to(work))] = file_facts(p)
    return result


class SignedOutput:
    def __init__(self, stream):
        self.stream, self.crc, self.hashed = stream, 0, SHA256.new()

    def write(self, raw, signed=False):
        require(self.stream.write(raw) == len(raw), '输出短写')
        self.crc = zlib.crc32(raw, self.crc)
        if signed:
            self.hashed.update(raw)
        return len(raw)


class SigningView:
    def __init__(self, output):
        self.output = output

    def write(self, raw):
        return self.output.write(raw, signed=True)


def encrypt(clear, size, manifest, key, target):
    iv = decode(manifest['iv'])
    blocks = (size+1019)//1020
    with target.open('xb') as f:
        output = SignedOutput(f)
        output.write(HEADER_MAGIC)
        require([r['kind'] for r in manifest['outer']] == ['DATV', 'PROV', 'UDID'], '外层块集合不符')
        for row in manifest['outer']:
            raw = decode(row['data'])
            output.write(struct.pack('>I4s', len(raw), row['kind'].encode())+raw)
        output.write(struct.pack('>I4s', blocks*1024+272, b'FDAT'))
        clear.seek(0)
        FdatStreamEncrypter(iv).encrypt_stream(clear, SigningView(output), size)
        output.write(iv, signed=True)
        output.write(pkcs1_15.new(key).sign(output.hashed))
        crc = output.crc
        output.write(struct.pack('>I4sI', 4, b'DEND', crc))
        f.flush()
        os.fsync(f.fileno())


def pack(work, output, version=None, private=None, public=None):
    work, output = Path(work).absolute(), Path(output).absolute()
    require(not work.is_symlink() and work.is_dir() and not (work/'INCOMPLETE.json').exists(), '工作目录不完整')
    require(not output.exists() and not output.is_symlink() and not output.with_suffix(output.suffix+'.json').exists(),
            '输出DAT或回执已存在，拒绝覆盖')
    require(not output.parent.resolve().is_relative_to('/dev'), '拒绝设备输出')
    require(shutil.disk_usage(output.parent).free > 3 << 30, '打包至少需要3GiB可用空间')
    key = signing_key(private or HOME/'keys/research-signing-private.pem', public or HOME/'keys/research-public.pem')
    manifest_path = regular(inside(work, 'manifest.json'))
    manifest = json.loads(manifest_path.read_text())
    require(manifest['schema'] == 1, '工作目录版本不支持')
    header = regular(inside(work, 'format/header.bin')).read_bytes()
    updater = regular(inside(work, 'format/updater.bin')).read_bytes()
    require(sha(header) == manifest['header_sha256'] and sha(updater) == manifest['updater_sha256'],
            '格式头或更新器变化；版本请使用--version设置')
    total = manifest['decryption']['plaintext_bytes']
    info = header_info(header, total)
    original_manifest_sha = digest(manifest_path)
    input_snapshot = workspace_snapshot(work)
    with tempfile.TemporaryDirectory(prefix='a7r5-dat-', dir=output.parent) as folder:
        temporary = Path(folder)
        files, current, changed_components = collect(work, manifest, temporary)
        input_facts = {n:file_facts(p) for n,p in files.items()}
        raw_header = bytearray(header)
        if version is not None:
            require(re.fullmatch(r'\d{1,2}\.\d{2}', version), '版本格式必须为4.05等两位小数')
            major, minor = version.split('.')
            raw_header[33], raw_header[32] = int(major, 16), int(minor, 16)
            struct.pack_into('<I', raw_header, 8, zlib.crc32(raw_header[12:]))
        header_info(bytes(raw_header), total)
        with tempfile.TemporaryFile(dir=temporary) as clear:
            clear.write(raw_header)
            clear.write(updater)
            for row in manifest['entries']:
                safe_name(row['name'])
                clear.write(decode(row['prefix']))
                if row['name'] in files:
                    with files[row['name']].open('rb') as f:
                        shutil.copyfileobj(f, clear, CHUNK)
            clear.write(decode(manifest['tail']))
            require(clear.tell() == total, '重建明文长度不符')
            clear.seek(0)
            _, _, _, rebuilt_entries, _ = read_archive(clear, total)
            require([r['name'] for r in rebuilt_entries] == [r['name'] for r in manifest['entries']], '重建归档路径不符')
            for row in rebuilt_entries:
                if row['name'] in current:
                    require(row['sha256'] == current[row['name']]['sha256'], '重建归档内容不符')
            partial = temporary/'UNVERIFIED.partial'
            encrypt(clear, total, manifest, key, partial)
            layout, _, _ = verify_signature(partial, key.public_key().export_key())
            clear.seek(0)
            h, count = hashlib.sha256(), 0
            for raw in decoded_chunks(partial, layout):
                require(raw == clear.read(len(raw)), '打包后独立解密回读不符')
                h.update(raw); count += len(raw)
            require(count == total and clear.read(1) == b'', '最终明文长度不符')
        require(input_facts == {n:file_facts(p) for n,p in files.items()} and digest(manifest_path) == original_manifest_sha
                and workspace_snapshot(work) == input_snapshot,
                '打包期间输入发生变化')
        facts = file_facts(partial)
        receipt = dict(status='OFFLINE_PACK_VERIFIED_DEVICE_UNTESTED', **facts,
                       source=manifest['source'], changed_archive_members=[n for n in current
                           if current[n]['sha256'] != next(r['sha256'] for r in manifest['entries'] if r['name']==n)],
                       changed_components=changed_components, plaintext_sha256=h.hexdigest(), plaintext_bytes=count,
                       public_key_sha256=sha(key.public_key().export_key()+b'\n'),
                       signature_verified=True, independent_decryption_exact=True,
                       camera_io=False, device_acceptance_verified=False)
        # 硬链接发布保证不会覆盖同名文件；验证通过前不发布最终DAT。
        os.link(partial, output)
        output.chmod(0o600)
        save(output.with_suffix(output.suffix+'.json'), receipt)
    return receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='A7R5本地DAT解包／研究签名打包工具；无实机接口')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['inspect', 'verify', 'unpack']:
        p = sub.add_parser(name)
        p.add_argument('dat', type=Path)
        p.add_argument('--public-key', type=Path)
        if name == 'unpack':
            p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('pack')
    p.add_argument('workspace', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--version')
    p.add_argument('--private-key', type=Path)
    p.add_argument('--public-key', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'unpack':
            result = unpack(args.dat, args.output, args.public_key)
        elif args.command == 'pack':
            result = pack(args.workspace, args.output, args.version, args.private_key, args.public_key)
        else:
            result = inspect(args.dat, args.public_key, full=args.command=='verify')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, tarfile.TarError) as error:
        print('已停止：'+str(error), file=sys.stderr)
        return 1
    return 0
