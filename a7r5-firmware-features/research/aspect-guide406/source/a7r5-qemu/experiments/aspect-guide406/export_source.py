"""从已验签、仅驻内存的研究包生成独立 QEMU 文件归档，不输出分区镜像。"""
import hashlib
import json
from pathlib import PurePosixPath
import stat
import struct

DAT_SHA = '3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2'
AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'


def export(archive, rootfs, usrfs, system, cp, destination):
    destination.mkdir(parents=True, exist_ok=False)
    records = {}
    inode_number = 0

    def emit(stream, name, mode, data=b'', *, rmajor=0, rminor=0):
        nonlocal inode_number
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or name in records:
            raise ValueError('重复或越界的客体路径：' + name)
        inode_number += 1
        encoded = name.encode('utf-8') + b'\0'
        fields = [inode_number, mode, 0, 0, 1, 0, len(data), 0, 0,
                  rmajor, rminor, len(encoded), 0]
        header = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields)
        stream.write(header + encoded + bytes((-110-len(encoded)) % 4))
        stream.write(data + bytes((-len(data)) % 4))
        records[name] = {'mode': mode, 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest()}

    def inode_data(fs, inode):
        mode, length, _ = fs.inode(inode)
        group, index = divmod(inode-1, fs.inodes_per_group)
        offset = fs.inode_table(group)*fs.block_size + index*fs.inode_size
        sectors = struct.unpack_from('<I', fs.mm, offset+28)[0]
        if stat.S_ISLNK(mode) and length <= 60 and sectors == 0:
            return bytes(fs.mm[offset+40:offset+40+length])
        data = fs.read_inode(inode)
        if len(data) != length:
            raise ValueError('inode 数据短读')
        return data

    def walk(stream, fs, inode, prefix, seen):
        if inode in seen or len(records) > 20000:
            raise ValueError('文件系统目录循环或条目超限')
        seen = seen | {inode}
        for child, name, _ in fs.dir_entries(inode):
            if name in ('.', '..'):
                continue
            path = prefix + '/' + name if prefix else name
            mode, _, _ = fs.inode(child)
            if stat.S_ISDIR(mode):
                emit(stream, path, mode)
                # mount.conf 将 nflasha15 挂到 /usr，根文件系统下层内容本来不可见。
                if not (fs is rootfs and path == 'usr'):
                    walk(stream, fs, child, path, seen)
            elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                emit(stream, path, mode, inode_data(fs, child))
            elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
                group, index = divmod(child-1, fs.inodes_per_group)
                offset = fs.inode_table(group)*fs.block_size + index*fs.inode_size
                device = struct.unpack_from('<I', fs.mm, offset+40)[0]
                if device > 65535:
                    raise ValueError('未支持的设备节点编码')
                emit(stream, path, mode, rmajor=device >> 8, rminor=device & 255)
            else:
                raise ValueError('未支持的 inode 类型：' + path)

    output = destination/'source.cpio'
    with output.open('xb') as stream:
        walk(stream, rootfs, 2, '', set())
        walk(stream, usrfs, 2, 'usr', set())
        for prefix, image in (('system', system), ('cp', cp)):
            for entry in image.entries.values():
                name = prefix + entry['path']
                if entry['is_directory']:
                    if name not in records:
                        emit(stream, name, 0o40755)
                else:
                    emit(stream, name, 0o100644, image.read(entry['path']))
        emit(stream, 'seed-setting', 0o40755)
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name.startswith('0800_appli/setting/'):
                name = 'seed-setting/' + member.name.removeprefix('0800_appli/setting/')
            elif member.name.startswith('0800_appli/tmp/'):
                name = member.name.removeprefix('0800_appli/')
            else:
                continue
            for parent in reversed(PurePosixPath(name).parents):
                if str(parent) != '.' and str(parent) not in records:
                    emit(stream, str(parent), 0o40755)
            emit(stream, name, stat.S_IFREG | member.mode,
                 archive.extractfile(member).read())
        backup = archive.extractfile('0110_backup/SYSIPSX-DSLR/GL/CX89200_ALLLANG.bin').read()
        emit(stream, 'seed-backup.bin', 0o100600, backup)
        emit(stream, 'simulation', 0o40755)
        if 'dev/console' not in records:
            emit(stream, 'dev/console', 0o20600, rmajor=5, rminor=1)
        init = (b'#!/bin/sh\nexport PATH=/bin:/sbin:/usr/bin:/usr/sbin\n'
                b'mount -t proc proc /proc\nmount -t sysfs sysfs /sys\n'
                b'mount -t devtmpfs devtmpfs /dev\n'
                b'echo A7R5_QEMU_ROOT_READY\nexec /bin/sh\n')
        emit(stream, 'init', 0o100755, init)
        emit(stream, 'TRAILER!!!', 0)
        stream.write(bytes((-stream.tell()) % 512))
    if records['usr/lib/appFw.so']['sha256'] != AP_SHA:
        raise ValueError('当前 AP 身份不符')
    kernel = system.read('/vmlinux.bin')
    with (destination/'vmlinux.bin').open('xb') as stream:
        stream.write(kernel)
    report = {'schema': 'a7r5-aspect406-source/1', 'dat_sha256': DAT_SHA,
              'signature': 'research-public verified by caller',
              'files': records, 'source_cpio_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'kernel_sha256': hashlib.sha256(kernel).hexdigest(),
              'mount_overlay': {'usr': 'nflasha15; lower rootfs/usr content hidden'},
              'original_components_modified': False, 'partition_images_written': False,
              'camera_io': False, 'complete_menu_verified': False}
    with (destination/'source-manifest.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return {key: value for key, value in report.items() if key != 'files'} | {'entries': len(records)}
