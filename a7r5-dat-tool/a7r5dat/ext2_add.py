"""向独立派生USR ext2镜像新增明确DSO；不导入打包/签名工具，不挂载镜像。"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile

from .ext2read import Ext2

DEBUGFS = Path('/opt/homebrew/opt/e2fsprogs/sbin/debugfs')
MAX_IMAGE = 512 << 20
MAX_DSO = 8 << 20
MAX_TOTAL = 16 << 20

def require(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def regular(path):
    p = Path(path).absolute()
    require(not p.is_symlink() and stat.S_ISREG(p.lstat().st_mode), '只接受无符号链接的普通文件')
    require(not p.resolve().is_relative_to('/dev'), '拒绝设备路径')
    return p

def identity(path):
    s = Path(path).stat()
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

def valid_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None

@dataclass(frozen=True)
class AddDso:
    source: Path
    path: str
    sha256: str

class Audit:
    """独立只读逐目录/逻辑块核验；不依赖debugfs的成功消息。"""
    def __init__(self, path):
        with Path(path).open('rb') as f:
            header = f.read(2048)
        require(len(header) == 2048 and header[1080:1082] == b'\x53\xef' and
                struct.unpack_from('<I', header, 1048)[0] <= 2, '不是支持的ext2镜像')
        self.fs = Ext2(path)
        self.raw = self.fs.mm
        try:
            self._geometry()
        except BaseException:
            self.close()
            raise

    def close(self):
        self.fs.mm.close()
        self.fs.f.close()

    def _geometry(self):
        r = self.raw
        f = self.fs
        require(len(r) <= MAX_IMAGE and len(r) >= 2048, '镜像大小不支持')
        first = struct.unpack_from('<I', r, 1044)[0]
        compat, incompat, ro = struct.unpack_from('<3I', r, 1116)
        require(f.block_size in (1024, 2048, 4096) and f.blocks_count*f.block_size == len(r), '文件系统几何不支持')
        require(f.inode_size in (128, 256) and first == int(f.block_size == 1024), 'inode几何不支持')
        require(incompat == 2 and not compat & 4 and not ro & ~3, '拒绝日志/extents/未知特性')
        require(0 < f.blocks_per_group <= f.block_size*8 and 0 < f.inodes_per_group <= f.block_size*8, '组几何无效')
        require(struct.unpack_from('<H', r, 1082)[0] == 1, '拒绝非干净文件系统')
        self.first = first
        self.groups = (f.blocks_count-first+f.blocks_per_group-1)//f.blocks_per_group
        require(0 < self.groups and f.bgd_off+self.groups*32 <= len(r), '组描述符越界')
        require(0 < f.inodes_count <= self.groups*f.inodes_per_group, 'inode总数与组不符')
        self.bitmaps = []
        free_blocks = free_inodes = 0
        for g in range(self.groups):
            off = f.bgd_off+g*32
            block_map, inode_map, table = struct.unpack_from('<3I', r, off)
            require(all(0 < p < f.blocks_count for p in (block_map, inode_map, table)), '组元数据越界')
            valid = min(f.blocks_per_group, f.blocks_count-first-g*f.blocks_per_group)
            bitmap = r[block_map*f.block_size:(block_map+1)*f.block_size]
            free = valid-(int.from_bytes(bitmap, 'little') & ((1 << valid)-1)).bit_count()
            inodes = min(f.inodes_per_group, max(0, f.inodes_count-g*f.inodes_per_group))
            imap = r[inode_map*f.block_size:(inode_map+1)*f.block_size]
            ifree = inodes-(int.from_bytes(imap, 'little') & ((1 << inodes)-1)).bit_count()
            require((free, ifree) == struct.unpack_from('<HH', r, off+12), '组空闲位图与计数不一致')
            require(table*f.block_size+inodes*f.inode_size <= len(r), 'inode表越界')
            self.bitmaps.append((bitmap, imap))
            free_blocks += free
            free_inodes += ifree
        require((free_blocks, free_inodes) == struct.unpack_from('<II', r, 1036), '超级块空闲计数不一致')
        self.free_blocks, self.free_inodes = free_blocks, free_inodes
        self.geometry = (len(r), f.inodes_count, f.blocks_count, f.block_size, f.blocks_per_group,
                         f.inodes_per_group, f.inode_size, first, compat, incompat, ro, bytes(r[1128:1144]))

    def block(self, number):
        f = self.fs
        require(self.first <= number < f.blocks_count and number > 0, '文件块越界')
        group, bit = divmod(number-self.first, f.blocks_per_group)
        require(self.bitmaps[group][0][bit//8] & (1 << (bit % 8)), '文件引用空闲块')
        return self.raw[number*f.block_size:(number+1)*f.block_size]

    def inode(self, ino):
        f = self.fs
        require(1 <= ino <= f.inodes_count, 'inode越界')
        group, index = divmod(ino-1, f.inodes_per_group)
        require(self.bitmaps[group][1][index//8] & (1 << (index % 8)), '目录引用空闲inode')
        off = f.inode_table(group)*f.block_size+index*f.inode_size
        raw = bytes(self.raw[off:off+f.inode_size])
        mode, uid, size = struct.unpack_from('<HHI', raw)
        if stat.S_ISREG(mode):
            require(not struct.unpack_from('<I', raw, 108)[0], '拒绝超过32位的文件大小')
        require(size <= MAX_IMAGE and not struct.unpack_from('<I', raw, 32)[0] & 0x80000, 'inode大小或布局不支持')
        return raw, mode, uid, size

    def chunks(self, raw, size):
        f = self.fs
        n = (size+f.block_size-1)//f.block_size
        count = f.block_size//4
        def descend(pointer, depth, left):
            if not pointer:
                for _ in range(left):
                    yield bytes(f.block_size)
                return
            if depth == 0:
                yield self.block(pointer)
                return
            entries = struct.unpack('<%dI' % count, self.block(pointer))
            capacity = count**(depth-1)
            for pointer in entries:
                used = min(left, capacity)
                if not used:
                    break
                yield from descend(pointer, depth-1, used)
                left -= used
        pointers = struct.unpack_from('<15I', raw, 40)
        remaining = size
        for index, pointer in enumerate(pointers):
            depth = max(0, index-11)
            take = min(n, count**depth)
            if not take:
                break
            for data in descend(pointer, depth, take):
                yield data[:min(len(data), remaining)]
                remaining -= min(len(data), remaining)
            n -= take
        require(not remaining, 'inode逻辑块不完整')

    def inventory(self):
        output = {}
        visited = set()
        todo = [('/', 2, 2)]
        while todo:
            path, ino, parent = todo.pop()
            require(path not in output and len(output) < 200000, '重复路径或目录数量越界')
            raw, mode, uid, size = self.inode(ino)
            row = dict(inode=ino, mode=mode, uid=uid, size=size, raw=raw)
            acl = struct.unpack_from('<I', raw, 104)[0]
            row['acl_sha256'] = hashlib.sha256(self.block(acl)).hexdigest() if acl else None
            row['mapping_sha256'] = self.mapping_digest(raw, size) if stat.S_ISDIR(mode) or stat.S_ISREG(mode) else None
            if stat.S_ISDIR(mode):
                require(ino not in visited, '目录循环或目录硬链接')
                visited.add(ino)
                data = b''.join(self.chunks(raw, size))
                row['directory_sha256'] = hashlib.sha256(data).hexdigest()
                pos = 0
                seen = set()
                while pos < len(data):
                    require(pos+8 <= len(data), '目录项头短读')
                    child, length, names, kind = struct.unpack_from('<IHBB', data, pos)
                    require(length >= 8 and length % 4 == 0 and names <= length-8 and names <= 255 and
                            pos+length <= len(data) and pos%self.fs.block_size+length <= self.fs.block_size, '目录记录越界')
                    name = data[pos+8:pos+8+names].decode('latin1')
                    if child:
                        require(name and '/' not in name and '\x00' not in name and name not in seen, '非法或重复目录名')
                        seen.add(name)
                        if name == '.':
                            require(child == ino, '目录self不符')
                        elif name == '..':
                            require(child == parent, '目录parent不符')
                        else:
                            todo.append((path.rstrip('/')+'/'+name, child, ino))
                    pos += length
                require({'.', '..'} <= seen, '目录缺少self/parent')
            elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                if stat.S_ISLNK(mode) and size <= 60 and not struct.unpack_from('<I', raw, 28)[0]:
                    h = hashlib.sha256(raw[40:40+size])
                else:
                    h = hashlib.sha256()
                    for chunk in self.chunks(raw, size):
                        h.update(chunk)
                row['sha256'] = h.hexdigest()
            else:
                require(stat.S_IFMT(mode) in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK), '未知inode类型')
            output[path] = row
        return output

    def mapping_digest(self, raw, size):
        """纳入间接表原字节，避免内容相同掩盖块映射元数据变化。"""
        count = self.fs.block_size//4
        needed = max(0, (size+self.fs.block_size-1)//self.fs.block_size-12)
        h = hashlib.sha256()
        def visit(pointer, depth, left):
            if not pointer or not left:
                return
            data = self.block(pointer)
            h.update(struct.pack('<I', pointer));h.update(data)
            if depth > 1:
                for child in struct.unpack('<%dI' % count, data):
                    used = min(left, count**(depth-1))
                    if not used:
                        break
                    visit(child, depth-1, used)
                    left -= used
        for depth, pointer in enumerate(struct.unpack_from('<3I', raw, 88), 1):
            used = min(needed, count**depth)
            visit(pointer, depth, used)
            needed -= used
        return h.hexdigest()

def tree_digest(rows):
    values = [(path, row['inode'], row['mode'], row['size'], row.get('sha256'),
               hashlib.sha256(row['raw']).hexdigest()) for path, row in sorted(rows.items())]
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()

def derive_usr_image(source, output, additions, expected_source_sha256, *, debugfs=DEBUGFS):
    """完整核验后无覆盖发布新普通镜像；所有失败均不发布输出。仅新增/lib/*.so。"""
    require(valid_sha(expected_source_sha256), '必须提供原镜像SHA256')
    source = regular(source)
    before_id = identity(source)
    require(2048 <= before_id[2] <= MAX_IMAGE and digest(source) == expected_source_sha256, '原镜像摘要或大小不符')
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink() and not output.parent.is_symlink() and
            output.parent.is_dir() and not output.parent.resolve().is_relative_to('/dev'), '输出已存在或目录不安全')
    require(1 <= len(additions) <= 8, '必须显式指定1到8个DSO')
    binary = regular(debugfs)
    paths = set()
    for add in additions:
        require(isinstance(add, AddDso) and valid_sha(add.sha256) and isinstance(add.path, str) and
                re.fullmatch(r'/lib/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,95}\.so', add.path) is not None and
                add.path not in paths, '新增DSO路径/摘要非法或重复')
        paths.add(add.path)
    old = Audit(source)
    try:
        old_rows = old.inventory()
        require('/lib' in old_rows and stat.S_ISDIR(old_rows['/lib']['mode']), '原/lib不是目录')
        require(not paths.intersection(old_rows), '拒绝替换已有路径')
        require(old.free_inodes >= len(additions), '空闲inode不足')
        geometry, bs = old.geometry, old.fs.block_size
        free_before = old.free_blocks
    finally:
        old.close()
    with tempfile.TemporaryDirectory(prefix='usr-add-', dir=output.parent, ignore_cleanup_errors=True) as temp:
        temp = Path(temp)
        require(not any(c in str(temp) for c in ('"', '\\', '\n', '\r')), '临时目录路径无法安全传递给debugfs')
        staged = []
        for i, add in enumerate(additions):
            p = regular(add.source)
            state = identity(p)
            require(64 <= state[2] <= MAX_DSO, 'DSO大小不支持')
            target = temp/f'dso-{i}.bin'
            with p.open('rb') as f, target.open('xb') as out:
                shutil.copyfileobj(f, out, 1 << 20)
            require(state == identity(p) and digest(target) == add.sha256, 'DSO源发生变化或摘要不符')
            with target.open('rb') as f:
                header = f.read(64)
            require(header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', header, 16) == (3, 183), 'DSO必须为小端AArch64 ET_DYN')
            staged.append((add, target, state[2]))
        require(sum(size for _, _, size in staged) <= MAX_TOTAL, 'DSO总容量超限')
        blocks = sum((size+bs-1)//bs+((size+bs-1)//bs+bs//4-1)//(bs//4)+3 for _, _, size in staged)+2
        require(blocks <= free_before, '空闲块不足（含间接块及目录增长预算）')
        candidate = temp/'derived.ext2'
        with source.open('rb') as f, candidate.open('xb') as out:
            shutil.copyfileobj(f, out, 1 << 20)
        candidate.chmod(0o600)
        require(identity(source) == before_id and digest(candidate) == expected_source_sha256, '镜像复制时源发生变化')
        commands = []
        for add, local, _ in staged:
            commands.append(f'write "{local}" {add.path}')
            for field, value in (('mode', '0100755'), ('uid', '0'), ('gid', '0'), ('atime', '0'), ('ctime', '0'), ('mtime', '0')):
                commands.append(f'set_inode_field {add.path} {field} {value}')
        script = temp/'add.cmd'
        script.write_text('\n'.join(commands)+'\n')
        run = subprocess.run([str(binary), '-w', '-f', str(script), str(candidate)], capture_output=True, text=True)
        require(run.returncode == 0, 'debugfs进程失败：'+run.stderr)
        check = Audit(candidate)
        try:
            require(check.geometry == geometry, '文件系统几何/功能/UUID发生变化')
            now = check.inventory()
            require(set(now) == set(old_rows)|paths, '全树路径集合发生非预期变化')
            allowed_dir_bytes = set(range(4, 8))|set(range(28, 32))|set(range(40, 100))
            for name, row in old_rows.items():
                other = now[name]
                require((row['inode'], row['mode'], row.get('sha256'), row['acl_sha256']) ==
                        (other['inode'], other['mode'], other.get('sha256'), other['acl_sha256']), '旧文件身份/内容/ACL变化：'+name)
                if name == '/lib':
                    require(all(a == b for i, (a, b) in enumerate(zip(row['raw'], other['raw'])) if i not in allowed_dir_bytes), '父目录非容量元数据变化')
                else:
                    require(row['raw'] == other['raw'], '旧inode元数据变化：'+name)
                    require((row['mapping_sha256'], row.get('directory_sha256')) ==
                            (other['mapping_sha256'], other.get('directory_sha256')), '旧映射/目录元数据变化：'+name)
            for add, _, size in staged:
                row = now[add.path]
                raw = row['raw']
                require(row['size'] == size and row['sha256'] == add.sha256 and row['mode'] == 0o100755 and
                        row['uid'] == 0 and struct.unpack_from('<H', raw, 24)[0] == 0 and
                        struct.unpack_from('<H', raw, 26)[0] == 1 and raw[8:24] == bytes(16) and
                        raw[32:36] == bytes(4) and raw[104:108] == bytes(4), '新增DSO内容/权限/属主/时间/链接/ACL不符')
                require(raw[120:124] == bytes(4), '新增DSO高位属主不符')
            free_after = check.free_blocks
            old_fingerprint, new_fingerprint = tree_digest(old_rows), tree_digest(now)
        finally:
            check.close()
        require(identity(source) == before_id and digest(source) == expected_source_sha256, '原镜像在派生过程中发生变化')
        result_sha = digest(candidate)
        with candidate.open('rb') as f:
            os.fsync(f.fileno())
        report = dict(schema='usr-ext2-add-dso/1', source=str(source), source_sha256=expected_source_sha256,
            output=str(output), output_sha256=result_sha, bytes=before_id[2], old_entries=len(old_rows),
            added=[dict(path=a.path, bytes=n, sha256=a.sha256, mode='0755', uid=0, gid=0) for a, _, n in staged],
            old_tree_sha256=old_fingerprint, output_tree_sha256=new_fingerprint,
            free_blocks_before=free_before, free_blocks_after=free_after,
            old_file_payload_and_inode_metadata_preserved=True, only_parent_capacity_fields_may_change=True,
            debugfs_sha256=digest(binary), debugfs_stdout=run.stdout, debugfs_stderr=run.stderr,
            input_modified=False, mounted=False, signed=False, DAT_created=False, device_io=False)
        # 同目录硬链接以原子“不存在才创建”发布，绝不使用可覆盖的rename/replace。
        os.link(candidate, output)
        return report
