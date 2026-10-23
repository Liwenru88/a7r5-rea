"""固定会话与只读核验规则；不包含凭据或客体执行载荷。"""
import hashlib
import re

RUN = '2f94aea65af84dc6ab01a667752d283c'
PREFIX = '/tmp/jiritsu/a7r5-' + RUN
RAM = '/tmp_network/a7r5-ssh-' + RUN
FINAL = (f'A7R5_PRIVATE_RESULT {RUN} code=85 parent_unchanged=1 '
         'child_tree_reaped=1 child_terminal_seen=0 listener_absent=1\n').encode()
STATE = f'A7R5-ROOT-1 {RUN} DONE 68 uid=0 euid=0 bytes=140\n'.encode()
NEUTRAL = b'\n' * 512
HASHES = {
    '/version.txt': '34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b',
    '/etc/passwd': '4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398',
    '/etc/nsswitch.conf': '3cb6f73826acc6786500cbac5f7a6a6ce11c807621eaa67d3f0dcebbe556f929',
    '/etc/ssh/sshd_config': 'fdccb272a96cc8b100116c8142b60b2bfd200390895770d2f263d07921db195d',
}
READS = (
    ('version', '/version.txt', 4096),
    ('root-state', PREFIX + '.state', 512),
    ('root-output', PREFIX + '.output', 512),
    ('parent-before', RAM + '/result', 1024),
    ('preload-before', '/etc/ld.so.preload', 4096),
    ('child-result', RAM + '/child-result', 1024),
    ('diagnostic', RAM + '/diagnostic', 4096),
    ('passwd', '/etc/passwd', 8192),
    ('nsswitch', '/etc/nsswitch.conf', 2048),
    ('sshd-config', '/etc/ssh/sshd_config', 8192),
    ('tcp', '/proc/net/tcp', 32768),
    ('heartbeat', RAM + '/heartbeat', 512),
    ('parent-after', RAM + '/result', 1024),
    ('preload-after', '/etc/ld.so.preload', 4096),
)
RISK = ('仅本次同端口054c:0336的固定14次只读核验；原始响应头、端点与选择结果留存；'
        '父子清理、账户配置原件、2222无监听、ENDED心跳、重复终态和精确512换行全部通过才一次STOP。'
        '不认证、不START、不DEBUG、不写相机文件、不连接SSH、不操作SD卡；'
        '服务态产品名只记录，无失败现场完整接口指纹，沿用接口0/alt0首对bulk规则；'
        '异常立即停止，不换端点、不重试、不自动断电。普通身份或096f只观察主机元数据。'
        'STOP可能Pipe error或停在过渡身份；主机恢复和屏幕确认单独核验，固定文件残留不删除。')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def child_result(raw):
    match = re.fullmatch(rb'PRIVATE_RESULT code=(\d{1,3}) errno=(\d{1,4}) sshd_attempted=([01]) '
                         rb'listener_observed=([01]) children_reaped=1 private_account_changed=([01]) '
                         rb'local_banner_verified=([01])\n', raw)
    if not match:
        raise ValueError('子终态格式或后代回收不符')
    code, error, attempted, listener, account, banner = map(int, match.groups())
    known = {0, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112,
             114, 115, 116, 117, 120, 124}
    if code not in known or error > 4095 or not banner <= listener <= attempted <= account:
        raise ValueError('未知子错误或启动标记不一致')
    if code in {101, 102, 103, 104, 105, 106} and account != 0:
        raise ValueError('早期子错误与账户标记矛盾')
    if code not in {0, 101, 102, 103, 104, 105, 106} and account != 1:
        raise ValueError('后期子错误缺少私有账户标记')
    if code in {107, 109, 110, 111, 114, 124} and attempted:
        raise ValueError('尚未启动阶段出现已启动标记')
    if code in {112, 115, 116, 117, 120} and not attempted:
        raise ValueError('启动后错误缺少尝试标记')
    if code in {108, 115} and (listener or banner):
        raise ValueError('启动前管道或fork错误不应出现监听/banner')
    if code == 112 and not (listener and banner):
        raise ValueError('READY通知失败缺少已完成的监听/banner')
    if code == 0 and (error or not (attempted and listener and account and banner)):
        raise ValueError('成功子终态缺少完整启动证据')
    return dict(code=code, errno=error, sshd_attempted=attempted, listener_observed=listener,
                children_reaped=1, private_account_changed=account, local_banner_verified=banner,
                errno_is_immediate_call_evidence=False)


def diagnostic_unreadable_allowed(child):
    return (child['code'] in {101, 102, 103, 104, 105, 106, 107, 108, 109, 124}
            and not any(child[key] for key in ('sshd_attempted', 'listener_observed', 'local_banner_verified')))


def no_listener(raw):
    if not raw or len(raw) >= 32768 or not raw.endswith(b'\n'):
        raise ValueError('TCP表为空、截断或超限')
    rows = raw.splitlines()
    header = rows[0].split()
    if header[:4] != [b'sl', b'local_address', b'rem_address', b'st']:
        raise ValueError('TCP表头不符')
    for row in rows[1:]:
        fields = row.split()
        if (len(fields) < 10 or not re.fullmatch(rb'\d+:', fields[0])
                or not all(re.fullmatch(rb'[0-9A-Fa-f]{8}:[0-9A-Fa-f]{4}', item) for item in fields[1:3])
                or not re.fullmatch(rb'[0-9A-Fa-f]{2}', fields[3])):
            raise ValueError('TCP表项不完整')
        if int(fields[1][-4:], 16) == 2222 and int(fields[3], 16) == 10:
            raise ValueError('2222仍有IPv4监听，不STOP')
    return True
