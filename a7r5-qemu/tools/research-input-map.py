"""从当前模拟副本建立固定候选映射，生成证据，不注入任何按键。"""
import hashlib
import json
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from backup_snapshot import BackupSnapshot
from cpio_inputs import entries
from runtime_manifest import LAB, verified_inputs

SELECTED = {'UP': 2, 'LEFT': 4, 'DOWN': 6, 'RIGHT': 22, 'MENU': 19, 'ENTER': 20,
            'PLAYBACK': 34, 'C4': 35, 'DISP': 36, 'FN': 141, 'CUSTOM': 14,
            'CUSTOM2': 223, 'CUSTOM3': 228, 'FRONT_DIAL': 0x2f5,
            'REAR_DIAL_L': 0x2ea, 'REAR_DIAL_R': 0x2ef, 'CONTROL_WHEEL': 0x2f6,
            'MODE_DIAL': 0x2a, 'JOYSTICK':0xf1}


def mapping_records(forward,inverse,ident):
    forwards=[(a,pair) for a,pair in forward if pair[1]==ident]
    inverses=[(a,pair) for a,pair in inverse if pair[0]==ident]
    if len(forwards)!=1 or len(inverses)!=1 or forwards[0][1][0]!=inverses[0][1][1]:
        raise ValueError('键映射没有唯一且一致的正反向记录')
    return forwards[0][0],inverses[0][0]


def seed_backup(archive):
    with archive.open('rb') as stream:
        while True:
            header = stream.read(110)
            if len(header) != 110 or header[:6] != b'070701': raise ValueError('归档头不符')
            fields = [int(header[6+i*8:14+i*8], 16) for i in range(13)]
            name = stream.read(fields[11])[:-1].decode().removeprefix('./')
            stream.seek((-110-fields[11]) % 4, 1)
            if name == 'seed-backup.bin':
                if fields[6] > 8*1024*1024: raise ValueError('设置种子超出大小限制')
                return stream.read(fields[6])
            stream.seek(fields[6]+(-fields[6]) % 4, 1)
            if name == 'TRAILER!!!': raise ValueError('缺少设置种子')


def main():
    inputs = verified_inputs()
    archive = entries(inputs['initrd'])
    target = LAB / 'logs/function-expansion'
    target.mkdir(exist_ok=True)
    path = LAB / 'build/input-analysis/appFw.so'
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != archive['usr/lib/appFw.so']['sha256']: raise ValueError('appFw 分析副本与当前客体不一致')
    _, config = BackupSnapshot(seed_backup(inputs['initrd'])).property(0x7a0001)
    magic, padded, kind, size = struct.unpack_from('<4I', config)
    if magic != 0x214e4942 or kind != 2 or size > padded or size % 48 or 16+padded > len(config):
        raise ValueError('输入配置块不符')
    physical = {struct.unpack_from('<12I', config, offset)[2]
                for offset in range(16, 16+size, 48)}
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        relocations = {r['r_offset']: r.entry.get('r_addend', 0)
                       for section in elf.iter_sections() if section['sh_type'] == 'SHT_RELA'
                       for r in section.iter_relocations()}
        def read(address, length):
            segment = next(s for s in segments if s['p_vaddr'] <= address < address+length <= s['p_vaddr']+s['p_filesz'])
            start = segment['p_offset']+address-segment['p_vaddr']
            return raw[start:start+length]
        records = []
        for key, ident in SELECTED.items():
            label_address = 0x5767e58+16*ident
            label_id, _, pointer = struct.unpack('<IIQ', read(label_address, 16))
            name = read(relocations.get(label_address+8, pointer), 128).split(b'\0')[0].decode()
            # 此表按原始键码排序，保留项/缺项后不能用 UI ID 当数组下标。
            forward = [(0x371b978+8*i, struct.unpack('<II', read(0x371b978+8*i,8)))
                       for i in range(0x2300//8)]
            inverse = [(0x371dc78+8*i, struct.unpack('<II', read(0x371dc78+8*i,8)))
                       for i in range(0x2300//8)]
            forward_address,inverse_address=mapping_records(forward,inverse,ident)
            code, forward_id = struct.unpack('<II', read(forward_address, 8))
            inverse_id, inverse_code = struct.unpack('<II', read(inverse_address, 8))
            if (label_id, forward_id, inverse_id) != (ident, ident, ident) or code != inverse_code or code not in physical:
                raise ValueError('名称、正反向映射或输入配置不一致: '+key)
            records.append({'control': key, 'name': name, 'ui_id': hex(ident), 'code': hex(code),
                            'name_record': hex(label_address), 'forward_record': hex(forward_address),
                            'inverse_record': hex(inverse_address), 'present_in_seed_key_config': True,
                            'evidence_level': 'static-only; behavior and physical assignment require runtime validation'})
    report = {'status': 'static-candidates-only', 'appfw_sha256': digest, 'records': records,
              'backup_property': '0x7a0001', 'backup_property_sha256': hashlib.sha256(config).hexdigest(),
              'backup_format_reference': 'Sony-PMCA-RE pmca/backup; read-only BK4 subset',
              'consumer_reference': 'libObj+0xce4fc Backup_get_datasize/read(0x7a0001), +0xce604 block selector',
              'original_images_accessed': False}
    (target / 'controls-map-20261020.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
