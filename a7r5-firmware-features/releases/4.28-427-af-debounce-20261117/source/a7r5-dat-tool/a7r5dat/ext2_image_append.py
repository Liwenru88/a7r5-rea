"""两个固定4.06图标资源的尾部块扩展；沿用旧inode，不更改通用Patch。"""
from dataclasses import dataclass
import hashlib
import struct

from .ext2_patch import Patch, require

@dataclass(frozen=True)
class ImageBinding:
    inode: int
    source_bytes: int
    target_bytes: int
    source_sha256: str
    target_sha256: str

class AppendImagePatch(Patch):
    # 只对应已锁定4.06 USR和本轮追加图标结果，不提供任意新白名单入口。
    _bindings = {
        '/share/app/image_00_23_IPSX.uxc': ImageBinding(84194,9598260,9677024,
            '80637a7bb69ccf2ddc6308a148847d1f14a88aa2001e4fc7de04b3e4c83ef061',
            'f54f991e79c68da5d4c62b2605403af9b427c2526169b32426064a5e8ee9ce59'),
        '/share/app/image_00_32_IPSX.uxc': ImageBinding(84053,9949936,10028700,
            'd5ec718d642fa8b813cf05c45bb0bc53f68b9bc4152fe003f01cdc39efc8a9db',
            '827a21b2d113436e2839baa5c2e3a9d9b03f422a13626ee37e25aadf35ae5667'),
    }

    def __init__(self, raw):
        super().__init__(raw)
        self.failed = False

    def _pointer_slot(self, off, pointers, logical, group):
        count = self.bs//4
        if logical < 12:
            return off+40+logical*4
        logical -= 12
        for depth in range(1, 4):
            capacity = count**depth
            if logical >= capacity:
                logical -= capacity
                continue
            root = 11+depth
            if not pointers[root]:
                pointers[root] = self.allocate(group)
                struct.pack_into('<I', self.data, off+40+root*4, pointers[root])
            block = pointers[root]
            for level in range(depth-1, 0, -1):
                index, logical = divmod(logical, count**level)
                address = block*self.bs+index*4
                child = struct.unpack_from('<I', self.data, address)[0]
                if not child:
                    child = self.allocate(group)
                    struct.pack_into('<I', self.data, address, child)
                require(0 < child < self.fs.blocks_count, '间接块指针越界')
                block = child
            require(0 < block < self.fs.blocks_count and logical < count, '末级指针槽越界')
            return block*self.bs+logical*4
        raise ValueError('文件逻辑块超出三级间接范围')

    def replace(self, path, expected, target):
        require(not self.failed, '先前失败的派生对象不可继续使用')
        try:
            binding = self._bindings.get(path)
            require(binding is not None and len(expected) == binding.source_bytes and
                    len(target) == binding.target_bytes and
                    hashlib.sha256(expected).hexdigest() == binding.source_sha256 and
                    hashlib.sha256(target).hexdigest() == binding.target_sha256, '图标路径/长度/源或目标摘要不符')
            inode = self.fs.walk(path)
            require(inode == binding.inode and not any(r['inode'] == inode for r in self.changed_files), '图标inode身份或重复替换不符')
            off = self.inode_offset(inode)
            mode, size, pointers = self.fs.inode(inode)
            require(mode & 0xf000 == 0x8000 and not struct.unpack_from('<I', self.data, off+32)[0] & 0x80000,
                    '图标不是普通块映射文件')
            require(self.fs.read_inode(inode) == expected and size == len(expected) and len(target) >= size,
                    '图标原内容不符或拒绝收缩')
            blocks = self.fs.inode_blocks(inode)
            require(len(blocks) == (size+self.bs-1)//self.bs and all(blocks) and len(set(blocks)) == len(blocks),
                    '原图标稀疏/重复/不完整')
            before_blocks = tuple(blocks)
            before_inode = bytes(self.data[off:off+self.fs.inode_size])
            allocated_before = len(self.allocated)
            need = (len(target)+self.bs-1)//self.bs
            extra = need-len(blocks)
            # 每个新数据块最多携带三个间接块，保守拒绝空间不足，不部分发布。
            require(extra*4 <= struct.unpack_from('<I', self.data, 1036)[0], '图标追加空闲块不足')
            sectors = struct.unpack_from('<I', self.data, off+28)[0]
            require(sectors+extra*4*(self.bs//512) < 1 << 32, 'i_blocks溢出')
            group = (inode-1)//self.fs.inodes_per_group
            while len(blocks) < need:
                slot = self._pointer_slot(off, pointers, len(blocks), group)
                require(struct.unpack_from('<I', self.data, slot)[0] == 0, '图标尾部指针槽已有占用')
                block = self.allocate(group)
                struct.pack_into('<I', self.data, slot, block)
                blocks.append(block)
            for index, block in enumerate(blocks):
                data = target[index*self.bs:(index+1)*self.bs]
                self.data[block*self.bs:block*self.bs+len(data)] = data
            struct.pack_into('<I', self.data, off+4, len(target))
            allocated = len(self.allocated)-allocated_before
            struct.pack_into('<I', self.data, off+28, sectors+allocated*(self.bs//512))
            require(self.fs.read_inode(inode) == target and tuple(self.fs.inode_blocks(inode)[:len(before_blocks)]) == before_blocks,
                    '图标回读不符或旧数据块地址变化')
            allowed = set(range(4,8))|set(range(28,32))|set(range(40,100))
            after_inode = self.data[off:off+self.fs.inode_size]
            require(all(a == b for i,(a,b) in enumerate(zip(before_inode,after_inode)) if i not in allowed),
                    '图标非容量inode元数据变化')
            self.changed_files.append(dict(path=path,inode=inode,before_bytes=size,after_bytes=len(target),
                new_allocated_blocks=allocated,old_data_block_addresses_preserved=True))
        except BaseException:
            self.failed = True
            raise

    def finish(self):
        require(not self.failed, '拒绝发布先前失败的图标派生对象')
        return super().finish()
