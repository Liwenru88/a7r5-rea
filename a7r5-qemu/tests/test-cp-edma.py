"""同一模型代码的搬运/失败契约，以及候选模型源码身份门槛。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from cp_native_probe import research_binary
from runtime_manifest import digest


class EDMAContract(unittest.TestCase):
    def test_actual_bytes_interrupt_masks_cycles_and_failure_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='cp-edma-test-',dir=LAB/'build') as folder:
            binary=Path(folder)/'contract'
            subprocess.run(['/usr/bin/clang','-std=c11','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-g',str(LAB/'tests/test-cp-edma.c'),
                '-o',str(binary)],check=True,capture_output=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.stdout,'CP_EDMA_CONTRACT_OK directions=2 channels=8 real_copy=16 no_link_or_message_synthesis=1\n')
            self.assertEqual(result.stderr,'')

    def test_model_source_change_or_missing_receipt_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory(prefix='cp-edma-identity-',dir=LAB/'build') as folder:
            root=Path(folder);sources=root/'source/qemu';sources.mkdir(parents=True)
            board=sources/'a7r5-cp-boot.c';board.write_text('test board')
            header=sources/'a7r5-cp-edma.h';header.write_text('test model')
            candidate=root/'build/cp-qemu-test';candidate.mkdir(parents=True)
            binary=candidate/'qemu';binary.write_bytes(b'test binary, not executable')
            receipt={'binary':'qemu','binary_bytes':binary.stat().st_size,
                'binary_sha256':digest(binary),'board_sha256':digest(board),
                'model_sources':{header.name:digest(header)}}
            record=candidate/'receipt.json';record.write_text(json.dumps(receipt))
            with patch('cp_native_probe.LAB',root):
                self.assertEqual(research_binary(candidate)[0],binary)
                header.write_text('changed model')
                with self.assertRaisesRegex(ValueError,'模型源码身份'):
                    research_binary(candidate)
                receipt.pop('model_sources');record.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError,'模型源码收据不完整'):
                    research_binary(candidate)


if __name__=='__main__':unittest.main()
