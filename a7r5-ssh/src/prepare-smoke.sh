#!/bin/sh
# 候选模板；只有离线生成器替换完整固定材料后才可在隔离副本验证。
set -eu
B=/bin/busybox
sum=$(/usr/bin/openssl dgst -sha256 /usr/sbin/sshd); [ "${sum##* }" = '@SSHD_SHA@' ]
sum=$(/usr/bin/openssl dgst -sha256 @SUPERVISOR@); [ "${sum##* }" = '@SUPERVISOR_SHA@' ]
root_shell=
while IFS=: read -r account password uid gid comment home shell; do [ "$account" != root ] || root_shell="$shell"; done < /etc/passwd
[ "$root_shell" = /bin/sh ]
matches=0
while read -r source target fs rest; do
  if [ "$target" = /tmp_network ] && [ "$fs" = tmpfs ]; then matches=$((matches+1)); fi
done < /proc/mounts
[ "$matches" = 1 ]
[ -d /var/empty ] && [ ! -L /var/empty ]
# 不更改原目录权限；根目录或RAM父目录不满足StrictModes时拒绝。
trusted_directory() {
  [ -d "$1" ] && [ ! -L "$1" ]
  metadata=$("$B" ls -ldn "$1")
  set -- $metadata
  case "$1" in drwx------|drwxr-x---|drwxr-xr-x) :;; *) return 1;; esac
  [ "$3" = 0 ]
}
trusted_directory /
trusted_directory /tmp_network
@SUPERVISOR@ --check-runtime
D=@DIRECTORY@
[ ! -e "$D" ] && [ ! -L "$D" ]
umask 077
"$B" mkdir -m 700 "$D"
printf '%s\n' '@PUBLIC_KEY@' > "$D/authorized_keys"
cat > "$D/sshd_config" <<'A7R5_FIXED_CONFIG'
@CONFIG@A7R5_FIXED_CONFIG
/usr/bin/ssh-keygen -t ecdsa -b 256 -N '' -f "$D/host_ecdsa"
/usr/sbin/sshd -t -f "$D/sshd_config"
printf 'A7R5_SSH_HOST_PUBLIC_KEY\n'
"$B" cat "$D/host_ecdsa.pub"
printf 'A7R5_SSH_STARTING_BOUNDED_FIXED_COMMAND\n'
exec @SUPERVISOR@ "$D/sshd_config" @SECONDS@
