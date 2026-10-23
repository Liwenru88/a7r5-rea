"""固定前像、公钥和库的离线信任候选重建；不导入USB／SSH，不提供设备写入。"""
import io
from pathlib import Path
import zlib
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from filesystems import FatImage, SquashImage, md5, require, sha
SOURCE_P1_SHA='acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731'
TARGET_SHA='a3733332c2a1b336226bb9000e01665ce54bec970aefc3334b88863b80f40ceb'
SONY_KEY_SHA='8281413b5607446939613e07d020b2c7d8ee2371349099de56bc8288f7be0a43'
PUBLIC_SHA='7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a'
KEY_PATH='/etc/VerificationKey.pem'
PATCH=bytes.fromhex('00008052c0035fd6')

TARGETS = {
    'libupdaterapi.so': (0x13324, 0x1356c, '1b334b9fb100601b1f8bc764cd9244bb32c2906101f4b2a8c0bd2e8d684df351', 71767),
    'libsdfileinputupdaterapi.so': (0xa9a8, 0xabf0, '257164d1cdf88757b8c0e2ba08ac47b06c46007410af308b7a8571b442b00cd2', None),
    'libseninputupdaterapi.so': (0x5244, 0x548c, '3240c3c70aaa645de3af74101cd4fb85263ec478cff830993a5cd4ba0a6bd704', 1349),
    'libuudfileinputupdaterapi.so': (0x95ac, 0x97f4, 'f8a622fd2b038080cf682b22febe60e379b916f72d8890687b1a6b2109c5182e', 321),
}

def elf_offset(elf, va):
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= va < segment['p_vaddr'] + segment['p_filesz']:
            return va - segment['p_vaddr'] + segment['p_offset']
    raise ValueError('ELF 地址不在文件内')

def verified_library(before, name):
    va, rsa_va, expected, cut = TARGETS[name]
    require(sha(before) == expected, '更新库身份不符：' + name)
    elf = ELFFile(io.BytesIO(before))
    require(elf['e_machine'] == 'EM_AARCH64', '更新库架构不符')
    symbols = {symbol.name: symbol for symbol in elf.get_section_by_name('.dynsym').iter_symbols()}
    key = symbols['_ZN7Updater21SignatureVerification9verifyKeyEPKc']
    rsa = symbols['_ZN7Updater21SignatureVerification15VerifySignatureENS_13verify_info_tEPKc']
    require((key['st_value'], key['st_size'], rsa['st_value'], rsa['st_size']) == (va, 584, rsa_va, 372), '更新库符号不符')
    offset = elf_offset(elf, va)
    require(before[offset:offset+8] == bytes.fromhex('fd7bb2a9e00301aa'), 'verifyKey 前像不符')
    instructions = [(i.mnemonic, i.op_str) for i in Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(PATCH, va)]
    require(instructions == [('mov', 'w0, #0'), ('ret', '')], '补丁指令不符')
    after = before[:offset] + PATCH + before[offset+8:]
    rsa_offset = elf_offset(elf, rsa_va)
    require(before[rsa_offset:rsa_offset+372] == after[rsa_offset:rsa_offset+372], 'RSA 验签函数被修改')
    return after, {'path': '/usr/lib/' + name, 'file_offset': offset, 'elf_va': hex(va),
                   'source_sha256': sha(before), 'target_sha256': sha(after),
                   'VerifySignature_372_bytes_unchanged': True, 'zlib_split': cut}

def compress_exact(clear, stored_size, cut=None):
    compressor = zlib.compressobj(9, zlib.DEFLATED, 15, 8, zlib.Z_DEFAULT_STRATEGY)
    packed = (compressor.compress(clear) + compressor.flush() if cut is None else
              compressor.compress(clear[:cut]) + compressor.flush(zlib.Z_BLOCK) +
              compressor.compress(clear[cut:]) + compressor.flush())
    require(len(packed) == stored_size, '压缩长度与原布局不同，拒绝填充或扩容')
    check = zlib.decompressobj()
    require(check.decompress(packed) + check.flush() == clear and check.eof and not check.unused_data and not check.unconsumed_tail,
            '不是单个完整压缩流')
    return packed

