"""研究工具的输入契约；不加载外部 RAW 引擎，不读取固件或设备。"""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / 'sony-r5-colorlab/R5ColorLab/chart_sources/v4.5'


class ResearchPathsTests(unittest.TestCase):
    def test_legacy_dat_audits_accept_explicit_source(self):
        for script in ('packaging406/final_verify.py', 'release406/verify_candidate.py'):
            with self.subTest(script=script):
                path = ROOT / 'a7r5-firmware-features/research/custom-filters/experiments' / script
                done = subprocess.run([sys.executable, '-B', str(path), '--help'],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn('--source-dat', done.stdout)

    def test_chart_input_bindings_use_caller_configuration(self):
        cases = [('build_synthetic_arw.py', 'SOURCE', 'R5_RAW_SOURCE'),
                 ('build_synthetic_arw.py', 'PARSER', 'R5_RAW_PARSER'),
                 ('convert_raf.py', 'IED', 'R5_IED_SOURCE'),
                 ('generate_arw.py', 'PROJECT', 'R5_IED_SOURCE'),
                 ('generate_arw.py', 'SOURCE', 'R5_RAW_SOURCE'),
                 ('prepare_design.py', 'SOURCE', 'R5_RAW_SOURCE')]
        with tempfile.TemporaryDirectory() as tmp:
            wanted = Path(tmp) / 'my input'
            for filename, binding, variable in cases:
                with self.subTest(filename=filename, binding=binding), patch.dict(os.environ, {variable: str(wanted)}):
                    node, = [n for n in ast.parse((CHART / filename).read_text()).body
                             if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == binding for t in n.targets)]
                    # 只执行输入声明，保留真实配置解析，避免引入不相关的外部引擎依赖。
                    scope = dict(Path=Path, os=os, ROOT=Path(tmp), HERE=Path(tmp))
                    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), scope)
                    self.assertEqual(scope[binding], wanted)

    def test_r6_comparison_uses_caller_raw_inputs(self):
        source = ROOT / 'sony-r5-colorlab/analysis/r6_st_reverse_20261028/reverse_and_compare.py'
        node, = [n for n in ast.parse(source.read_text()).body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'PATHS' for t in n.targets)]
        env = dict(R5_R6_RAW='/path/to/r6.ARW', R5_RAW_SOURCE='/path/to/r5.ARW', R5_RAW_REPORT='/path/to/report.json')
        with patch.dict(os.environ, env):
            scope = dict(Path=Path, os=os, ROOT=ROOT, HERE=source.parent)
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
        self.assertEqual(scope['PATHS']['r6_raw'], Path(env['R5_R6_RAW']))
        self.assertEqual(scope['PATHS']['r5_raw'], Path(env['R5_RAW_SOURCE']))
        self.assertEqual(scope['PATHS']['saved_raw_report'], Path(env['R5_RAW_REPORT']))


if __name__ == '__main__':
    unittest.main()
