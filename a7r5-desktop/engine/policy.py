"""固定回执契约；不把文件服务错误当成不存在，不把READY当清理完成。"""
import base64
import hashlib
import re

BASELINE = b'\n' * 512


def ready(raw, run, seconds):
    pattern = (rb'A7R5_PRIVATE_READY '+run.encode()+rb' parent=(\d+) child=(\d+) uid=0 euid=0 ttl='+
               str(seconds).encode()+rb' parent_unchanged=1 private_account_changed=1 parent_ns=(mnt:\[\d+\]) '
               rb'child_ns=(mnt:\[\d+\]) host_public_sha=([0-9a-f]{64})\n')
    match = re.fullmatch(pattern, raw)
    if not match or min(int(match[1]), int(match[2])) <= 1 or match[1] == match[2] or match[3] == match[4]:
        raise ValueError('READY身份、寿命或视图不符')
    return dict(parent=int(match[1]), child=int(match[2]), parent_ns=match[3].decode(),
                child_ns=match[4].decode(), public_sha=match[5].decode())


def public_key(raw, expected_sha):
    if not re.fullmatch(rb'ecdsa-sha2-nistp256 [A-Za-z0-9+/=]+(?: [ -~]*)?\n', raw) or len(raw)>512:
        raise ValueError('主机公钥格式不符')
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('主机公钥摘要不符')
    data = base64.b64decode(raw.split()[1], validate=True)
    if len(data) != 104 or data[:23] != b'\x00\x00\x00\x13ecdsa-sha2-nistp256':
        raise ValueError('ECDSA主机公钥结构不符')
    return raw.split()[0]+b' '+raw.split()[1]


def heartbeat(raw, run, identity, seconds, *, allow_changes=False):
    pattern = (rb'A7R5_PRIVATE_ALIVE '+run.encode()+rb' parent='+str(identity['parent']).encode()+
               rb' child='+str(identity['child']).encode()+rb' ttl='+str(seconds).encode()+
               rb' elapsed_ms=(\d+) parent_unchanged=([01]) changes_observed=([01])\n')
    match = re.fullmatch(pattern,raw)
    if not match or (not allow_changes and match.group(2,3)!=(b'1',b'0')) or match.group(2,3)==(b'0',b'0'):
        raise ValueError('启动心跳、原件或实例身份不符')
    return int(match[1])


def terminal(raw, child, run):
    match = re.fullmatch(rb'A7R5_PRIVATE_RESULT '+run.encode()+rb' code=0 parent_unchanged=([01]) '
                         rb'child_tree_reaped=1 child_terminal_seen=1 listener_absent=1 changes_observed=([01])\n',raw)
    if not match or (match[1] == b'0' and match[2] != b'1'):
        raise ValueError('没有完整父监督器清理终态')
    if not re.fullmatch(rb'PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 '
                        rb'children_reaped=1 private_account_changed=1 local_banner_verified=1\n', child):
        raise ValueError('没有完整私有子视图清理终态')
    return dict(originals_unchanged=match[1] == b'1', changes_observed=match[2] == b'1')
