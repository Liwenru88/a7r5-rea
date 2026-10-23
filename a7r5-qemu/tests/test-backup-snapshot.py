"""只读设置解析的边界回归，不触及真实镜像或设备。"""
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from backup_snapshot import BackupSnapshot


def backup(payload=b'abc', pointer=None):
    raw = bytearray(272+len(payload)); raw[12:16] = b'BK4\0'
    struct.pack_into('<4I', raw, 16, 1, 1, 272, len(payload))
    struct.pack_into('<HI', raw, 256, 1, 0)
    struct.pack_into('<HI', raw, 262, 0, pointer if pointer is not None else len(payload)<<24|272)
    raw[272:] = payload
    struct.pack_into('<I', raw, 32, sum(raw[:32])+sum(raw[36:]))
    return raw


class SnapshotContract(unittest.TestCase):
    def test_exact_end_inline_and_variable_properties(self):
        for payload, pointer, expected in ((b'abc', None, b'abc'),
                                           (struct.pack('<HH', 2, 3)+b'ab\0', 272, b'ab'),
                                           (struct.pack('<H', 3)+b'abc', 255<<24|272, b'abc')):
            with self.subTest(pointer=pointer):
                self.assertEqual(BackupSnapshot(backup(payload,pointer)).property(0), (0, expected))

    def test_checksum_and_all_pointer_forms_reject_invalid_data(self):
        raw = backup(); raw[-1] ^= 1
        with self.assertRaisesRegex(ValueError,'校验和'): BackupSnapshot(raw)
        for pointer in (0xffffffff, 3<<24|10, 4<<24|272, 272, 255<<24|274):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                BackupSnapshot(backup(pointer=pointer)).property(0)
        for ident in (-1, 1, 65536, 1<<32):
            with self.subTest(ident=ident), self.assertRaises(ValueError):
                BackupSnapshot(backup()).property(ident)


if __name__ == '__main__': unittest.main()
