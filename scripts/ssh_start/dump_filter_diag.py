#!/usr/bin/env python3
"""通过相机 SSH 只读抓取 appFw.so 内存中的自定义滤镜诊断状态与 RAM 环形日志。"""
import argparse
import json
import shlex
import struct
import subprocess
import sys

# 4.28/4.29 appFw.so 静态固定相对偏移（相对于 appFw.so 加载基址）
# r5_filter_diag425 位于 0x8ee3f00；r5_stage411_state / probe / transfer / ram_log 可通过符号偏移读取
DEFAULT_DIAG_OFF = 0x8EE3F00

REMOTE_PY_OR_SH = r'''
set -eu
PID=""
for p in /proc/[0-9]*; do
  [ -r "$p/maps" ] || continue
  if grep -q "appFw\.so" "$p/maps" 2>/dev/null; then
    PID="${p#/proc/}"
    break
  fi
done
if [ -z "$PID" ]; then
  echo "ERR:NO_APPFW_PID"
  exit 2
fi
BASE_HEX="$(awk '/appFw\.so/ && $2 ~ /r-xp/ {split($1,a,"-"); print a[1]; exit}' "/proc/$PID/maps")"
if [ -z "$BASE_HEX" ]; then
  BASE_HEX="$(awk '/appFw\.so/ {split($1,a,"-"); print a[1]; exit}' "/proc/$PID/maps")"
fi
echo "PID=$PID"
echo "BASE=0x$BASE_HEX"
echo "MAPS_BEGIN"
grep "appFw\.so" "/proc/$PID/maps" || true
echo "MAPS_END"
echo "MOUNTS_LUT_BEGIN"
grep -E "/usr/data/lut|/setting" /proc/self/mountinfo 2>/dev/null || mount 2>/dev/null | grep -E "lut|setting" || true
echo "MOUNTS_LUT_END"
echo "LS_LUT_BEGIN"
ls -la /usr/data/lut /setting/r5_aspect10_v1.dat 2>&1 || true
echo "LS_LUT_END"
# 读取 r5_filter_diag425 (base + 0x8ee3f00, 64 字节)
DIAG_OFF=$((0x$BASE_HEX + 0x8ee3f00))
echo "DIAG_HEX_BEGIN"
dd if="/proc/$PID/mem" bs=1 skip="$DIAG_OFF" count=64 2>/dev/null | od -An -tx4 -v || true
echo "DIAG_HEX_END"
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip', required=True, help='相机 IPv4 地址')
    parser.add_argument('--port', type=int, default=2222, help='SSH 端口（默认 2222）')
    parser.add_argument('--known-hosts', help='由 start_ssh.py 生成的 known_hosts 路径')
    parser.add_argument('--host-alias', help='与 known_hosts 匹配的 HostKeyAlias')
    args = parser.parse_args()

    cmd = [
        '/usr/bin/ssh',
        '-F', '/dev/null',
        '-o', 'IdentityAgent=none',
        '-o', 'PubkeyAuthentication=no',
        '-o', 'PreferredAuthentications=password',
        '-o', 'ConnectTimeout=10',
        '-p', str(args.port),
    ]
    if args.known_hosts and args.host_alias:
        cmd += [
            '-o', f'HostKeyAlias={args.host_alias}',
            '-o', f'UserKnownHostsFile={args.known_hosts}',
            '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'StrictHostKeyChecking=yes',
        ]
    cmd += [f'root@{args.ip}', 'sh', '-s']

    print(f'[diag] 正在只读连接 root@{args.ip}:{args.port} 采集自定义滤镜诊断现场...', flush=True)
    proc = subprocess.run(cmd, input=REMOTE_PY_OR_SH, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
