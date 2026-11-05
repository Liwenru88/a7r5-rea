"""真实交叉编译拒绝旧邻接头遮蔽；不执行目标指令。"""
from pathlib import Path
import importlib.util
import io
import json
import os
import struct
import sys
import tempfile


def test_generated_crc_header_cannot_be_shadowed_by_source_sibling(tmp_path, monkeypatch):
    here=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('cp_boot_header_test',here/'build_paired.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    source=tmp_path/'bootstrap';source.mkdir()
    for name in ('guard.c','gates.S'):
        (source/name).write_bytes((here/'bootstrap'/name).read_bytes())
    (source/'image_constants.h').write_text('#error STALE_SOURCE_SIBLING_MUST_NEVER_BE_INCLUDED\n')
    monkeypatch.setattr(builder,'SOURCE',source)
    receipt=Path(os.environ['AF_CP_PAIR_RECEIPT']).resolve()
    with tempfile.TemporaryDirectory(prefix='cp-header-binding-',dir=builder.R/'.local/fixed-custom-filters') as temp:
        out=Path(temp)/'build'
        monkeypatch.setattr(sys,'argv',['build_paired.py','--module-receipt',str(receipt),'--output',str(out)])
        builder.main()
        report=json.loads((out/'verification.json').read_text())
        expected=int(report['RX_crc_msb_init0'],16)
        actual=struct.unpack_from('<I',(out/'bootstrap-rx.bin').read_bytes(),168)[0]
        assert actual==expected and report['bytes']==408


def test_compiled_descriptor_keeps_both_prepared_and_verified_mapping():
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    from capstone.arm_const import ARM_CC_NE,ARM_CC_EQ
    build=Path(os.environ['AF_CP_BOOT_BUILD'])
    raw=(build/'bootstrap.elf').read_bytes();elf=ELFFile(io.BytesIO(raw))
    symbols={s.name:int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols()}
    section=elf.get_section_by_name('.text');address=symbols['af_boot34_map']&~1
    offset=address-section['sh_addr'];md=Cs(CS_ARCH_ARM,CS_MODE_THUMB);md.detail=True
    code=list(md.disasm(section.data()[offset:offset+20],address))
    # 对实际目标码做静态契约检查：只拒phase0；phase1/2均保留，执行入口仍独立限制phase2。
    assert code[2].mnemonic=='cmp' and code[2].op_str=='r3, #0'
    assert code[3].mnemonic=='ite' and code[3].op_str=='ne'
    assert code[4].mnemonic=='adrne' and code[4].cc==ARM_CC_NE
    assert code[5].mnemonic=='moveq' and code[5].cc==ARM_CC_EQ and code[5].op_str=='r2, #0'
    assert 0x800000<=symbols['af_boot34_descriptor']<0x1000000
    phase_offset=symbols['phase']-section['sh_addr']
    phase=struct.unpack_from('<I',section.data(),phase_offset)[0]
    report=json.loads((build/'verification.json').read_text())
    assert phase==0x1a3ab40+report['RW_bytes']==int(report['phase_address'],16)
    assert phase+4<=0x1a3b000
