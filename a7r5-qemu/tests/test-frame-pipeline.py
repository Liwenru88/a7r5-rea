"""快照只校验一次，像素转换保持逐值一致，损坏数据不得发布。"""
import base64
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import menu_bridge
import menu_live
from headless_osd_capture import HEADER, METADATA, PIXELS, decode_export
from PIL import Image


def container():
    raw = bytearray(HEADER + METADATA + PIXELS)
    raw[:8] = b'HOSDAP02'
    struct.pack_into('<QIIIIQQIII', raw, 8, 2, 7, 640, 480, 1, 0x410000000, 0, PIXELS, METADATA, 0x1003)
    struct.pack_into('<H', raw, 64, 0x1003)
    struct.pack_into('<I', raw, 72, 7)
    struct.pack_into('<HH', raw, 84, 640, 480)
    struct.pack_into('<H', raw, 100, 0x1002)
    struct.pack_into('<I', raw, 108, 0x1003)
    struct.pack_into('<Q', raw, 120, 2)
    # 所有 16 位像素值都出现，避免只测特定菜单色造成通道颠倒盲区。
    pixels = b''.join(struct.pack('<H', i) for i in range(65536))
    raw[HEADER + METADATA:] = (pixels * 5)[:PIXELS]
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    struct.pack_into('<Q', raw, 40, value)
    return bytes(raw)


def transport(raw):
    return b'HEADLESS_OSD_BEGIN\n' + base64.b64encode(raw) + b'\nHEADLESS_OSD_END\n'


class FramePipeline(unittest.TestCase):
    def test_known_kernel_record_cannot_hide_snapshot_boundary(self):
        raw = container()
        original = transport(raw)
        noise = b'[  867.504812] [K]**UIPC ERROR** osal_snd_msg: No snd_msg registered. Skip snd to 0x86f\n'
        for marker in (b'HEADLESS_OSD_BEGIN', b'HEADLESS_OSD_END'):
            for position in (len(marker)//2, len(marker)):
                with self.subTest(marker=marker, position=position):
                    interrupted = original.replace(marker, marker[:position]+noise+marker[position:])
                    checked, _ = decode_export(interrupted)
                    self.assertEqual(checked, raw)

    def test_malformed_compression_cannot_allocate_or_bypass_checksum(self):
        size = HEADER+METADATA+PIXELS
        for payload in (b'', b'\0\0', b'\x01\x80', b'\xff\xff\0\0'*11,
                        b'\x01\0\0\0', b'\0\x80\0\0'):
            packed = b'HOSDRL01'+struct.pack('<I', size)+payload
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                decode_export(transport(packed))
    def test_one_validation_and_identical_rgba(self):
        raw = container()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = type('VM', (), {'out': root, 'console': root / 'console',
                                 'command': lambda self, *a, **kw: transport(raw)})()
            vm.console.touch()
            from headless_osd_capture import decode_export
            with patch.object(menu_bridge, 'decode_export', wraps=decode_export) as first, \
                    patch.object(menu_live, 'decode_export', wraps=decode_export) as second:
                menu_bridge.capture(vm, 'frame')
                self.assertEqual(first.call_count + second.call_count, 1, '一次快照发生重复解码校验')
            pixels = raw[HEADER + METADATA:]
            expected = bytearray()
            for (value,) in struct.iter_unpack('<H', pixels):
                expected.extend(((value >> 12)*17, ((value >> 8)&15)*17, ((value >> 4)&15)*17, (value&15)*17))
            with Image.open(root / 'frame.png') as image:
                self.assertEqual(image.convert('RGBA').tobytes(), expected)

    def test_corrupt_container_does_not_publish_frame(self):
        raw = bytearray(container()); raw[-1] ^= 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vm = type('VM', (), {'out': root, 'console': root / 'console',
                                 'command': lambda self, *a, **kw: transport(raw)})()
            vm.console.touch()
            with self.assertRaisesRegex(ValueError, 'checksum'):
                menu_bridge.capture(vm, 'frame')
            self.assertFalse((root / 'frame.png').exists())

    def test_missing_stale_or_mismatched_ready_receipt_cannot_publish(self):
        raw = container()
        for prefix, after in ((b'', 1), (b'HEADLESS_OSD_READY after=2 sequence=2 wait_ms=20\n', 2),
                              (b'HEADLESS_OSD_READY after=1 sequence=3 wait_ms=20\n', 1)):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vm = type('VM', (), {'out': root, 'console': root / 'console',
                                     'command': lambda self, *a, **kw: prefix+transport(raw)})()
                vm.console.touch()
                with self.assertRaises(ValueError):
                    menu_bridge.capture(vm, 'frame', after=after)
                self.assertFalse((root / 'frame.png').exists())


if __name__ == '__main__':
    unittest.main()
