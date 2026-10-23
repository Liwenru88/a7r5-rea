"""私有RAM密钥修复包的固定验收与执行范围。"""
import hashlib
import re
import stat

PREDECESSOR='c3c32712333d4e9db5598f79df2be599'
NEUTRAL=b'\n'*512
RISK=('一次固定安装、两阶段认证/START及一次DEBUG；只接受精确512换行预加载基线。'
      '在新持久安装目录生成主机密钥，私有子视图仅在tmpfs内创建0600副本并核验后交给sshd。'
      '原账户不改；私有RAM账户副本允许root口令登录和完整终端，0.0.0.0:2222无TTL后台运行；'
      '自启钩子材料保留为禁用候选，不写enabled标记、不留永久预加载、不重启。'
      '固定安装/密钥/中和文件残留；固定口令、root终端误写、无TTL监听与失败恢复受限风险。'
      '成功安装需root终态、RAM密钥回执、监听、主机公钥、前进心跳、重复状态及中和全部通过才一次STOP。'
      'USB和完整媒体恢复通过后，仅对10.10.10.177进行一次PTY和两次默认SCP，测试仅写RAM的65536字节文件。'
      '协议或传输失败立即停止；已回收的载荷DONE失败仅补读hostkey-copy、child-result、diagnostic各一次后停止。'
      '不重试、换端点、自动断电、自动清理或第二次回收；不操作SD卡内容、不格式化。')


def digest(raw): return hashlib.sha256(raw).hexdigest()


def hostkey_receipt(raw,run):
    pattern=(rb'A7R5_RAM_HOSTKEY1 '+run.encode()+
             rb' stage=0 errno=0 verified=1 source_mode=([0-7]{1,7}) source_uid=0 source_gid=(\d{1,10}) source_bytes=(\d{1,5})'
             rb' dest_mode=100600 dest_uid=0 dest_gid=(\d{1,10}) dest_bytes=(\d{1,5}) dest_tmpfs=1 source_unchanged=1 partial_removed=0 private_key_logged=0\n')
    match=re.fullmatch(pattern,raw)
    if not match: raise ValueError('私有RAM密钥复制回执不符')
    mode=int(match[1],8);source_size=int(match[3]);dest_size=int(match[5])
    if (not stat.S_ISREG(mode) or mode&0o22 or not 0<source_size<=8192 or dest_size!=source_size
            or int(match[2])>0xffffffff or int(match[4])>0xffffffff):
        raise ValueError('源密钥或RAM副本元数据不符')
    return dict(source_mode=oct(mode),destination_mode='0o100600',bytes=source_size,
                source_content_and_permissions_unchanged=True,destination_tmpfs=True,private_key_logged=False)


def ready(raw,run):
    match=re.fullmatch(rb'A7R5_PRIVATE_READY '+run.encode()+rb' parent=(\d+) child=(\d+) uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=(mnt:\[\d+\]) child_ns=(mnt:\[\d+\]) host_public_sha=([0-9a-f]{64})\n',raw)
    if not match or min(int(match[1]),int(match[2]))<=1 or match[1]==match[2] or match[3]==match[4]:
        raise ValueError('READY身份或隔离回执不符')
    return dict(parent=int(match[1]),child=int(match[2]),public_sha=match[5].decode())


def heartbeat(raw,run,identity):
    match=re.fullmatch(rb'A7R5_PRIVATE_ALIVE '+run.encode()+rb' parent=(\d+) child=(\d+) ttl=0 elapsed_ms=(\d{1,6}) parent_unchanged=1\n',raw)
    if (not match or (int(match[1]),int(match[2]))!=(identity['parent'],identity['child'])
            or int(match[3])>90000): raise ValueError('首次心跳身份或时间不符')
    return int(match[3])
