"""材料包的交互客户端；只有显式ssh/upload/download子命令才联网。"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent


def trusted_key(source):
    # 必须来自USB固定文件读取或其他独立可信通道；不能使用未认证的ssh-keyscan替代。
    raw=Path(source).read_text().strip().split()
    if len(raw)<2 or raw[0]!='ecdsa-sha2-nistp256' or not re.fullmatch('[A-Za-z0-9+/=]+',raw[1]):raise ValueError('主机公钥格式不符')
    blob=base64.b64decode(raw[1],validate=True)
    if not blob.startswith(b'\0\0\0\x13ecdsa-sha2-nistp256'):raise ValueError('主机公钥类型不符')
    return raw[:2], 'SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def main():
    parser=argparse.ArgumentParser(description='默认无联网；密码仅由系统SSH提示输入')
    parser.add_argument('action',choices=['bind-host-key','ssh','upload','download'])
    parser.add_argument('paths',nargs='*');parser.add_argument('--ip',default='10.10.10.177')
    args=parser.parse_args();ip=ipaddress.IPv4Address(args.ip)
    if not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:raise ValueError('仅接受明确的局域网单地址')
    operation=json.loads((ROOT/'manifest.json').read_text())
    alias='a7r5-'+operation['run_id'];hosts=ROOT/'known_hosts'
    if args.action=='bind-host-key':
        if len(args.paths)!=1:parser.error('提供本会话USB可信回读的host-public-key文件')
        key,fingerprint=trusted_key(args.paths[0])
        fd=os.open(hosts,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(alias+' '+' '.join(key)+'\n')
        print('已绑定独立可信主机公钥：'+fingerprint);return
    if not hosts.is_file() or hosts.is_symlink():raise ValueError('先使用独立可信回读公钥执行bind-host-key；缺失时拒绝联网')
    common=['-F','/dev/null','-o','HostKeyAlias='+alias,'-o','UserKnownHostsFile='+str(hosts),'-o','GlobalKnownHostsFile=/dev/null','-o','StrictHostKeyChecking=yes',
            '-o','IdentityAgent=none','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=10']
    if args.action=='ssh':
        if args.paths:parser.error('交互SSH不接受额外固定命令参数')
        command=['/usr/bin/ssh',*common,'-tt','-p','2222','root@'+str(ip)]
    else:
        if len(args.paths)!=2:parser.error('传输需两个路径：本地和远端；download时先远端后本地')
        remote_index=1 if args.action=='upload' else 0
        remote=args.paths[remote_index]
        if not remote.startswith('/') or '\n' in remote or '\r' in remote:raise ValueError('远端路径须为绝对路径')
        arguments=list(args.paths);arguments[remote_index]='root@'+str(ip)+':'+remote
        local=1-remote_index;arguments[local]=str(Path(arguments[local]).absolute())
        command=['/usr/bin/scp',*common,'-P','2222',*arguments]
    # 不自动重试，不嵌入口令，不强制固定命令。
    raise SystemExit(subprocess.call(command))


if __name__=='__main__':main()
