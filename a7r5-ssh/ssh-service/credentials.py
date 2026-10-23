"""用户指定口令仅本机受限文件保留明文；命令行和日志不包含口令。"""
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess

HASH_PATTERN=r'\$6\$rounds=10000\$[A-Za-z0-9./]{16}\$[A-Za-z0-9./]{86}'


def valid_hash(value):
    return isinstance(value,str) and re.fullmatch(HASH_PATTERN,value) is not None


def validate_password(password):
    # 混合字符通过标准输入交给哈希程序，拒绝终止符和控制字符。
    if (not isinstance(password,str) or not 8 <= len(password) <= 128
            or any(ord(c)<32 or ord(c)==127 for c in password)
            or len(password.encode('utf-8'))>512):
        raise ValueError('密码须为8至128个字符，不能包含控制字符')


def make_hash(password):
    validate_password(password)
    salt=''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./') for _ in range(16))
    result=subprocess.run(['/opt/homebrew/opt/openssl/bin/openssl','passwd','-6','-salt','rounds=10000$'+salt,'-stdin'],
                          input=password+'\n',text=True,capture_output=True,timeout=15)
    value=result.stdout.strip()
    if result.returncode or not valid_hash(value):raise ValueError('口令哈希生成失败，不输出敏感内容')
    return value


def load(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise PermissionError('拒绝链接口令文件')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077:raise PermissionError('口令必须为0600普通文件')
        raw=os.read(fd,11)
        if len(raw)!=9 or raw[-1:]!=b'\n' or not re.fullmatch(rb'[0-9]{8}\n',raw):raise ValueError('口令文件格式不符')
        return raw[:-1].decode('ascii')
    finally:os.close(fd)
