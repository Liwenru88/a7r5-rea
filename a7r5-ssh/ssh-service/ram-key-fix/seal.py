"""冻结包内材料与本机依赖；只生成accepted=false模板。"""
import json
from pathlib import Path
import sys
import policy
import runner


def seal():
    root = Path(__file__).resolve().parent
    if (root / 'approval.json').exists() or (root / 'ATTEMPT_LOCK').exists() or (root / 'result').exists():
        raise ValueError('已有批准或执行记录，不再封包')
    usb = Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()
    python = Path(sys.executable).resolve()
    baseline_file = root / 'proof/device/final-acceptance.json'
    final = json.loads(baseline_file.read_text())
    if not final['host_recovery_verified'] or not final['screen_normal']:
        raise ValueError('历史恢复证据不完整')
    baseline = dict(location_id=1048576, model='ILCE-7RM5', pid=3594,
                    media=[[False,67108352],[False,8589934592],[False,118286712832],[True,67108864],[True,126877696000]],
                    drivers=['IOUSBMassStorageDriver','IOUSBMassStorageDriverNub','IOUSBMassStorageInterfaceNub'])
    openssl=Path('/opt/homebrew/opt/openssl/bin/openssl').resolve()
    credential=root.parents[2]/'fixed-password-input'
    manifest = dict(policy=runner.metadata(), directory=str(root), libusb=str(usb),openssl=str(openssl),credential_path=str(credential),run_id=json.loads((root/'config.json').read_text())['run_id'],target_ip='10.10.10.177',host_baseline=baseline,
                    dependencies={str(p): policy.digest(p.read_bytes()) for p in (usb,python,openssl,Path('/usr/bin/ssh'),Path('/usr/bin/scp'))}, files={})
    excluded = {'operation.json','approval-template.json','checksums.sha256'}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('拒绝链接材料')
        if path.is_file() and path.name not in excluded:
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                raise ValueError('不得打包构建缓存')
            raw = path.read_bytes()
            manifest['files'][str(path.relative_to(root))] = dict(bytes=len(raw), sha256=policy.digest(raw))
            path.chmod(0o700 if path.name.endswith('.command') else 0o600)
    runner.save(root / 'operation.json', manifest)
    runner.save(root / 'approval-template.json', dict(accepted=False, operation_sha256=policy.digest(
        (root / 'operation.json').read_bytes()), risk=policy.RISK))
    runner.check(False)
    (root / 'checksums.sha256').write_text(''.join(policy.digest(p.read_bytes()) + '  ' + str(p.relative_to(root)) + '\n'
        for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'checksums.sha256'))
    print(json.dumps(dict(package=str(root), files=len(manifest['files']), operation_sha256=policy.digest(
        (root / 'operation.json').read_bytes()), approval_created=False), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    seal()
