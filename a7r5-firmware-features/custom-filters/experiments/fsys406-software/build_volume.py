"""隔离构建原Fsys文件后端实验，不改默认客体、原库或产品升级包。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
LAB=ROOT/'a7r5-qemu'
sys.path.insert(0,str(LAB/'tools'))
from media_candidate import add_files,extract,patch_property
from cpio_inputs import entries
from native_vm import dtb_properties
from virtual_fat import make_fixture
from volume_fixture import make_library


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--software',required=True,type=Path);args=parser.parse_args()
    out=args.output.absolute();assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    software=json.loads(args.software.read_text());assert software['status']=='PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS'
    repository=args.software.absolute().parent/'libaf_repository_media.so'
    artifact=software['artifacts']['libaf_repository_media.so']
    assert repository.stat().st_size==artifact['bytes'] and digest(repository)==artifact['sha256']
    previous=LAB/'build/aspect-guide406-20261026-01/guest-11';source=previous/'menu.cpio'
    assert digest(source)=='15089fc1b0a65dc7a198a2b11d9a56f6f55c746400e5cdc0122a9b878a768a53'
    native=ROOT/'a7r5-firmware-features/custom-filters/native';here=Path(__file__).parent;out.mkdir(parents=True)
    names=['libInfraFsys.so','libInfraMediaCommon.so','libMWF.so','libbackup.so','libosal_uipc.so','libosal_utm.so']
    libraries=extract(source,['usr/lib/'+n for n in names])
    for name,raw in libraries.items():(out/Path(name).name).write_bytes(raw)
    assert digest(out/'libInfraFsys.so')=='1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b'
    glibc=[str(LAB/'sdk/lib'/n) for n in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    common=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
            '-nostdlib','-ffreestanding','-O2','-mno-outline-atomics','-Wl,--no-undefined']
    units=[native/n for n in ('af_fsys406.c','af_cube.c','af_document.c','af_slots.c','af_sha256.c','af_ap_manage.c')]
    (out/'libaf_repository_media.so').write_bytes(repository.read_bytes())
    commands=[common+['-shared','-fPIC',str(here/'volume-config.c'),*glibc,'-o',str(out/'volume-config.so')],
       common+['-I'+str(native),'-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
       str(here/'volume-driver.c'),*map(str,units),'-Wl,--no-as-needed',*[str(out/n) for n in names],'-L'+str(out),'-laf_repository_media',
       '-Wl,--allow-shlib-undefined',*glibc,'-o',str(out/'volume-driver')]]
    logs=[]
    for argv in commands:
        result=subprocess.run(argv,capture_output=True,text=True);logs.append(dict(argv=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        (out/'compile.json').write_text(json.dumps(logs,indent=2)+'\n');assert result.returncode==0,result.stderr
    added={'simulation/af-volume-config.so':(out/'volume-config.so').read_bytes(),
           'simulation/af-volume-driver':(out/'volume-driver').read_bytes(),'simulation/af-volume.fat':make_library(make_fixture),
           'usr/lib/libaf_repository_media.so':repository.read_bytes()}
    before=entries(source);assert not set(added)&set(before)
    target=out/'volume.cpio';add_files(source,target,added);after=entries(target)
    assert set(after)-set(before)==set(added) and all(after[n]==r for n,r in before.items())
    original=json.loads((previous/'manifest.json').read_text());dtb=(previous/'virt.dtb').read_bytes();properties=dtb_properties(dtb)
    bootargs=properties[('/chosen','bootargs')].rstrip(b'\0')
    for match in re.finditer(rb'memrsv=(0x[0-9a-fA-F]+)@(0x[0-9a-fA-F]+)',bootargs):
        size,start=map(lambda x:int(x,16),match.groups());assert not(start<0x41ea00000 and start+size>0x41e600000)
    bootargs=re.sub(rb'ramdisk_size=\d+',b'ramdisk_size='+str((target.stat().st_size+1023)//1024).encode(),bootargs)
    dtb=patch_property(dtb,'/chosen','bootargs',bootargs+b' memrsv=0x00400000@0x41e600000:uc a7r5.fsys_volume=1\0')
    dtb=patch_property(dtb,'/chosen','linux,initrd-end',(0x440000000+target.stat().st_size).to_bytes(8,'big'))
    (out/'virt.dtb').write_bytes(dtb);files={}
    for key,row in original['files'].items():
        p=target if key=='initrd' else out/'virt.dtb' if key=='dtb' else LAB/row['path']
        if key not in ('initrd','dtb'):assert digest(p)==row['sha256']
        files[key]=dict(path=str(p),bytes=p.stat().st_size,sha256=digest(p))
    report=dict(schema='af-fsys-volume406/1',files=files,original_entries_unchanged=True,added=list(added),
        original_libraries={n:hashlib.sha256(r).hexdigest() for n,r in libraries.items()},
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),here/'volume-config.c',here/'volume-driver.c',here/'volume_fixture.py',*units]},
        physical_SD=False,CP_ISP_hardware_emulated=False,camera_io=False,deployable=False)
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'manifest.json',flush=True)


if __name__=='__main__':main()
