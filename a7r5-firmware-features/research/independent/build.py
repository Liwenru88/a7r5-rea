"""从锁定的 DAT 和单项归档增量复现离线升级包。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAT_TOOL = ROOT / 'a7r5-dat-tool'
sys.path[:0] = [str(DAT_TOOL), str(ROOT / 'a7r5-desktop/engine')]

from a7r5dat import tool
from a7r5dat.codec import digest, verify_signature
from component_recipe import path_in
from native24_preset import apply_delta


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text())


def build(profile, source, output):
    folder = HERE / 'profiles' / profile
    spec = read_json(folder / 'resources.json')
    require(spec['schema'] == 1 and spec['profile'] == profile
            and spec['base_public_key'] in ('sony-original-public.pem', 'research-public.pem'),
            '功能清单身份不符')
    source = source.absolute()
    output = output.absolute()
    local = ROOT / '.local'
    require(output.resolve().is_relative_to(local) and output != local
            and not output.exists() and output.parent.is_dir()
            and not any(p.is_symlink() for p in (output, *output.parents)),
            '输出必须是 .local 下的新目录')
    require(source.is_file() and not source.is_symlink() and digest(source) == spec['base_sha256'],
            '输入 DAT SHA-256 与功能清单不符')
    keys = DAT_TOOL / 'keys'
    research_public = keys / 'research-public.pem'
    records = spec['deltas']
    assets = {}
    for row in records:
        resource = path_in(folder, row['delta'])
        require(digest(resource) == row['delta_sha256'], '增量资源摘要不符')
        assets[row['path']] = resource
    require(len(assets) == len(records), '归档成员重复')
    companion = spec.get('companion')
    if companion:
        recipe = path_in(folder, companion['file'])
        require(digest(recipe) == companion['sha256'], '配方文件摘要不符')

    with tempfile.TemporaryDirectory(prefix='.feature-build-', dir=output.parent) as scratch:
        temporary = Path(scratch)
        workspace = temporary / 'workspace'
        tool.unpack(source, workspace, keys / spec['base_public_key'])
        before = read_json(workspace / 'manifest.json')
        for row in records:
            apply_delta(path_in(workspace / 'archive', row['path']), assets[row['path']], row)

        candidate = temporary / 'BODYDATA.DAT'
        packed = tool.pack(workspace, candidate, spec['version'],
                           keys / 'research-signing-private.pem', research_public)
        require(packed['sha256'] == spec['expected_dat_sha256'], '复现 DAT 摘要不符')
        readback = temporary / 'readback'
        tool.unpack(candidate, readback, research_public)
        after = read_json(readback / 'manifest.json')
        changes = {}
        for left, right in zip(before['entries'], after['entries'], strict=True):
            require({k: v for k, v in left.items() if k not in ('sha256', 'crc32')}
                    == {k: v for k, v in right.items() if k not in ('sha256', 'crc32')},
                    '归档布局变化')
            if left != right:
                changes[right['name']] = right['sha256']
        require(changes == spec['expected_changes'], '独立回读的成员变化超出功能清单')
        require(after['updater_sha256'] == before['updater_sha256'], '更新器内容变化')
        _, signed, signature = verify_signature(candidate, research_public.read_bytes())
        (temporary / 'signed.sha256.bin').write_bytes(signed.digest())
        (temporary / 'signature.bin').write_bytes(signature)
        subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(research_public),
                        '-sigfile', str(temporary / 'signature.bin'), '-in',
                        str(temporary / 'signed.sha256.bin'), '-pkeyopt', 'digest:sha256'],
                       check=True, capture_output=True)
        receipt = {
            'profile': profile, 'version': spec['version'], 'base_sha256': spec['base_sha256'],
            'dat_sha256': packed['sha256'], 'archive_entries': len(after['entries']),
            'frames': after['decryption']['frame_count'], 'changed_members': changes,
            'independent_unpack': True, 'openssl_signature_verified': True,
            'camera_io': False, 'device_acceptance_verified': False,
        }
        output.mkdir(mode=0o700)
        if companion:
            shutil.copyfile(recipe, output / companion['file'])
        shutil.copyfile(research_public, output / research_public.name)
        (output / 'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        os.link(candidate, output / candidate.name)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main():
    profiles = sorted(p.parent.name for p in (HERE / 'profiles').glob('*/resources.json'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=profiles)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.profile, args.base, args.output)


if __name__ == '__main__':
    main()
