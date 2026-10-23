"""固定元数据诊断策略；不包含密钥或账户凭据。"""
import hashlib
import re
import stat

TARGET = '2f94aea65af84dc6ab01a667752d283c'
NEUTRAL = b'\n' * 512
VERSION_SHA = '34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b'
PROBE_SHA = '610bbf754d77967ef0653b5d7b53bae38990749d2e9daad9e6f28990fdb35a17'
OLD_STATE = f'A7R5-ROOT-1 {TARGET} DONE 68 uid=0 euid=0 bytes=140\n'.encode()
RISK = ('本包仅诊断旧安装目录及host_ecdsa的元数据，不读取密钥内容、不修改密钥或账户、不启动SSH、不操作SD卡。'
        '允许两阶段认证/START，固定上传新probe和root执行库，临时写/etc/ld.so.preload并一次DEBUG；'
        '仅接受精确512换行基线，执行器先中和再运行探针；新文件、状态、输出及中和文件会持久残留。'
        '最多16次状态观察，每次间隔1秒，仅尚未生成结果0x10000006和RUNNING可继续观察；'
        '不重发认证、DEBUG或失败传输，不自动改写未知预加载。完成回执、完整输出、重复终态及中和全部通过才一次STOP。'
        '真实lstat失败或权限拒绝是诊断结果，不自动修复。异常可能停留服务态或留下预加载，恢复受限；'
        '不自动重试、切换端点、断电或清理，STOP后仅主机观察45秒并核对屏幕。')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_output(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 2048:
        raise ValueError('探针输出超限或为空')
    rows = raw.splitlines(keepends=True)
    if len(rows) != 4 or rows[0] != f'KEY109_BEGIN1 run={TARGET}\n'.encode() or rows[3] != (
            f'KEY109_END1 run={TARGET} samples=2 key_content_read=0 key_writes=0 ssh_started=0\n'.encode()):
        raise ValueError('输出会话、边界或行数不符')
    result = {}
    for label, row in zip(('install', 'private'), rows[1:3]):
        pattern = (rb'KEY109_META1 run=' + TARGET.encode() + b' label=' + label.encode() +
                   rb' rc=(-?\d{1,2}) errno=(\d{1,4}) valid=([01]) mode=([0-7]{1,7}) uid=(\d{1,10}) gid=(\d{1,10}) size=(-?\d{1,19}) private_policy=([01]) reject_mask=(\d{1,2})\n')
        match = re.fullmatch(pattern, row)
        if not match:
            raise ValueError('元数据格式错误')
        rc, error, valid = map(int, match.groups()[:3])
        mode = int(match[4], 8)
        uid, gid, size, private, mask = map(int, match.groups()[4:])
        if (rc not in (0, -1) or valid != (rc == 0) or not 0 <= error <= 4095
                or (valid and error != 0) or (not valid and error == 0)
                or uid > 0xffffffff or gid > 0xffffffff or mode > 0xffff or abs(size) > (1 << 63) - 1
                or private != (label == 'private')):
            raise ValueError('字段范围或有效性矛盾')
        if not valid and any((mode, uid, gid, size)):
            raise ValueError('查询失败不能携带有效属性')
        expected = (1 if not valid else (0 if stat.S_ISREG(mode) else 2) | (4 if uid else 0) | (8 if mode & 0o77 else 0)) if private else 0
        if mask != expected:
            raise ValueError('拒绝位与旧109门槛矛盾')
        result[label] = dict(rc=rc, errno=error, valid=bool(valid), mode_octal=oct(mode), uid=uid, gid=gid,
                             size=size, reject_mask=mask, old_private_policy_applies=bool(private))
    return dict(target_session=TARGET, metadata=result, key_content_read=False, ssh_started=False,
                historical_snapshot_proven=False, current_parent_view_only=True)
