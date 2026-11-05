"""将实际CPU测试、源码与组件身份绑定，供离线归档门禁核对。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
REPORTS = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [p for folder in (HERE, HERE / 'runtime', HERE / 'tests', HERE.parent / 'native12-combined/tests')
             for p in folder.iterdir() if p.is_file() and p.suffix in ('.py','.c','.h','.S','.ld','.json')
             and p.name != 'current-candidate.json']
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def pytest_sessionstart(session):
    build = Path(os.environ.get('A7R5_NATIVE24_BUILD', ROOT / '.local/native24-runtime-20261103-05'))
    record = json.loads((build / 'build.json').read_text())
    for name, key in [('appFw.so','AP_sha256'), ('cpapp-b.bin','CP_sha256')]:
        if sha(build / name) != record[key]:
            raise pytest.UsageError('测试组件摘要不符：' + name)
    for name, value in record.get('owned_sources', {}).items():
        if sha(HERE / name) != value:
            raise pytest.UsageError('被测构建与当前拥有源码不符：' + name)
    session.stability_state = {'build': build, 'record': record, 'sources': sources(), 'started': time.monotonic()}


def pytest_runtest_logreport(report):
    REPORTS.append({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome})


def pytest_sessionfinish(session, exitstatus):
    value = getattr(session, 'stability_state', None)
    if value is None:
        return
    unchanged = sources() == value['sources']
    if not unchanged:
        session.exitstatus = 1
    folder = os.environ.get('A7R5_NATIVE24_EVIDENCE')
    if not folder:
        return
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    selected = [item.nodeid for item in session.items]
    passed = {r['nodeid'] for r in REPORTS if r['when']=='call' and r['outcome']=='passed'}
    full = (len(session.config.args)==1 and Path(session.config.args[0]).resolve()==HERE/'tests'
            and not session.config.option.keyword and not session.config.option.markexpr
            and not getattr(session.config.option, 'lf', False))
    report = {'schema':'native24-cpu-evidence/1', 'status':'PASS' if not exitstatus and unchanged and set(selected)==passed else 'FAIL',
              'exit_code':int(session.exitstatus), 'full_related_suite':full, 'tests':selected,
              'seconds':time.monotonic()-value['started'], 'AP_sha256':value['record']['AP_sha256'],
              'CP_sha256':value['record']['CP_sha256'], 'build_receipt_sha256':sha(value['build']/'build.json'),
              'sources_unchanged':unchanged, 'sources':value['sources'], 'reports':REPORTS, 'argv':sys.argv,
              'camera_io':False, 'boundary':'真实AP／CP，OS／文件／UI／E4执行边界为明确夹具'}
    (target/'session-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
