"""离线小ext2派生镜像联验；不挂载、签名或接触设备。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat/ext2read.py').exists())
sys.path.insert(0,str(ROOT/'a7r5-dat-tool'))
import a7r5dat
PROPOSAL=Path(__file__).resolve().parents[1]/'a7r5dat/ext2_add.py'
if not PROPOSAL.exists():PROPOSAL=ROOT/'a7r5-dat-tool/a7r5dat/ext2_add.py'
spec=importlib.util.spec_from_file_location('a7r5dat.ext2_add',PROPOSAL)
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
MKE2FS=Path('/opt/homebrew/opt/e2fsprogs/sbin/mke2fs')
DEBUGFS=Path('/opt/homebrew/opt/e2fsprogs/sbin/debugfs')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def debug(image,*commands):
    for command in commands:
        r=subprocess.run([str(DEBUGFS),'-w','-R',command,str(image)],capture_output=True,text=True)
        assert r.returncode==0,r.stderr

@pytest.fixture
def image(tmp_path):
    source=tmp_path/'source.ext2'
    with source.open('xb') as f:f.truncate(4<<20)
    r=subprocess.run([str(MKE2FS),'-q','-t','ext2','-b','1024','-I','128','-O','filetype,sparse_super,large_file',str(source)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    payload=tmp_path/'old.bin';payload.write_bytes(b'old payload\x00\xff'*2000)
    debug(source,'mkdir /lib',f'write {payload} /lib/original.so','symlink /lib/original-link original.so')
    return source

def dso(tmp_path,name='new.so',size=70000):
    raw=bytearray(size);raw[:6]=b'\x7fELF\x02\x01';struct.pack_into('<HH',raw,16,3,183)
    for i in range(64,len(raw)):raw[i]=(i*29+7)%256
    p=tmp_path/name;p.write_bytes(raw);return p

def test_add_uses_new_inode_and_preserves_whole_old_tree(image,tmp_path):
    before=sha(image);a=dso(tmp_path);b=dso(tmp_path,'other.so',270000)
    out=tmp_path/'derived.ext2'
    report=module.derive_usr_image(image,out,[module.AddDso(a,'/lib/libaf_ui406.so',sha(a)),
        module.AddDso(b,'/lib/libaf_repository_media.so',sha(b))],before)
    assert sha(image)==before and out.stat().st_size==image.stat().st_size
    assert report['old_file_payload_and_inode_metadata_preserved'] and not report['input_modified']
    assert report['free_blocks_after']<report['free_blocks_before']
    audit=module.Audit(out)
    try:
        tree=audit.inventory()
        assert tree['/lib/libaf_ui406.so']['sha256']==sha(a)
        assert tree['/lib/libaf_repository_media.so']['sha256']==sha(b)
        assert tree['/lib/original-link']['sha256']==hashlib.sha256(b'original.so').hexdigest()
    finally:audit.close()
    # 独立原e2fsprogs完整结构检查，返回0才接受。
    fsck=subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck','-f','-n',str(out)],capture_output=True,text=True)
    assert fsck.returncode==0,fsck.stdout+fsck.stderr

@pytest.mark.parametrize('failure',['existing','duplicate','path','source_sha','dso_sha','capacity','metadata'])
def test_rejects_before_publication_and_preserves_source(image,tmp_path,failure):
    a=dso(tmp_path);before=sha(image);out=tmp_path/'result.ext2'
    additions=[module.AddDso(a,'/lib/new.so',sha(a))];expected=before
    if failure=='existing':additions=[module.AddDso(a,'/lib/original.so',sha(a))]
    if failure=='duplicate':additions*=2
    if failure=='path':additions=[module.AddDso(a,'/lib/../new.so',sha(a))]
    if failure=='source_sha':expected='0'*64
    if failure=='dso_sha':additions=[module.AddDso(a,'/lib/new.so','0'*64)]
    if failure=='capacity':
        a=dso(tmp_path,'large.so',4<<20);additions=[module.AddDso(a,'/lib/new.so',sha(a))]
    if failure=='metadata':
        with image.open('r+b') as f:f.seek(1036);f.write(struct.pack('<I',1))
        before=sha(image);expected=before
    with pytest.raises((ValueError,OSError)):
        module.derive_usr_image(image,out,additions,expected)
    assert not out.exists() and sha(image)==before

def test_rejects_existing_or_linked_output_and_non_dso(image,tmp_path):
    a=dso(tmp_path);before=sha(image);out=tmp_path/'existing.ext2';out.write_bytes(b'keep')
    with pytest.raises(ValueError):module.derive_usr_image(image,out,[module.AddDso(a,'/lib/new.so',sha(a))],before)
    assert out.read_bytes()==b'keep'
    link=tmp_path/'link.ext2';link.symlink_to(image)
    with pytest.raises(ValueError):module.derive_usr_image(image,link,[module.AddDso(a,'/lib/new.so',sha(a))],before)
    bad=tmp_path/'text.so';bad.write_bytes(b'not a DSO'*20)
    with pytest.raises(ValueError):module.derive_usr_image(image,tmp_path/'bad.ext2',[module.AddDso(bad,'/lib/new.so',sha(bad))],before)
    assert sha(image)==before and not (tmp_path/'bad.ext2').exists()

@pytest.mark.parametrize('fault',['no_write','old_payload_changed','old_indirect_changed'])
def test_independent_reader_rejects_success_exit_with_wrong_tree(image,tmp_path,monkeypatch,fault):
    a=dso(tmp_path);before=sha(image);out=tmp_path/'bad-writer.ext2'
    actual=module.subprocess.run
    def writer(command,**kwargs):
        if fault=='no_write':return subprocess.CompletedProcess(command,0,'claimed success','')
        result=actual(command,**kwargs)
        candidate=Path(command[-1]);audit=module.Audit(candidate)
        try:
            row=audit.inventory()['/lib/original.so'];pointer=struct.unpack_from('<I',row['raw'],40)[0]
            offset=pointer*audit.fs.block_size
            if fault=='old_indirect_changed':
                pointer=struct.unpack_from('<I',row['raw'],88)[0];assert pointer
                offset=(pointer+1)*audit.fs.block_size-1
        finally:audit.close()
        with candidate.open('r+b') as f:f.seek(offset);f.write(b'\x99')
        return result
    monkeypatch.setattr(module.subprocess,'run',writer)
    with pytest.raises(ValueError):
        module.derive_usr_image(image,out,[module.AddDso(a,'/lib/new.so',sha(a))],before)
    assert not out.exists() and sha(image)==before

def test_parent_directory_can_grow_without_changing_old_attributes(image,tmp_path):
    old=tmp_path/'small.bin';old.write_bytes(b'old')
    debug(image,f'write {old} /lib/'+('a'*240))
    check=module.Audit(image)
    try:size_before=check.inventory()['/lib']['size']
    finally:check.close()
    a=dso(tmp_path,size=128);items=[module.AddDso(a,'/lib/lib%d_'%i+'x'*87+'.so',sha(a)) for i in range(8)]
    out=tmp_path/'grown.ext2';module.derive_usr_image(image,out,items,sha(image))
    check=module.Audit(out)
    try:assert check.inventory()['/lib']['size']>size_before
    finally:check.close()
