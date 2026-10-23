#!/bin/sh
# 固定只读检查；不输出密码字段、私钥或完整账号文件。
set -eu
B=/bin/busybox
printf 'A7R5_SSH_PREFLIGHT_BEGIN @RUN@\n'
while read -r field real effective rest; do
  if [ "$field" = Uid: ]; then printf 'UID %s\nEUID %s\n' "$real" "$effective"; fi
done < /proc/self/status
sum=$(/usr/bin/openssl dgst -sha256 /version.txt); printf 'VERSION_SHA256 %s\n' "${sum##* }"
sum=$(/usr/bin/openssl dgst -sha256 /usr/sbin/sshd); printf 'SSHD_SHA256 %s\n' "${sum##* }"
while IFS=: read -r account password uid gid comment home shell; do
  if [ "$account" = root ]; then printf 'ROOT_SHELL %s\n' "$shell"; fi
done < /etc/passwd
printf 'ACCOUNT_METADATA\n'
while IFS=: read -r account password uid gid comment home shell; do
  case "$account" in root|sshd) printf '%s:uid=%s:gid=%s:home=%s:shell=%s\n' "$account" "$uid" "$gid" "$home" "$shell";; esac
done < /etc/passwd
sum=$(/usr/bin/openssl dgst -sha256 /etc/passwd); printf 'PASSWD_SHA256 %s\n' "${sum##* }"
printf 'MOUNTS\n'
while read -r source target fs options rest; do
  case "$target" in /tmp_network|/etc|/tmp|/var|/tmp/jiritsu|/dev/pts) printf '%s %s %s %s\n' "$source" "$target" "$fs" "$options";; esac
done < /proc/mounts
printf 'DIRECTORY_METADATA\n'
for d in /tmp_network /var/empty /var/run/sshd /dev/ptmx /dev/pts; do
  if [ -e "$d" ]; then "$B" ls -ldn "$d"; else printf 'MISSING %s\n' "$d"; fi
done
printf 'NSS_PASSWD\n'
if [ -r /etc/nsswitch.conf ]; then
  while read -r field rest; do [ "$field" != passwd: ] || printf '%s %s\n' "$field" "$rest"; done < /etc/nsswitch.conf
else printf 'UNREADABLE_OR_MISSING\n'; fi
printf 'FREE_SPACE_SOURCE preflight_fs.c statvfs\n'
printf 'NETWORK_INTERFACES\n'
"$B" cat /proc/net/dev
printf 'NETWORK_IPV4\n'
"$B" ifconfig -a
printf 'TCP_METADATA\n'
"$B" cat /proc/net/tcp
printf 'A7R5_SSH_PREFLIGHT_COMPLETE @RUN@\n'
