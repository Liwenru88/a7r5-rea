"""构建当前57挂钩管理UI，核验原像并运行受影响测试；不启动客体。"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[4]
FEATURE=ROOT/'a7r5-firmware-features/custom-filters'
NATIVE=FEATURE/'native'
OUT=ROOT/'.local/fixed-custom-filters/rename30/module-v3'
sys.path[:0]=[str(FEATURE),str(ROOT/'a7r5-qemu/tools')]
from media_candidate import extract
from a7filters.investigate import AP
from a7filters.ap_ui_hooks import collect


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    files=('af_slots.c','af_ui.c','af_ap_ui.c','af_ap_ui.S','af_labels.c','af_ap_names.c','af_ap_manage.c','af_ap_targets.c','af_ap_browser.c','af_ap_cards.c','af_ap_media.c')
    headers=('af_slots.h','af_ui.h','af_ap_ui.h','af_ap_names.h','af_labels.h','af_ap_manage.h','af_text.h',
             'af_ap_ui.ld','af_ap_ui_dynamic.ld','af_ap_targets.h','af_ap_browser.h','af_ap_cards.h','af_ap_media.h','af_media.h','af_grid.h')
    paths=[NATIVE/n for n in files+headers]
    paths += [FEATURE/'tests'/n for n in ('test_ap_names.py','test_ap_ui_dynamic.py','test_ap_ui_lifecycle.py','test_ap_targets.py','test_ap_targets_overwrite.py','test_ap_ui_overwrite.py','test_ap_targets_clear.py','test_ap_ui_clear.py','test_ap_manage_clear_menu.py','test_ap_ui_rename.py','test_ap_ui_rename_recovery.py','test_ap_ui_rename_parent.py')]
    paths += [FEATURE/'a7filters/ap_ui_hooks.py',Path(__file__)]
    paths += [FEATURE/'experiments/native-ui406'/n for n in ('loader.py','runtime.py','test_loader.py','test_ram_mount.py')]
    paths += [FEATURE/'experiments/native-targets406/verify_target.py']
    before={str(p.relative_to(ROOT)):sha(p) for p in paths};commands=[]
    def run(argv):
        start=time.monotonic();result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True)
        commands.append({'argv':argv,'exit_code':result.returncode,'seconds':time.monotonic()-start,
                         'stdout':result.stdout,'stderr':result.stderr})
        if result.returncode:
            (OUT/'failed-command.json').write_text(json.dumps(commands[-1],indent=2)+'\n')
            raise RuntimeError(result.stdout+result.stderr)
    for mode in ('legacy','dynamic'):
        directory=OUT/mode;directory.mkdir();objects=[]
        for name in files:
            output=directory/(name+'.o');objects.append(str(output))
            command=['clang','--target=aarch64-none-elf','-std=c11','-O2','-ffreestanding','-fno-builtin',
                     '-fno-stack-protector','-Wall','-Wextra','-Werror','-I'+str(NATIVE)]
            if mode=='dynamic':command+=['-DAF_AP_DYNAMIC','-fPIC']
            run(command+['-c',str(NATIVE/name),'-o',str(output)])
        command=['/opt/homebrew/opt/lld/bin/ld.lld','--build-id=none']
        if mode=='dynamic':command+=['-shared','-Bsymbolic','--no-undefined','-z','max-page-size=4096']
        run(command+['-T',str(NATIVE/('af_ap_ui_dynamic.ld' if mode=='dynamic' else 'af_ap_ui.ld')),
                     *objects,'-o',str(directory/'ap-ui.elf')])
    source=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    assert sha(source)=='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
    names=['usr/lib/appFw.so','usr/lib/libstdc++.so.6.0.22','usr/lib/libgcc_s.so.1']
    raw=extract(source,names);ap=AP(raw[names[0]])
    checks=re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+)\}',
        (NATIVE/'af_ap_ui.c').read_text().split('static const AfApCheck checks[] = {',1)[1].split('};',1)[0])
    assert len(checks)==132
    assert all(ap.u32(int(a,16))==int(b,16) for a,b in checks)
    legacy=collect(raw[names[0]],raw[names[1]],(OUT/'legacy/ap-ui.elf').read_bytes(),raw[names[2]])
    (OUT/'legacy-original-branches.json').write_text(json.dumps(legacy,indent=2)+'\n')
    run([str(ROOT/'.venv/bin/python'),'-B','-m','pytest','-q','-p','no:cacheprovider',
        str(FEATURE/'tests/test_ap_names.py'),str(FEATURE/'tests/test_ap_targets.py'),
        str(FEATURE/'tests/test_ap_targets_overwrite.py'),str(FEATURE/'tests/test_ap_ui_overwrite.py'),
        str(FEATURE/'tests/test_ap_ui_lifecycle.py'),str(FEATURE/'tests/test_ap_targets_clear.py'),
        str(FEATURE/'tests/test_ap_ui_clear.py'),str(FEATURE/'tests/test_ap_manage_clear_menu.py'),str(FEATURE/'tests/test_ap_ui_rename.py'),str(FEATURE/'tests/test_ap_ui_rename_recovery.py'),str(FEATURE/'tests/test_ap_ui_rename_parent.py'),
        str(FEATURE/'tests/test_ap_ui_dynamic.py'),
        str(FEATURE/'experiments/native-ui406/test_loader.py'),str(FEATURE/'experiments/native-ui406/test_ram_mount.py'),'--tb=short'])
    assert before=={str(p.relative_to(ROOT)):sha(p) for p in paths},'验证期间源码变化'
    receipt={'schema':'a7r5-ap-ui-dynamic-preflight/1','status':'PASS','commands':commands,
        'source_fingerprints':before,'AP_preimages_checked':len(checks),
        'dynamic_module_sha256':sha(OUT/'dynamic/ap-ui.elf'),
        'dynamic_module_bytes':(OUT/'dynamic/ap-ui.elf').stat().st_size,
        'camera_io':False,'guest_started':False,'CP_imaging':False,'persistence_verified':False}
    (OUT/'verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('commands','source_fingerprints')},indent=2))


if __name__=='__main__':main()
