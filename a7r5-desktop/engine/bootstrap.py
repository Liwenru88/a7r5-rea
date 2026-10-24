"""仅从应用内隔离解释器启动；命令均为固定动作，不接受脚本或任意命令。"""
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT/'site'), str(ROOT/'vendor/pmca_source')]
from common import load, save, sha


def selfcheck():
    from Cryptodome.PublicKey import RSA
    from cryptography.hazmat.primitives import serialization
    import numpy
    import usb
    from pmca.usb.sony import SonySenserAuthDevice
    from a7r5dat import tool
    import ctypes
    ctypes.CDLL(str(ROOT/'lib/libusb-1.0.dylib'))
    private = RSA.import_key((ROOT/'keys/research-signing-private.pem').read_bytes())
    public = RSA.import_key((ROOT/'keys/research-public.pem').read_bytes())
    if private.public_key().export_key() != public.export_key():raise ValueError('签名密钥不配对')
    from common import render_template
    manifest = load(ROOT/'templates.json')
    for name in manifest['files']:
        render_template(name, '0123456789abcdef0123456789abcdef', manifest['hash_marker'])
    return dict(ok=True, python=sys.version.split()[0], numpy=numpy.__version__, key_pair_verified=True,
                templates_verified=True, authentication_module_imported=True, usb_library_loaded=True, USB_enumerated=False,
                camera_IO=False, qemu_required=False)


def execute(action, request, job):
    job = Path(job)
    if action == 'firmware':
        import firmware
        return firmware.build(request, job)
    if action == 'device':
        import device
        try:
            result = device.run(request, job)
        except Exception as error:
            started = (job/'ATTEMPT_LOCK').exists()
            result = dict(kind=request['kind'], error=str(error), task_complete=False,
                          device_IO=started, can_replug=not started, automatic_retry=False)
        save(job/'result.json', result)
        return result
    if action == 'recovery':
        import host
        from policy import pre_service_failure
        previous = request['previous']
        if previous.get('task_complete') is not True and not pre_service_failure(previous):
            raise ValueError('服务已启动或阶段证据不全，禁止按普通恢复流程重试')
        # 跨次检查重新识别唯一A7R5，不把上次端口、媒体或驱动当作本次基线。
        current = host.snapshot(job, 'current')
        if current.get('kind') != 'ordinary' or current.get('model') != 'ILCE-7RM5' or not current.get('media') or not current.get('drivers'):
            raise ValueError('当前未识别到A7R5的MSC连接，请在相机上选择MSC')
        proof = host.observe(current, lambda label, timeout=5:host.snapshot(job, label, timeout, current['location_id']))
        return dict(previous, USB_recovered=proof['recovered'], recovery_baseline=current, host_recovery=proof)
    raise ValueError('不支持的动作')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        if sys.argv[1:] == ['selfcheck']:
            result = selfcheck()
        elif len(sys.argv) == 4 and sys.argv[1] in ('firmware', 'device', 'recovery'):
            request = load(sys.argv[2]);result = execute(sys.argv[1], request, sys.argv[3])
        else:raise ValueError('命令格式无效')
        print(json.dumps(dict(result=result), ensure_ascii=False), flush=True)
    except Exception as error:
        print(json.dumps(dict(error=str(error)), ensure_ascii=False), flush=True)
        sys.exit(1)
