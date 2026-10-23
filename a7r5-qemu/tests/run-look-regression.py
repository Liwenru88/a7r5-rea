"""仅收集本轮相关的固定回归文件，保留日志和机器可读回执。"""
import importlib.util
import json
import os
from pathlib import Path
import unittest

LAB=Path(__file__).resolve().parents[1]
os.environ.setdefault('LOOK_REFERENCE_PARAMETERS',str(LAB/'runs/native-look-cp-509uu886/look-parameters.json'))
FILES=('test-look-reference.py','test-look-live.py','test-look-chroma.py','test-look-camera-jpeg.py',
       'test-look-integrated.py','test-look-matrix-inline.py','test-look-matrix-compact.py',
       'test-look-load-audit.py','test-look-joint.py')
suite=unittest.TestSuite()
for filename in FILES:
    spec=importlib.util.spec_from_file_location(filename.replace('-','_').replace('.py',''),LAB/'tests'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
number=1
while (output:=LAB/'logs'/('look-joint-regression-20261022'+(f'-{number:02}' if number>1 else '')+'.log')).exists():number+=1
with output.open('x') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
record=dict(status='passed' if result.wasSuccessful() else 'failed',tests=result.testsRun,
    failures=len(result.failures),errors=len(result.errors),files=FILES,
    camera_io=False,SD_io=False,original_images_modified=False)
with output.with_suffix('.json').open('x') as stream:json.dump(record,stream,indent=2)
print(json.dumps(record,indent=2));raise SystemExit(not result.wasSuccessful())