def construct(raw, private, public):
    require(len(raw) == 25100288 and sha(raw) == SOURCE_P1_SHA, '本机一号分区前像不符')
    fat = FatImage(raw)
    initrd = fat.read('/boot/initrd.img')
    sq = SquashImage(initrd)
    require(sha(sq.read(KEY_PATH)) == SONY_KEY_SHA, '原厂验签公钥不符')
    require(len(public)==451 and sha(public)==PUBLIC_SHA and public.startswith(b'-----BEGIN PUBLIC KEY-----'), '公钥不是已封存的配对身份')
    require(private is None, '本模块不读取或生成私钥')
    expected, changes = {KEY_PATH: public}, []
    fragment_changes = {}
    for name in TARGETS:
        path = '/usr/lib/' + name
        after, record = verified_library(sq.read(path), name)
        expected[path] = after
        changes.append(record)
    for path, after in expected.items():
        node = sq.nodes[path]
        require(not node['block_sizes'] and node['fragment_index'] != 0xffffffff, '目标未完整位于 fragment')
        index = node['fragment_index']
        require(not sq.fragments[index]['size'] & (1 << 24), '目标 fragment 不是 zlib')
        fragment_changes.setdefault(index, []).append((node['fragment_offset'], node['size'], after, path))
    patched = bytearray(initrd)
    for index, entries in fragment_changes.items():
        fragment = sq.fragments[index]
        clear = sq.fragment_data(index)
        size, start = fragment['size'] & 0xffffff, fragment['start']
        require(zlib.compress(clear, 9) == initrd[start:start+size], '原始库压缩流不符')
        changed = bytearray(clear)
        cuts = []
        for offset, length, after, path in entries:
            changed[offset:offset+length] = after
            if path != KEY_PATH and TARGETS[Path(path).name][3] is not None:
                cuts.append(TARGETS[Path(path).name][3])
        require(len(cuts) <= 1, '未支持共享 fragment 中多个压缩分段')
        patched[start:start+size] = compress_exact(bytes(changed), size, cuts[0] if cuts else None)
    patched = bytes(patched)
    ns = SquashImage(patched)
    require(ns.nodes == sq.nodes and ns.fragments == sq.fragments and patched[sq.inode_table:] == initrd[sq.inode_table:], 'SquashFS 元数据变化')
    changed_files = []
    for path, node in sq.nodes.items():
        if node['inode_type'] in (2, 9):
            before, after = sq.read(path), ns.read(path)
            require(after == expected.get(path, before), '非目标文件变化：' + path)
            if before != after:
                changed_files.append(path)
    require(set(changed_files) == set(expected), '信任修改范围不符')
    checksums = fat.read('/p1chksum')
    require(checksums == (md5(fat.read('/boot/vmlinux.bin')) + '  ./boot/vmlinux.bin\n' + md5(initrd) + '  ./boot/initrd.img\n').encode(), '原始 p1chksum 不符')
    new_sums = checksums.replace(md5(initrd).encode(), md5(patched).encode(), 1)
    result = bytearray(raw)
    fat.patch(result, '/boot/initrd.img', patched)
    fat.patch(result, '/p1chksum', new_sums)
    result = bytes(result)
    nf = FatImage(result)
    require(nf.entries == fat.entries and result[:fat.data_start] == raw[:fat.data_start], 'FAT 元数据变化')
    for path, entry in fat.entries.items():
        if not entry['is_directory']:
            require(nf.read(path) == {'/boot/initrd.img': patched, '/p1chksum': new_sums}.get(path, fat.read(path)), '非目标 FAT 文件变化')
    return result, patched, new_sums, {'changed_squashfs_files': sorted(changed_files), 'libraries': changes,
        'fat_metadata_unchanged': True, 'squashfs_metadata_unchanged': True,
        'current_parser_count': 1, 'p1chksum_valid': True,
        'kernel_unchanged': nf.read('/boot/vmlinux.bin') == fat.read('/boot/vmlinux.bin'),
        'all_other_contents_unchanged': True, 'rsa_signature_checks_preserved': True}
