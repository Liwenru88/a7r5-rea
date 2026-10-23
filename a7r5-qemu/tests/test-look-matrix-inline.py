"""保护内嵌布局、原件、来源校验及本次原生等价输出契约。"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from look_materials import load,sha
from look_matrix_embed import build,compile_helper,branch,HELPER_VA,TABLE_VA


class InlineMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,_=load(LAB/'build/look-materials-77zf0trj')
        cls.candidate=LAB/'build/look-materials-inline-inbjxwos'

    def test_layout_inverse_and_original_regions_preserved(self):
        source=self.files['cpapp-b.bin'];target,report=build(source,self.files['matrix-delta.bin'])
        expected,_=load(self.candidate);self.assertEqual(target,expected['cpapp-b.bin'])
        self.assertLess(report['BSS_clear_end'],TABLE_VA)
        self.assertLessEqual(TABLE_VA+2304,report['stack_begin'])
        self.assertEqual(target[0x20148:0x2016c],source[0x20148:0x2016c])
        self.assertEqual(target[:0x1000],source[:0x1000])
        self.assertEqual(target[0xae74c0:HELPER_VA-0x108000],source[0xae74c0:HELPER_VA-0x108000])
        self.assertEqual(target[0x108d080:0x108ef5c],source[0x108d080:0x108ef5c])
        undo=bytearray(target)
        for row in report['patches']:
            undo[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['before'])
        self.assertEqual(undo[:len(source)],source)
        self.assertFalse(any(undo[len(source):]))
        self.assertFalse(report['device_deployment_ready'])

    def test_fail_closed_source_delta_helper_and_branch(self):
        source=self.files['cpapp-b.bin'];delta=self.files['matrix-delta.bin']
        for cp,d,h in ((b'bad',delta,None),(source,delta[:-1],None),(source,delta,b'bad')):
            with self.assertRaises(ValueError):
                build(cp,d) if h is None else build(cp,d,h)
        with self.assertRaises(ValueError):branch(0,0x4000000)

    def test_assembly_rebuild_and_destination_instructions(self):
        from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
        with tempfile.TemporaryDirectory(dir=LAB/'build') as tmp:
            compile_helper(Path(tmp));raw=(Path(tmp)/'matrix-helper.bin').read_bytes()
        destinations=[i.op_str for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw,HELPER_VA) if i.mnemonic=='b.w']
        self.assertEqual(destinations,['#0x71e488','#0xbef3b4'])

    def test_self_authorized_receipt_cannot_replace_embedded_CP(self):
        files,record=load(self.candidate)
        with tempfile.TemporaryDirectory(prefix='look-materials-tamper-',dir=LAB/'build') as tmp:
            folder=Path(tmp);files['cpapp-b.bin']=files['cpapp-b.bin'][:-1]+b'\x7f'
            for name,raw in files.items():(folder/name).write_bytes(raw)
            record['files']={name:dict(bytes=len(raw),sha256=sha(raw)) for name,raw in files.items()}
            (folder/'receipt.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'重建'):load(folder)

    def test_complete_native_case_parser_rejects_corruption(self):
        from look_embed_verify import parse
        r=json.loads((LAB/'runs/look-inline-verify-ydbziv_t/result.json').read_text())
        raw=(Path(r['QEMU_runs']['inline0']['run'])/'console.log').read_bytes()
        self.assertEqual(len(parse(raw)),3336)
        for bad in (raw[:-20],raw.replace(b'MATRIX_INLINE_CHECK_END',raw.splitlines()[1]+b'\nMATRIX_INLINE_CHECK_END')):
            with self.assertRaises(ValueError):parse(bad)


if __name__=='__main__':unittest.main()
