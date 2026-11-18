"""图标块扩展的显式合成边界；不修改产品白名单或输入镜像。"""
from pathlib import Path
import hashlib
import importlib.util
import subprocess
import sys
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-dat-tool/a7r5dat/ext2read.py').exists())
sys.path.insert(0,str(ROOT/'a7r5-dat-tool'))
P=Path(__file__).resolve().parents[1]/'a7r5dat/ext2_image_append.py'
if not P.exists():P=ROOT/'a7r5-dat-tool/a7r5dat/ext2_image_append.py'
spec=importlib.util.spec_from_file_location('a7r5dat.ext2_image_append',P)
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
PATH='/share/app/image_00_23_IPSX.uxc'

@pytest.mark.parametrize('name,corrected,broken',[
 ('23','f54f991e79c68da5d4c62b2605403af9b427c2526169b32426064a5e8ee9ce59',
       '88604ca10d4f0d8194e30616033a883f7ab4be5eeba7c398b5421c12652e1cc8'),
 ('32','827a21b2d113436e2839baa5c2e3a9d9b03f422a13626ee37e25aadf35ae5667',
       'd99962342020febff22421cb44054fb8570576a1d0fb7691db04ebd10d961840')])
def test_product_binding_accepts_offset_repair_and_rejects_known_broken_image(name,corrected,broken):
    # 摘要来自原复杂记录240字节修复及同源像素核对，不从待测生成器取预期值。
    binding=m.AppendImagePatch._bindings[f'/share/app/image_00_{name}_IPSX.uxc']
    assert binding.target_sha256==corrected and binding.target_sha256!=broken

def sha(raw):return hashlib.sha256(raw).hexdigest()

def fixture(tmp_path, blocks):
    image=tmp_path/'base.ext2'
    with image.open('xb') as f:f.truncate(8<<20)
    mk=subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/mke2fs','-q','-t','ext2','-b','1024','-I','128',str(image)],capture_output=True,text=True)
    assert mk.returncode==0,mk.stderr
    expected=(b'original nonzero data! '*50000)[:blocks*1024-7]
    target=b'NEW!'+expected[4:]+b'new tail data!'*300
    source=tmp_path/'old.bin';source.write_bytes(expected)
    script=tmp_path/'seed.cmd';script.write_text(f'mkdir /share\nmkdir /share/app\nwrite {source} {PATH}\nwrite {source} /unrelated\n')
    db=subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/debugfs','-w','-f',str(script),str(image)],capture_output=True,text=True)
    assert db.returncode==0,db.stderr
    raw=image.read_bytes();fs=m.Patch(raw).fs;ino=fs.walk(PATH)
    class Synthetic(m.AppendImagePatch):
        # 仅测试数学边界，产品类仍绑定真实4.06的两个原inode/原SHA/新SHA。
        _bindings={PATH:m.ImageBinding(ino,len(expected),len(target),sha(expected),sha(target))}
    return raw,expected,target,Synthetic

@pytest.mark.parametrize('blocks',[12,268,524])
def test_tail_extension_preserves_inode_and_old_blocks_across_indirect_edges(tmp_path,blocks):
    raw,expected,target,Type=fixture(tmp_path,blocks);patch=Type(raw)
    ino=patch.fs.walk(PATH);before=patch.fs.inode_blocks(ino);other=patch.fs.read_inode(patch.fs.walk('/unrelated'))
    patch.replace(PATH,expected,target);result,report=patch.finish()
    assert raw!=result and patch.fs.walk(PATH)==ino and patch.fs.inode_blocks(ino)[:len(before)]==before
    assert patch.fs.read_inode(patch.fs.walk('/unrelated'))==other and report['filesystem_size_unchanged']
    out=tmp_path/'derived.ext2';out.write_bytes(result)
    fsck=subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck','-f','-n',str(out)],capture_output=True,text=True)
    assert fsck.returncode==0,fsck.stdout+fsck.stderr

def test_wrong_binding_and_allocation_failure_cannot_finish(tmp_path,monkeypatch):
    raw,expected,target,Type=fixture(tmp_path,268)
    actual=m.AppendImagePatch(raw)
    with pytest.raises(ValueError):actual.replace(PATH,expected,target)
    with pytest.raises(ValueError):actual.finish()
    patch=Type(raw);calls=0;allocate=patch.allocate
    def fail(group):
        nonlocal calls
        calls+=1
        if calls==2:raise ValueError('explicit allocation fault')
        return allocate(group)
    monkeypatch.setattr(patch,'allocate',fail)
    with pytest.raises(ValueError):patch.replace(PATH,expected,target)
    with pytest.raises(ValueError):patch.finish()
    assert patch.source==raw
