"""核对研究包完整性，可创建并读回校验一个全新的 ZIP；不启动模拟器。"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def verify(root):
    root = root.resolve()
    wanted = {}
    for line in (root/'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ',1)
        parts = PurePosixPath(name)
        if (len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected)
                or parts.is_absolute() or '..' in parts.parts or name in wanted or name=='SHA256SUMS'):
            raise ValueError('非法或重复的校验清单条目')
        wanted[name] = expected
    actual = {}
    for path in root.rglob('*'):
        if path.is_symlink(): raise ValueError('研究包不接受符号链接')
        if path.is_file() and path.name != 'SHA256SUMS': actual[path.relative_to(root).as_posix()] = path
    if set(wanted)!=set(actual): raise ValueError('研究包存在缺失或额外文件')
    for name, expected in wanted.items():
        if digest(actual[name])!=expected: raise ValueError('摘要不符：'+name)
    manifest = json.loads((root/'manifest.json').read_text())
    if (manifest['schema'],manifest['acceptance']['device_tested'],manifest['installable_firmware']) != (
            'a7r5-aspect-guide406-research/1',False,False):
        raise ValueError('研究包身份或验收范围不符')
    return wanted


def archive(root, target, wanted):
    target = target.absolute()
    if target.is_relative_to(root) or not target.parent.is_dir() or target.exists() or target.is_symlink():
        raise ValueError('ZIP 必须写到包外的全新普通文件')
    checksum = Path(str(target)+'.sha256')
    if checksum.exists() or checksum.is_symlink(): raise ValueError('ZIP 校验文件已存在')
    names = sorted([*wanted,'SHA256SUMS'])
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as out:
        for name in names:
            info = zipfile.ZipInfo(root.name+'/'+name,date_time=(2026,10,26,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            out.writestr(info,(root/name).read_bytes())
    with zipfile.ZipFile(target) as packed:
        if packed.testzip() is not None or packed.namelist()!=[root.name+'/'+n for n in names]:
            raise ValueError('ZIP 成员或 CRC 校验不符')
        for name in names:
            if hashlib.sha256(packed.read(root.name+'/'+name)).hexdigest()!=digest(root/name):
                raise ValueError('ZIP 读回摘要不符：'+name)
    value = digest(target)
    with checksum.open('x') as stream: stream.write(value+'  '+target.name+'\n')
    return {'path':str(target),'bytes':target.stat().st_size,'sha256':value,'readback_verified':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--archive',type=Path)
    args = parser.parse_args();root = args.root.absolute();wanted = verify(root)
    result = {'status':'research-bundle-verified','files_checked':len(wanted),'camera_io':False,
              'installable_firmware':False}
    if args.archive: result['archive'] = archive(root,args.archive,wanted)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
