"""确保替换菜单模拟库时保留固件条目；错误归档不产生成功结果。"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from cpio_inputs import only_observer_changed
spec=importlib.util.spec_from_file_location('guest',LAB/'tools/build-guest.py')
guest=importlib.util.module_from_spec(spec);spec.loader.exec_module(guest)


def archive(rows):
    output=bytearray()
    for name,data in [*rows,('TRAILER!!!',b'')]:
        name=name.encode()+b'\0'
        fields=[1,0o100755,0,0,1,0,len(data),0,0,0,0,len(name),0]
        header=b'070701'+b''.join(f'{value:08x}'.encode() for value in fields)
        output.extend(header+name+bytes((-110-len(name))%4)+data+bytes((-len(data))%4))
    return output


class GuestContract(unittest.TestCase):
    def test_rebuild_preserves_original_firmware_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input';target=root/'output'
            source.write_bytes(archive([('usr/bin/bootin.elf',b'original-firmware'),('simulation/menu-observe-a7r5-baseline.so',b'old')]))
            guest.replace_cpio(source,target,{'simulation/menu-observe-a7r5-baseline.so':b'new-simulation'})
            report=only_observer_changed(source,target)
            self.assertEqual(report['entries'],3)
            self.assertEqual(report['changed'],['simulation/menu-observe-a7r5-baseline.so'])

    def test_missing_entry_or_corrupt_archive_cannot_succeed(self):
        for payload in (archive([('usr/bin/bootin.elf',b'original')]),b'bad-header'):
            with self.subTest(payload=payload[:12]),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);source=root/'input';source.write_bytes(payload)
                with self.assertRaises(ValueError):
                    guest.replace_cpio(source,root/'output',{'simulation/menu-observe-a7r5-baseline.so':b'new'})


if __name__=='__main__':unittest.main()
