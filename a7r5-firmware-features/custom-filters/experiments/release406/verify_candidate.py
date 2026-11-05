"""复核最终DAT中的资源和产品库，独立读取UXD复杂记录；不运行设备。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'a7r5-dat-tool'))
from a7r5dat.ext2_add import Audit


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def bitmap(raw):
    assert raw[:12]==bytes.fromhex('757864070000000008000000')
    packed=struct.unpack_from('<I',raw,12)[0];count=packed&8191
    assert packed==count|(count<<12)
    base=(16+2*count+3)&~3;items={}
    for i in range(count):
        pointer=struct.unpack_from('<H',raw,16+2*i)[0]
        if pointer==65535:continue
        at=base+4*pointer;tag,flags,shape=struct.unpack_from('<3I',raw,at)
        assert tag==0x1a000000|i and flags in (0x40000000,0xc0000000,0x48000000,0xc8000000)
        complex_record=bool(flags&0x08000000);field=32 if complex_record else 12
        if complex_record:assert struct.unpack_from('<I',raw,at+12)[0]==0x10002
        size,offset=struct.unpack_from('<2I',raw,at+field);start=at+4+offset
        assert size and at+field+8<=start<start+size<=len(raw)
        items[i]=dict(at=at,flags=flags,shape=shape,offset=offset,size=size,sha256=sha(raw[start:start+size]),complex=complex_record)
    return count,items


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',required=True,type=Path);parser.add_argument('--source-workspace',required=True,type=Path)
    parser.add_argument('--version',choices=('4.10','4.12'),default='4.10')
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    release=args.release.resolve();out=args.output.resolve()
    assert release.is_relative_to(ROOT/'.local/fixed-custom-filters')
    assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    package=release/('update'+args.version.replace('.',''));receipt=json.loads((package/'verification.json').read_text())
    done=json.loads((package/'COMPLETED.json').read_text());manifest=json.loads((release/'staging.json').read_text())
    assert done['sha256']==receipt['sha256']==digest(package/'BODYDATA.DAT')
    assert receipt['version']==args.version and receipt['signature_verified'] and receipt['independent_decryption_exact']
    assert not receipt['device_acceptance_verified'] and not receipt['device_installation_approved']
    before=Audit(args.source_workspace.resolve()/'archive/0700_part_image/dev/nflasha15')
    after=Audit(package/'readback/archive/0700_part_image/dev/nflasha15')
    images=[];modules=[]
    try:
        for suffix in ('23','32'):
            name=f'/share/app/image_00_{suffix}_IPSX.uxc'
            a=before.fs.read_inode(before.fs.walk(name));b=after.fs.read_inode(after.fs.walk(name))
            count,old=bitmap(a);new_count,new=bitmap(b)
            assert count==7844 and new_count==7858 and len(new)==len(old)+14
            for index,row in old.items():
                changed=new[index]
                assert all(changed[k]==row[k] for k in ('flags','shape','size','sha256','complex'))
                assert changed['at']==row['at']+28 and changed['offset']==row['offset']+280
            assert sum(row['complex'] for row in old.values())==30
            images.append(dict(path=name,sha256=sha(b),old_payloads_identical=len(old),complex_payloads_identical=30,new_icons=14))
        for row in manifest['dsos']:
            raw=after.fs.read_inode(after.fs.walk(row['target']))
            assert sha(raw)==row['sha256'] and len(raw)==row['bytes']
            modules.append(dict(path=row['target'],sha256=sha(raw),bytes=len(raw)))
    finally:
        before.close();after.close()
    source_dat=Path('/Users/wenruli/Desktop/索尼/BODYDATA.DAT')
    assert digest(source_dat)=='3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2'
    codec=ROOT/'.local/fixed-custom-filters/integration52-fsys-codec/verification.json'
    source_cp=package/'readback/components/cpapp-b.bin'
    previous=ROOT/'.local/incident409-20261101/candidate409/components/cpapp-b.bin'
    report=dict(status='PASS_CURRENT_RESEARCH_DAT_CONTENT_AUDIT_NOT_DEVICE_ACCEPTANCE',
        version=args.version,DAT_sha256=receipt['sha256'],images=images,modules=modules,
        CP_sha256=digest(source_cp),CP_unchanged_from_previous_research_candidate=digest(source_cp)==digest(previous),
        original_Fsys_codec_receipt_sha256=digest(codec),
        original_Fsys_volume_IO_verified=False,actual_EVF_JPG_pixels_verified=False,
        CP_ISP_hardware_emulated=False,camera_io=False,
        source_sha256={str(Path(__file__).relative_to(ROOT)):digest(Path(__file__))})
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],DAT_sha256=report['DAT_sha256'],original_complex_payloads_verified=60),ensure_ascii=False))


if __name__=='__main__':main()
