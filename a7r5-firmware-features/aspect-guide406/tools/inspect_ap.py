"""只读检查固定 AP 的补丁前像；不生成修改后的 AP 或升级包。"""
import argparse
import hashlib
import json
from pathlib import Path
import stat

AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
AP_BYTES = 97368304
HERE = Path(__file__).resolve().parents[1]


def verify_bytes(raw, plan):
    if len(raw) != AP_BYTES or hashlib.sha256(raw).hexdigest() != AP_SHA:
        raise ValueError('AP 完整摘要或长度不符，不能应用当前研究落点')
    if (plan['schema'], plan['baseline']['AP_sha256']) != ('a7r5-aspect-guide406-patch-plan/1', AP_SHA):
        raise ValueError('补丁清单身份不符')
    windows = sorted(plan['file_preimages'], key=lambda row: row['file_offset'])
    end = 0
    for row in windows:
        at = row['file_offset']; expected = bytes.fromhex(row['before_hex'])
        if not expected or at < end or at+len(expected) > len(raw):
            raise ValueError('前像窗口重叠或越界')
        if raw[at:at+len(expected)] != expected:
            raise ValueError('补丁前像不符：'+row['id'])
        end = at+len(expected)
    if len(plan['support_writes']) != 28 or len(plan['registrations']) != 3:
        raise ValueError('支持位或登记数量不完整')
    return {'status': 'baseline-and-preimages-verified', 'AP_sha256': AP_SHA,
            'file_preimages_checked': len(windows), 'support_writes_planned': 28,
            'registrations_planned': 3, 'modified_AP_written': False,
            'installable_firmware_created': False, 'camera_io': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap', required=True, type=Path)
    parser.add_argument('--plan', type=Path, default=HERE/'patch-plan.json')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    path = args.ap.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('只接受没有符号链接的普通 AP 文件')
    if any(path.is_relative_to(p) for p in (Path('/dev'),Path('/Volumes'),Path('/proc'),Path('/sys'))):
        raise ValueError('不读取设备、挂载介质或系统伪文件')
    result = verify_bytes(path.read_bytes(), json.loads(args.plan.read_text()))
    if args.receipt:
        with args.receipt.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
