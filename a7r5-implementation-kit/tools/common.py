"""材料包通用操作；所有准备动作仅处理普通本机文件。"""
from pathlib import Path
import hashlib
import json
import os
import re
import sys

BASE = Path(__file__).resolve().parents[1]
ENGINE = BASE / 'engine'
sys.path[:0] = [str(ENGINE / 'libs'), str(ENGINE / 'mac')]


def sha(path):
    digest = hashlib.sha256()
    with regular(path).open('rb') as handle:
        while block := handle.read(8 << 20):
            digest.update(block)
    return digest.hexdigest()


def safe(path):
    path = Path(path).absolute()
    if path.is_relative_to('/dev') or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('仅接受不经过符号链接的本机路径')
    return path


def regular(path):
    import stat
    path = safe(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('仅接受普通文件')
    return path


def save(path, value):
    path = safe(path)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def fresh(path):
    path = safe(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def resource_hashes():
    resources = [BASE / 'kit.py', *sorted((BASE / 'tools').glob('*.py')),
                 *sorted((BASE / 'payload').glob('*.c')),
                 *sorted((BASE / 'profiles').glob('*.json')),
                 *sorted((BASE / 'profiles').glob('*.bin')),
                 BASE / 'historical/expected-inventory.json']
    resources += [p for p in (BASE / 'engine').rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return {str(p.relative_to(BASE)): sha(p) for p in resources}


def seal(directory, value):
    directory = safe(directory)
    value['schema'] = 'a7r5-implementation-operation-1'
    value['material_root'] = str(BASE)
    value['output'] = str(directory / 'result')
    value['resources'] = resource_hashes()
    from system_dump.usb_adapter import LIBUSB
    from system_dump.images import E2FS
    paths = [Path(sys.executable).resolve(), LIBUSB.resolve(), (E2FS / 'debugfs').resolve()]
    value['runtime'] = {str(p): sha(p) for p in paths}
    value['artifacts'] = {str(p.relative_to(directory)): sha(p)
                          for p in directory.rglob('*') if p.is_file()}
    save(directory / 'operation.json', value)
    save(directory / 'approval-template.json', {
        'schema': 'a7r5-implementation-approval-1', 'operation_sha256': sha(directory / 'operation.json'),
        'run_id': value['run_id'], 'kind': value['kind'], 'accepted': False,
        'risk_statement': value['risk_statement']})
    return value


def load(directory):
    directory = safe(directory)
    value = json.loads(regular(directory / 'operation.json').read_bytes())
    if (value.get('schema') != 'a7r5-implementation-operation-1' or value['material_root'] != str(BASE)
            or value['kind'] not in ('dump', 'root', 'collect')
            or not re.fullmatch('[0-9a-f]{32}', value['run_id'])
            or value['output'] != str(directory / 'result')):
        raise ValueError('操作类型、会话、材料目录或输出不符；移动材料后须重新准备')
    if value['resources'] != resource_hashes():
        raise ValueError('材料变化；停止并重新离线准备，不复用批准')
    for name, digest in value['runtime'].items():
        if sha(name) != digest:
            raise ValueError('外部运行依赖变化：' + name)
    for name, digest in value['artifacts'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(directory / name) != digest:
            raise ValueError('本次固定材料变化：' + name)
    if value['kind'] in ('dump', 'collect'):
        from .profiles import inventory, project
        expected = inventory(value.get('dump_profile'))
        if (value.get('image_count') != len(expected['partitions'])
                or value.get('image_bytes') != expected['total_bytes']):
            raise ValueError('操作模式、数量或字节范围不符')
        if value['kind'] == 'collect':
            binding = json.loads(regular(directory / 'binding.json').read_bytes())
            if (binding.get('dump_profile') != value['dump_profile']
                    or project(binding['inventory']) != project(expected)):
                raise ValueError('采集绑定与操作模式不符')
    return value


def consent_phrase(directory):
    return 'ACCEPT-' + sha(safe(directory) / 'operation.json')[:16]


def approve(directory, phrase):
    directory = safe(directory)
    value = load(directory)
    if phrase != consent_phrase(directory):
        raise PermissionError('必须逐次确认该操作摘要对应的风险接受短语')
    if (directory / 'ATTEMPT_LOCK').exists() or (directory / 'result').exists():
        raise FileExistsError('该操作已经尝试，不得重新批准或删除锁重跑')
    approval = json.loads((directory / 'approval-template.json').read_bytes())
    approval['accepted'] = True
    save(directory / 'approval.json', approval)
    return {'approved': True, 'kind': value['kind'], 'run_id': value['run_id']}


def checked_approval(directory):
    directory = safe(directory)
    # 缺少批准时，在资源加载和任何主机元数据查询之前拒绝。
    path = directory / 'approval.json'
    if not path.is_file() or path.is_symlink():
        raise PermissionError('没有本次明确批准；不观察设备、不发送相机请求')
    value = load(directory)
    actual = json.loads(regular(path).read_bytes())
    expected = json.loads(regular(directory / 'approval-template.json').read_bytes())
    expected['accepted'] = True
    if (actual != expected or actual['operation_sha256'] != sha(directory / 'operation.json')
            or actual['run_id'] != value['run_id'] or actual['kind'] != value['kind']):
        raise PermissionError('批准未绑定本次材料')
    if (directory / 'ATTEMPT_LOCK').exists() or (directory / 'result').exists():
        raise FileExistsError('已有尝试锁或输出，禁止重试')
    return value


def execute(directory):
    directory = safe(directory)
    value = checked_approval(directory)
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise PermissionError('实机入口须在macOS Terminal内由本机sudo启动')
    (directory / 'ATTEMPT_LOCK').mkdir(mode=0o700)
    owner = directory.stat()
    try:
        if value['kind'] == 'dump':
            from .workflows import run_dump
            return run_dump(directory, value)
        if value['kind'] == 'root':
            from .root import execute_root
            return execute_root(directory, value)
        from .selective import capture
        return capture(directory, value)
    finally:
        # 只归还本次输出，不递归改动材料包、原镜像或任何外部目录。
        output = directory / 'result'
        items = [directory / 'ATTEMPT_LOCK']
        if output.exists():
            items += [output, *output.rglob('*')]
        for path in items:
            if path.is_symlink():
                raise ValueError('输出出现链接，停止修改归属')
            os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
