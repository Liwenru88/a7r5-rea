"""冻结新包；只生成未批准模板，不调用设备入口。"""
import json
from pathlib import Path
import sys
import runner

HERE = Path(__file__).resolve().parent


def main():
    if any((HERE/name).exists() for name in ('approval.json','ATTEMPT_LOCK','result','operation.json')):
        raise ValueError('不覆盖封存或执行记录')
    work = next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
    config = json.loads((HERE/'config.json').read_text())
    usb = Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()
    dependencies = [Path(sys.executable).resolve(),usb,Path('/usr/bin/ssh')]
    manifest = dict(directory=str(HERE),risk=runner.RISK,run_id=config['run_id'],service_run=config['service_run'],
                    target_ip='10.10.10.177',port=2222,public_sha256=config['public_sha256'],libusb=str(usb),
                    credential_path=str(work/'a7r5-ssh/ssh-service/fixed-password-input'),
                    dependencies={str(p):runner.digest(p) for p in dependencies},files={},
                    host_baseline=dict(location_id=1048576,model='ILCE-7RM5',pid=3594,
                    media=[[False,67108352],[False,8589934592],[False,118286712832],[True,67108864],[True,126877696000]],
                    drivers=['IOUSBMassStorageDriver','IOUSBMassStorageDriverNub','IOUSBMassStorageInterfaceNub']),
                    maximums=dict(payload_uploads=1,host_preload_writes=1,debug=1,stop=1,post_usb_ssh_connections=1),
                    old_packages_preserved=True,autostart_repaired=False)
    excluded = {'approval-template.json','checksums.sha256'}
    for path in sorted(HERE.rglob('*')):
        if path.is_symlink():
            raise ValueError('包内含链接')
        if path.is_file() and path.name not in excluded:
            if path.suffix == '.pyc' or '__pycache__' in path.parts:
                raise ValueError('包内含缓存')
            manifest['files'][str(path.relative_to(HERE))] = runner.digest(path)
            path.chmod(0o700 if path.name.endswith('.command') else 0o600)
    runner.save(HERE/'operation.json',manifest)
    runner.save(HERE/'approval-template.json',dict(accepted=False,operation_sha256=runner.digest(HERE/'operation.json'),risk=runner.RISK))
    runner.check(False)
    (HERE/'checksums.sha256').write_text(''.join(runner.digest(p)+'  '+str(p.relative_to(HERE))+'\n'
        for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'checksums.sha256'))
    print(json.dumps(dict(package=str(HERE),operation_sha256=runner.digest(HERE/'operation.json'),camera_io=False,approval_created=False),ensure_ascii=False))


if __name__ == '__main__':
    main()
