"""冻结的FAT12读取与定长替换辅助。"""
import hashlib
import struct
import zlib


def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

class FatImage:
    def __init__(self, data):
        self.data = data
        self.sector = struct.unpack_from('<H', data, 11)[0]
        self.cluster_bytes = self.sector * data[13]
        reserved = struct.unpack_from('<H', data, 14)[0]
        copies = data[16]
        roots = struct.unpack_from('<H', data, 17)[0]
        spf = struct.unpack_from('<H', data, 22)[0]
        require(data[54:62] == b'FAT12   ', 'Expected original FAT12')
        self.fat_start = reserved * self.sector
        self.root_start = self.fat_start + copies * spf * self.sector
        self.root_size = ((roots * 32 + self.sector - 1) // self.sector) * self.sector
        self.data_start = self.root_start + self.root_size
        self.entries = {}
        self.walk([(self.root_start, self.root_size)], '')

    def chain(self, cluster):
        seen = set()
        result = []
        while cluster >= 2 and cluster < 0xff8:
            require(cluster not in seen, 'FAT cluster chain loop')
            seen.add(cluster)
            offset = self.data_start + (cluster - 2) * self.cluster_bytes
            require(offset + self.cluster_bytes <= len(self.data), 'FAT cluster outside image')
            result.append((offset, self.cluster_bytes))
            pos = self.fat_start + cluster * 3 // 2
            pair = struct.unpack_from('<H', self.data, pos)[0]
            cluster = (pair >> 4) if cluster & 1 else (pair & 0xfff)
        require(cluster >= 0xff8 or not result, 'FAT chain ended on bad/free cluster')
        return result

    def walk(self, extents, parent):
        name_parts = {}
        for start, size in extents:
            for off in range(start, start + size, 32):
                e = self.data[off:off + 32]
                if e[0] == 0:
                    return
                if e[0] == 0xe5:
                    name_parts = {}
                    continue
                if e[11] == 0x0f:
                    seq = e[0] & 0x1f
                    if e[0] & 0x40:
                        name_parts = {}
                    name_parts[seq] = e[1:11] + e[14:26] + e[28:32]
                    continue
                if e[11] & 8:
                    name_parts = {}
                    continue
                if name_parts:
                    name = b''.join(name_parts[i] for i in sorted(name_parts)).decode('utf-16le').rstrip('\0\uffff')
                else:
                    name = e[:8].decode('ascii').rstrip()
                    ext = e[8:11].decode('ascii').rstrip()
                    if ext:
                        name += '.' + ext
                name_parts = {}
                if name in ('.', '..'):
                    continue
                path = parent + '/' + name
                cluster = struct.unpack_from('<H', e, 26)[0]
                length = struct.unpack_from('<I', e, 28)[0]
                entry = {'path': path, 'size': length, 'directory_entry_offset': off,
                         'directory_entry_sha256': sha(e), 'extents': self.chain(cluster),
                         'is_directory': bool(e[11] & 16)}
                key = path.casefold()
                require(key not in self.entries, 'Duplicate FAT path')
                self.entries[key] = entry
                if entry['is_directory']:
                    self.walk(entry['extents'], path)

    def read(self, path):
        e = self.entries[path.casefold()]
        require(not e['is_directory'], 'Cannot read directory')
        raw = b''.join(self.data[o:o+n] for o, n in e['extents'])
        require(len(raw) >= e['size'], 'FAT allocation too short')
        return raw[:e['size']]

    def patch(self, output, path, content):
        entry = self.entries[path.casefold()]
        require(len(content) == entry['size'], 'FAT file length must be unchanged')
        pos = 0
        used = []
        for off, length in entry['extents']:
            take = min(length, len(content) - pos)
            if take <= 0:
                break
            output[off:off+take] = content[pos:pos+take]
            used.append((off, take))
            pos += take
        require(pos == len(content), 'Short FAT write')
        return used


def md5(raw):
    return hashlib.md5(raw).hexdigest()

class SquashImage:
    def __init__(self, data):
        self.data = data
        fields = struct.unpack_from('<5I6H8Q', data)
        require(fields[0] == 0x73717368 and fields[5] == 1 and fields[9:11] == (4, 0),
                'Expected zlib SquashFS 4.0')
        self.count, self.block_size, self.fragment_count = fields[1], fields[3], fields[4]
        self.root_ref, self.bytes_used = fields[11], fields[12]
        self.id_table, self.inode_table, self.dir_table, self.fragment_table = fields[13], fields[15], fields[16], fields[17]
        self.metadata_cache = {}
        self.fragments = []
        for i in range(self.fragment_count):
            table_off = struct.unpack_from('<Q', data, self.fragment_table + 8 * ((i * 16) // 8192))[0]
            start, size, unused = struct.unpack('<QII', self.meta(table_off, (i * 16) % 8192, 16))
            self.fragments.append({'start': start, 'size': size, 'unused': unused})
        self.nodes = {}
        self.walk(self.root_ref >> 16, self.root_ref & 65535, '/')
        require(len(self.nodes) == self.count, 'SquashFS traversal inode count mismatch')

    def metadata_block(self, offset):
        if offset not in self.metadata_cache:
            header = struct.unpack_from('<H', self.data, offset)[0]
            size = header & 0x7fff
            raw = self.data[offset+2:offset+2+size]
            require(len(raw) == size and size > 0, 'Invalid SquashFS metadata block')
            block = raw if header & 0x8000 else zlib.decompress(raw)
            self.metadata_cache[offset] = (block, offset + size + 2)
        return self.metadata_cache[offset]

    def meta(self, start, offset, size):
        result = bytearray()
        while len(result) < offset + size:
            block, start = self.metadata_block(start)
            result.extend(block)
        return bytes(result[offset:offset+size])

    def walk(self, block, offset, path):
        start = self.inode_table + block
        header = self.meta(start, offset, 16)
        inode_type, permissions, uid, gid, mtime, number = struct.unpack('<4H2I', header)
        node = {'path': path, 'inode_type': inode_type, 'permissions': oct(permissions),
                'uid_index': uid, 'gid_index': gid, 'mtime': mtime, 'inode_number': number,
                'inode_ref': (block << 16) | offset}
        require(path not in self.nodes, 'Duplicate SquashFS path')
        self.nodes[path] = node
        if inode_type in (1, 8):
            if inode_type == 1:
                db, links, length, do, parent = struct.unpack('<IIHHI', self.meta(start, offset+16, 16))
            else:
                links, length, db, parent, indexes, do, xattr = struct.unpack('<IIIIHHI', self.meta(start, offset+16, 24))
            directory = self.meta(self.dir_table + db, do, length - 3)
            pos = 0
            while pos < len(directory):
                count, child_block, base_inode = struct.unpack_from('<3I', directory, pos)
                pos += 12
                for _ in range(count + 1):
                    child_off, delta, dtype, name_size = struct.unpack_from('<HHHH', directory, pos)
                    pos += 8
                    name = directory[pos:pos+name_size+1].decode('ascii')
                    pos += name_size + 1
                    self.walk(child_block, child_off, path.rstrip('/') + '/' + name)
            require(pos == len(directory), 'Malformed directory')
        elif inode_type in (2, 9):
            if inode_type == 2:
                blocks_start, fragment, fragment_offset, length = struct.unpack('<4I', self.meta(start, offset+16, 16))
                extra = 16
            else:
                blocks_start, length, sparse, links, fragment, fragment_offset, xattr = struct.unpack('<QQQ4I', self.meta(start, offset+16, 40))
                extra = 40
            count = length // self.block_size if fragment != 0xffffffff else (length+self.block_size-1)//self.block_size
            sizes = struct.unpack('<' + str(count) + 'I', self.meta(start, offset+16+extra, count*4)) if count else ()
            node.update({'size': length, 'blocks_start': blocks_start, 'fragment_index': fragment,
                         'fragment_offset': fragment_offset, 'block_sizes': list(sizes)})
        elif inode_type in (3, 10):
            links, length = struct.unpack('<2I', self.meta(start, offset+16, 8))
            node['symlink_hex'] = self.meta(start, offset+24, length).hex()
        elif inode_type in (4, 5, 11, 12):
            links, rdev = struct.unpack('<2I', self.meta(start, offset+16, 8))
            node.update({'hard_links': links, 'rdev': rdev})
        elif inode_type in (6, 7, 13, 14):
            node['hard_links'] = struct.unpack('<I', self.meta(start, offset+16, 4))[0]
        else:
            raise ValueError('Unsupported SquashFS inode type ' + str(inode_type))

    def fragment_data(self, index):
        fragment = self.fragments[index]
        size = fragment['size'] & 0xffffff
        start = fragment['start']
        raw = self.data[start:start+size]
        return raw if fragment['size'] & (1 << 24) else zlib.decompress(raw)

    def read(self, path):
        node = self.nodes[path]
        require(node['inode_type'] in (2, 9), 'Expected regular file')
        out = bytearray()
        pos = node['blocks_start']
        for size in node['block_sizes']:
            length = min(node['size'] - len(out), self.block_size)
            if size == 0:
                out.extend(b'\0' * length)
            else:
                stored = size & 0xffffff
                raw = self.data[pos:pos+stored]
                block = raw if size & (1 << 24) else zlib.decompress(raw)
                require(len(block) == length, 'SquashFS data block length mismatch')
                out.extend(block)
                pos += stored
        if node['fragment_index'] != 0xffffffff:
            block = self.fragment_data(node['fragment_index'])
            off = node['fragment_offset']
            out.extend(block[off:off+node['size']-len(out)])
        require(len(out) == node['size'], 'SquashFS file size mismatch')
        return bytes(out)

