"""在本机临时目录运行相同执行器；不触及系统预加载或相机。"""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT if (ROOT/'config.json').exists() else ROOT/'packages/key109-once-20261021-01'


class NativeExecutor(unittest.TestCase):
    def run_case(self, arm=True, gate=True, task_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp).resolve()
            neutral=tmp/'preload'
            neutral.write_bytes(b'/fixed-test.so\n' if arm else b'unknown.so\n')
            trigger=tmp/'gate'
            trigger.write_bytes(b'/bin/sh\0-c\0/bin/date -s 070421422017.26\0' if gate else b'other\0')
            marker=tmp/'marker'
            # 执行顺序由脚本断言：在它启动前必须已经精确中和。
            task=f'test "$(wc -c < {neutral})" -eq 512 && test "$(tr -d \'\\n\' < {neutral})" = "" && printf safe > {marker} && printf metadata-report'
            if task_failure: task='exit 7'
            config=dict(RUN_ID='a'*32,STATE_PATH=str(tmp/'state'),OUTPUT_PATH=str(tmp/'output'),
                        ARM_BYTES='/fixed-test.so\n',PRELOAD_PATH=str(neutral),GATE_PATH=str(trigger),TASK_SCRIPT=task)
            (tmp/'root_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in config.items())+
                                           '#define TASK_SECONDS 2\n#define OUTPUT_LIMIT 4096\n')
            (tmp/'root_once.c').write_bytes((PACKAGE/'materials/root_once.c').read_bytes())
            command=['/usr/bin/clang','-DA7R5_HOST_TEST','-Wall','-Wextra','-Werror','-O1','-g',
                     '-fsanitize=address,undefined',str(tmp/'root_once.c'),'-o',str(tmp/'executor')]
            compiled=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            launched=subprocess.run([str(tmp/'executor')],capture_output=True,text=True,timeout=5)
            if not gate:
                self.assertEqual(launched.returncode,100)
                self.assertFalse(marker.exists())
                self.assertFalse((tmp/'state').exists())
                return
            if not arm:
                self.assertEqual(launched.returncode,92)
                self.assertIn('FAILED 92',(tmp/'state').read_text())
                self.assertFalse(marker.exists())
                self.assertEqual(neutral.read_bytes(),b'unknown.so\n')
                return
            self.assertEqual(launched.returncode,0)
            state=''
            until=time.monotonic()+10
            while time.monotonic()<until:
                state=(tmp/'state').read_text() if (tmp/'state').exists() else ''
                if ' DONE ' in state or ' FAILED ' in state or ' TIMEOUT ' in state: break
                time.sleep(.05)
            self.assertIn('DONE '+('7' if task_failure else '0'),state)
            self.assertEqual(neutral.read_bytes(),b'\n'*512)
            if not task_failure:
                self.assertEqual(marker.read_bytes(),b'safe')
                self.assertEqual((tmp/'output').read_bytes(),b'metadata-report')
            self.assertFalse((tmp/'state.new').exists())

    def test_disarm_before_script_and_atomic_final_state(self): self.run_case()
    def test_unknown_arm_cannot_start_command_or_be_overwritten(self): self.run_case(arm=False)
    def test_unrelated_constructor_load_does_nothing(self): self.run_case(gate=False)
    def test_command_failure_is_not_done_zero(self): self.run_case(task_failure=True)
