"""生成固定RAM来源门槛；仅使用已记录的BusyBox applet和shell内建。"""
import json
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parent
SOURCE = '/var/run/a7r5-ssh-5e551f1a97774fa1885f15799583d09b'


def binding():
    value = json.loads((ROOT / 'key-source-audit-20261021-02/result.json').read_text())
    if value.get('passed') is not True or value.get('private_key_content_read') is not False:
        raise ValueError('没有本次只读来源证据')
    e = value['evidence']; c = e['configurations'][0]
    p = next(row for row in e['ancestors'] if row['pid'] == c['pid'])
    key = e['keys'][0]['before']
    if key != e['keys'][0]['after'] or key['path'] != SOURCE + '/host_ecdsa' or key['mode'] != '0o100600' or key['uid'] or key['gid'] or key['bytes'] != 505:
        raise ValueError('RAM来源属性不符')
    return dict(pid=p['pid'], start_ticks=p['start_ticks'], mount_namespace=p['mount_namespace'],
                config=c['metadata']['path'], key=key['path'], bytes=key['bytes'])


def script(qemu_only=False):
    b = binding(); process = ''
    if not qemu_only:
        process = f'''
[ "$(/bin/busybox readlink /proc/{b['pid']}/exe)" = /usr/sbin/sshd ] || die source_process
[ "$(/bin/busybox readlink /proc/{b['pid']}/ns/mnt)" = {shlex.quote(b['mount_namespace'])} ] || die source_namespace
line=$(/bin/busybox cat /proc/{b['pid']}/stat) || die source_start
line=${{line##*) }}
set -- $line
[ "$#" -ge 20 ] || die source_start
shift 19
[ "$1" = {b['start_ticks']} ] || die source_start
pid=$$
matched=0
steps=0
while [ "$pid" -gt 1 ] && [ "$steps" -lt 24 ]; do
    [ "$pid" != {b['pid']} ] || {{ matched=1; break; }}
    parent=
    while IFS= read -r line; do
        case "$line" in PPid:*) set -- $line; parent=$2;; esac
    done < /proc/$pid/status
    case "$parent" in ''|*[!0-9]*) die source_ancestry;; esac
    pid=$parent
    steps=$((steps+1))
done
[ "$matched" = 1 ] || die source_ancestry
config={shlex.quote(b['config'])}
[ -f "$config" ] && [ ! -L "$config" ] || die source_config
keys=0
ports=0
while read -r kind value extra; do
    case "$kind" in
        HostKey) [ "$value" = "$source_dir/host_ecdsa" ] && [ -z "$extra" ] || die source_config_key; keys=$((keys+1));;
        Port) [ "$value" = 2222 ] && [ -z "$extra" ] || die source_config_port; ports=$((ports+1));;
    esac
done < "$config"
[ "$keys" = 1 ] && [ "$ports" = 1 ] || die source_config_count
'''
    return f'''# 上传前和候选启动前重新验证；不打开私钥内容。
source_gate(){{
source_dir={shlex.quote(SOURCE)}
[ -d "$source_dir" ] && [ ! -L "$source_dir" ] || die source_directory
for component in /var /var/run "$source_dir"; do
    [ -d "$component" ] && [ ! -L "$component" ] || die source_directory_path
done
set -- $(/bin/busybox ls -ldn "$source_dir")
[ "$#" -ge 5 ] && [ "$1" = drwx------ ] && [ "$3" = 0 ] && [ "$4" = 0 ] || die source_directory_metadata
[ -f "$source_dir/host_ecdsa" ] && [ ! -L "$source_dir/host_ecdsa" ] || die source_key
set -- $(/bin/busybox ls -ldn "$source_dir/host_ecdsa")
[ "$#" -ge 5 ] && [ "$1" = -rw------- ] && [ "$2" = 1 ] && [ "$3" = 0 ] && [ "$4" = 0 ] {'' if qemu_only else '&& [ "$5" = 505 ]'} || die source_key_metadata
{process}
}}
source_gate
'''
