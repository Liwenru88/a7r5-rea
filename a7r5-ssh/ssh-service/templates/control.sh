#!/bin/sh
# 仅目标机使用；私有账户不会限制已登录root主动写入其他共享路径的能力。
set -eu
PATH=/bin:/usr/bin:/usr/sbin
export PATH
umask 077
I='@INSTALL@'
R='@RUN@'
N='@NEUTRAL_SHA@'
H='@HOOK_LINE_SHA@'
RAM='/tmp_network/a7r5-ssh-@RUN@'
P='/etc/ld.so.preload'
die() { printf '%s\n' "A7R5_CONTROL_REFUSED $1" >&2; exit 1; }
hash() { [ -f "$1" ] && [ ! -L "$1" ] || return 1; value=$(/usr/bin/openssl dgst -sha256 "$1") || return 1; printf '%s' "${value##* }"; }
check_files() {
 [ "$(hash "$I/ssh-service.arm64")" = '@HELPER_SHA@' ] || die helper
 [ "$(hash "$I/boot-hook.so")" = '@HOOK_SHA@' ] || die hook
 [ "$(hash "$I/preload.backup")" = "$N" ] || die backup
}
case "${1:-}" in
 status)
  /bin/busybox cat "$RAM/ready" "$RAM/heartbeat"
  ;;
 enable-autostart)
  [ "${2:-}" = "ENABLE_AUTOSTART_$R" ] || die explicit_enable_token
  check_files
  [ "$(hash "$P")" = "$N" ] || die unknown_preload
  [ ! -e "$I/enabled" ] && [ ! -L "$I/enabled" ] || die existing_marker
  [ ! -e "$I/disabled-marker-$R" ] && [ ! -L "$I/disabled-marker-$R" ] || die retired_package
  # 全局互斥目录只覆盖本工具；不能证明其他软件不会同时改preload。
  /bin/busybox mkdir /etc/.a7r5-preload-edit.lock
  set -C
  printf '%s\n' "$R" > "$I/enabled"
  printf '%s\n' "$I/boot-hook.so" > "$P.a7r5-$R.new"
  set +C
  /bin/busybox chmod 600 "$I/enabled"
  /bin/busybox chmod 644 "$P.a7r5-$R.new"
  [ "$(hash "$P.a7r5-$R.new")" = "$H" ] || die staged_preload
  [ "$(hash "$P")" = "$N" ] || die concurrent_preload_change
  /bin/busybox sync
  /bin/busybox mv "$P.a7r5-$R.new" "$P"
  /bin/busybox sync
  [ "$(hash "$P")" = "$H" ] || die preload_readback
  /bin/busybox rmdir /etc/.a7r5-preload-edit.lock
  printf '%s\n' 'A7R5_AUTOSTART_ENABLED_CANDIDATE'
  ;;
 disable-autostart)
  check_files
  current=$(hash "$P") || die preload
  [ "$current" = "$N" ] || [ "$current" = "$H" ] || die unknown_preload
  if [ -e "$I/enabled" ] || [ -L "$I/enabled" ]; then
   [ -f "$I/enabled" ] && [ ! -L "$I/enabled" ] || die marker_type
   [ "$(hash "$I/enabled")" = '@MARKER_SHA@' ] || die marker_content
   [ ! -e "$I/disabled-marker-$R" ] && [ ! -L "$I/disabled-marker-$R" ] || die prior_disabled_marker
  fi
  /bin/busybox mkdir /etc/.a7r5-preload-edit.lock
  if [ -e "$I/enabled" ]; then /bin/busybox mv "$I/enabled" "$I/disabled-marker-$R"; fi
  if [ "$current" = "$H" ]; then
   set -C
   /bin/busybox cat "$I/preload.backup" > "$P.a7r5-$R.restore"
   set +C
   /bin/busybox chmod 644 "$P.a7r5-$R.restore"
   [ "$(hash "$P.a7r5-$R.restore")" = "$N" ] || die restore_candidate
   [ "$(hash "$P")" = "$H" ] || die concurrent_preload_change
   /bin/busybox sync
   /bin/busybox mv "$P.a7r5-$R.restore" "$P"
   /bin/busybox sync
  fi
  [ "$(hash "$P")" = "$N" ] || die restore_readback
  /bin/busybox rmdir /etc/.a7r5-preload-edit.lock
  printf '%s\n' 'A7R5_AUTOSTART_DISABLED_PRELOAD_RESTORED'
  ;;
 stop)
  # 应从服务外部调用；在本SSH会话内调用会同时结束当前连接。
  check_files
  [ "$(hash "$P")" = "$N" ] || die disable_autostart_first
  [ ! -e "$I/enabled" ] && [ ! -L "$I/enabled" ] || die disable_marker_first
  exec "$I/ssh-service.arm64" --stop
  ;;
 *) die 'use_status_enable-autostart_disable-autostart_or_stop' ;;
esac
