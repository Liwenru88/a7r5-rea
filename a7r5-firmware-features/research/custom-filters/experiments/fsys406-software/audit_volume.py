"""独立复核原卷执行、合成FAT实际文件及生产导入／恢复回执。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from volume_fixture import payloads,CUBE

ROOT=Path(__file__).resolve().parents[4]


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def read_fat(raw):
    """只读FAT16，独立核双表、簇归属、LFN序号／校验和及文件内容。"""
    assert len(raw)==0x400000 and raw[510:512]==b'\x55\xaa'
    assert struct.unpack_from('<HBHBHHBH',raw,11)==(512,1,1,2,512,8192,0xf8,32)
    fat=raw[512:33*512];assert fat==raw[33*512:65*512];used=set();files={}
    def chain(first):
        blocks=[];visited=set()
        while first<0xfff8:
            assert 2<=first<8097 and first not in visited and first not in used
            visited.add(first);used.add(first);at=(97+first-2)*512;blocks.append(raw[at:at+512])
            first=struct.unpack_from('<H',fat,first*2)[0]
        return b''.join(blocks)
    def directory(data,prefix,depth=0):
        assert depth<=8;lfn=[];checksum=None;sequence=0
        for at in range(0,len(data),32):
            e=data[at:at+32]
            if not e[0]:break
            if e[0]==0xe5:lfn=[];checksum=None;sequence=0;continue
            if e[11]==15:
                if e[0]&0x40:assert not lfn;checksum=e[13];sequence=e[0]&31
                assert sequence>0 and e[0]&31==sequence and e[13]==checksum and not e[12] and e[26:28]==b'\0\0'
                lfn.insert(0,e[1:11]+e[14:26]+e[28:32]);sequence-=1;continue
            if e[11]&8:assert not lfn;continue
            if lfn:
                expected=0
                for c in e[:11]:expected=((expected>>1)|((expected&1)<<7))+c;expected&=255
                assert checksum==expected and sequence==0
                name=b''.join(lfn).decode('utf-16le').split('\0',1)[0];lfn=[];checksum=None
            else:
                stem=e[:8].decode().rstrip();extension=e[8:11].decode().rstrip();name=stem+('.'+extension if extension else '')
            if name in ('.','..'):continue
            assert name and '/' not in name and '\\' not in name
            first,size=struct.unpack_from('<HI',e,26);body=chain(first) if first else b'';path=prefix+'/'+name
            if e[11]&16:directory(body,path,depth+1)
            else:
                assert path not in files and size<=len(body)<size+512;files[path]=body[:size]
        assert not lfn
    directory(raw[65*512:97*512],'');return files


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--run',required=True,action='append',type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    out=args.output.absolute();assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    manifest=json.loads(args.manifest.read_text());assert manifest['schema']=='af-fsys-volume406/1'
    assert 'usr/lib/libaf_repository_media.so' in manifest['added']
    for name,h in manifest['source_sha256'].items():assert digest(ROOT/name)==h,name
    expected=payloads();runs=[]
    for run in args.run:
        receipt=run/'verification.json';d=json.loads(receipt.read_text());data=(run/'console.log').read_text(errors='strict').replace('\r','')
        assert d['status']=='PASS_ORIGINAL_FSYS_VOLUME_AND_ADAPTER_SOFTWARE_ONLY' and d['exit']=={'method':'qmp-quit','exit_code':0}
        assert d['manifest_sha256']==digest(args.manifest) and d['source_sha256']==digest(Path(__file__).with_name('run_volume.py'))
        actual={item['name']:(item['bytes'],item['sha256']) for item in d['files']}
        assert actual=={name:(len(raw),hashlib.sha256(raw).hexdigest()) for name,raw in expected.items()}
        volume=run/'synthetic-volume.fat';assert digest(volume)==d['synthetic_volume_sha256']
        files=read_fat(volume.read_bytes());root='/PRIVATE/SONY/PRO/LUT/'
        assert all(files[root+name]==raw for name,raw in expected.items())
        assert files[root+'PROBE.BIN']==CUBE
        imported=re.findall(r'^AF_VOLUME_IMPORTED slot=(\d+) kind=(\d+) generation=(\d+) polls=(\d+) name=(.*)$',data,re.M)
        assert [(int(slot),int(kind),int(generation)) for slot,kind,generation,_,_ in imported]==[(7,1,1),(8,0,1)]
        assert re.search(r'^AF_VOLUME_RESTORED slots=7,8 source=production_repository_guest_directory$',data,re.M)
        runs.append(dict(path=str(run.absolute()),receipt_sha256=digest(receipt),mount_flags=d['mount_flags'],
            original_files_verified=3,independent_FAT_files=len(files),production_CUBE_and_AFD1_import=True,
            saved_slots=[7,8],closed_reopened=True,QMP_exit_code=0))
    assert {r['mount_flags'] for r in runs}=={0,0x400}
    report=dict(status='PASS_ORIGINAL_FSYS_SD_LIBRARY_SOFTWARE_IMPORT_SAVE_RESTORE',runs=runs,
        original_Fsys_volume_IO_executed=True,original_Fsys_on_physical_SD_verified=False,
        production_adapter_verified=True,production_reference_fitting_and_repository_verified=True,
        test_media_model=True,test_body_directory=True,actual_body_persistence_verified=False,
        actual_EVF_JPG_pixels_verified=False,CP_ISP_hardware_emulated=False,camera_io=False,
        manifest_sha256=digest(args.manifest),source_sha256=digest(Path(__file__)))
    out.mkdir(parents=True);(out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],runs=len(runs),physical_SD_verified=False),ensure_ascii=False))


if __name__=='__main__':main()
