"""真实宿主文件的私有COW逆补丁和默认不发布；不执行任何目标指令。"""
from pathlib import Path
import ctypes as c
import hashlib
import json
import os
import re
import subprocess
import sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
sys.path[:0]=[str(ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406'),str(HERE.parent)]
from candidate_preflight import read_cpio,compose,AP_SHA

def test_real_candidate_inverse_private_mapping_and_default_closed(tmp_path):
    preflight=Path(os.environ['AF_BOOTSTRAP_PREFLIGHT'])
    build=Path(os.environ['AF_BOOTSTRAP_BUILD'])
    report=json.loads(preflight.read_text())
    source=read_cpio(ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio',{'usr/lib/appFw.so'})['usr/lib/appFw.so']
    candidate=compose(source,AP_SHA,report['bootstrap']['file_patch_plan'])
    path=tmp_path/'appFw.so';path.write_bytes(candidate)
    pin=hashlib.sha256(candidate).hexdigest();assert pin==report['bootstrap']['memory_only_candidate_ap_sha256']
    header=(build/'af_bootstrap_manifest.h').read_text()
    assert header.count('"/usr/lib/appFw.so"')==1
    (tmp_path/'af_bootstrap_manifest.h').write_text(header.replace('"/usr/lib/appFw.so"',json.dumps(str(path))))
    target=tmp_path/'bootstrap-host.so'
    argv=['clang','-shared','-fPIC','-O2','-std=c11','-Wall','-Wextra','-Werror','-DAF_BOOTSTRAP_HOST_TEST',
        '-I'+str(tmp_path),'-I'+str(HERE),'-I'+str(HERE.parent/'native'),'-I'+str(ROOT/'a7r5-firmware-features/custom-filters/native'),
        str(HERE/'af_bootstrap406.c'),str(ROOT/'a7r5-firmware-features/custom-filters/native/af_ap_lifecycle.c'),
        str(ROOT/'a7r5-firmware-features/custom-filters/native/af_storage406.c'),
        str(ROOT/'a7r5-firmware-features/custom-filters/native/af_fsys406.c'),
        str(ROOT/'a7r5-firmware-features/custom-filters/native/af_media_snapshot406.c'),
        str(ROOT/'a7r5-firmware-features/custom-filters/native/af_sha256.c'),'-o',str(target)]
    r=subprocess.run(argv,capture_output=True,text=True);assert r.returncode==0,r.stderr
    api=c.CDLL(str(target));api.af_bootstrap406_bind_storage.argtypes=[c.c_int,c.c_int]
    assert api.af_bootstrap406_publish()==-4
    assert api.af_bootstrap406_bind_native_storage(-1)==-4
    assert api.af_bootstrap406_bind_native_media(0)==-4
    assert api.af_bootstrap406_test_canonical()==1
    assert hashlib.sha256(path.read_bytes()).hexdigest()==pin
    assert api.af_bootstrap406_publish()==-4 and api.af_bootstrap406_bind_storage(-1,-1)==-4
    with path.open('r+b') as f:f.seek(4096);f.write(bytes([candidate[4096]^1]))
    assert api.af_bootstrap406_test_canonical()==0
    with path.open('r+b') as f:f.seek(4096);f.write(candidate[4096:4097])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==pin
