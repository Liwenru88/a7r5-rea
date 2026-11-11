"""将第三轮清理归档中的普通文件恢复到全新的临时目录，禁止覆盖现有内容。"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def restore(archive, prefix, destination=None):
    prefix_path = PurePosixPath(prefix)
    if prefix_path.is_absolute() or '..' in prefix_path.parts or not prefix_path.parts:
        raise ValueError('前缀必须是工程内的相对路径')
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('manifest.json'))
        assert manifest['schema'] == 'r5-cleanup-evidence/2'
        selected = [row for row in manifest['rows'] if row['disposition'] == 'archived-by-content-hash'
                    and (row['path'] == prefix or row['path'].startswith(prefix.rstrip('/') + '/'))]
        if not selected:
            raise ValueError('前缀下没有可恢复的普通文件；旧 CPIO 仅记录摘要')
        for row in selected:
            path = PurePosixPath(row['path'])
            if path.is_absolute() or '..' in path.parts or not stat.S_ISREG(row['mode']):
                raise ValueError('归档路径或类型不合法')
            h = row['sha256']
            assert len(h) == 64 and all(c in '0123456789abcdef' for c in h)
            assert z.getinfo('objects/' + h).file_size == row['bytes']
        if destination is not None:
            destination = Path(destination)
            if destination.exists() or destination.is_symlink():
                raise ValueError('目标必须是不存在的新目录，禁止覆盖原工程')
            destination.mkdir(parents=True, exist_ok=False)
            for row in selected:
                output = destination / row['path']
                output.parent.mkdir(parents=True, exist_ok=True)
                hasher = hashlib.sha256()
                with z.open('objects/' + row['sha256']) as source, output.open('xb') as target:
                    while chunk := source.read(1 << 20):
                        target.write(chunk)
                        hasher.update(chunk)
                assert hasher.hexdigest() == row['sha256'], row['path']
                os.chmod(output, stat.S_IMODE(row['mode']))
        return dict(files=len(selected), bytes=sum(row['bytes'] for row in selected),
                    extracted=destination is not None, prefix=prefix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--dest', type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent / 'execution-03-deep'
    archive = base / 'retained-evidence.zip'
    expected = json.loads((base / 'prepared.json').read_text())['archive']['sha256']
    assert digest(archive) == expected, '归档摘要不符，停止恢复'
    print(json.dumps(restore(archive, args.prefix, args.dest), ensure_ascii=False))


if __name__ == '__main__':
    main()
