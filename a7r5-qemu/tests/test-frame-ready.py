"""执行真实导出辅助程序：新帧稳定后导出，旧帧/损坏帧有界失败。"""
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pipeline', ROOT / 'tests/test-frame-pipeline.py')
pipeline = importlib.util.module_from_spec(spec); spec.loader.exec_module(pipeline)
from headless_osd_capture import decode_export


class FrameReady(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        driver = cls.root / 'main.c'
        driver.write_text('extern int hosd_wait_export(const char *, unsigned long, long);\n'
                          'int main(int argc,char **argv) { return argc==2 ? hosd_wait_export(argv[1],2,120) : 3; }\n')
        cls.binary = cls.root / 'export'
        subprocess.run(['/usr/bin/clang', '-O2', '-DHOSD_EXPORT_TEST',
                        str(ROOT / 'source/guest/headless-osd-export.c'), str(driver),
                        '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_stale_and_malformed_frames_fail_without_export(self):
        for raw in (pipeline.container(), b'bad-header'):
            with self.subTest(raw=raw[:8]):
                path = self.root / 'frame'; path.write_bytes(raw)
                result = subprocess.run([str(self.binary), str(path)], capture_output=True, timeout=2)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b'HEADLESS_OSD_BEGIN', result.stdout)

    def test_new_atomic_generation_is_exported_and_independently_validated(self):
        old = pipeline.container()
        raw = bytearray(old)
        struct.pack_into('<Q', raw, 8, 3); struct.pack_into('<Q', raw, 120, 3)
        raw[40:48] = bytes(8)
        value = 14695981039346656037
        for byte in raw:
            value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
        struct.pack_into('<Q', raw, 40, value)
        path = self.root / 'frame'; path.write_bytes(old)
        new = self.root / 'next'; new.write_bytes(raw)
        def replace():
            time.sleep(.025)
            new.replace(path)
        writer = threading.Thread(target=replace); writer.start()
        result = subprocess.run([str(self.binary), str(path)], capture_output=True, timeout=2)
        writer.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        checked, info = decode_export(result.stdout)
        self.assertEqual(checked, raw)
        self.assertEqual(info['sequence'], 3)
        self.assertIn(b'HEADLESS_OSD_READY after=2 sequence=3', result.stdout)

    def test_metadata_churn_does_not_block_stable_pixel_source(self):
        # 只改元数据提交序列，像素来源固定；本测试验证就绪门槛，完整校验另有用例。
        raw = bytearray(pipeline.container())
        struct.pack_into('<Q', raw, 120, 2)
        path = self.root / 'churn'; path.write_bytes(raw)
        stop = threading.Event()
        def replace():
            seq = 3
            while not stop.is_set():
                struct.pack_into('<Q', raw, 8, seq)
                target = self.root / 'churn-next'; target.write_bytes(raw); target.replace(path)
                seq += 1
                stop.wait(.005)
        writer = threading.Thread(target=replace); writer.start()
        try:
            result = subprocess.run([str(self.binary), str(path)], capture_output=True, timeout=2)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'HEADLESS_OSD_READY after=2', result.stdout)
        finally:
            stop.set(); writer.join()


if __name__ == '__main__':
    unittest.main()
