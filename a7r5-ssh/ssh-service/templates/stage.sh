#!/bin/sh
# 固定上传路径与摘要；不启用自启，不覆盖已有安装，失败保留部分材料供核对。
set -eu
PATH=/bin:/usr/bin:/usr/sbin
export PATH
umask 077
I='@INSTALL@'
S='/tmp/jiritsu/a7r5-@RUN@'
hash() { [ -f "$1" ] && [ ! -L "$1" ] || return 1; value=$(/usr/bin/openssl dgst -sha256 "$1") || return 1; printf '%s' "${value##* }"; }
[ "$(hash /etc/ld.so.preload)" = '@NEUTRAL_SHA@' ]
[ "$(hash /etc/passwd)" = '@PASSWD_SHA@' ]
[ ! -e /etc/shadow ] && [ ! -L /etc/shadow ]
[ "$(hash /usr/sbin/sshd)" = '@SSHD_SHA@' ]
[ "$(hash /version.txt)" = '@VERSION_SHA@' ]
[ "$(hash "$S.service-helper")" = '@HELPER_SHA@' ]
[ "$(hash "$S.boot-hook.so")" = '@HOOK_SHA@' ]
[ "$(hash "$S.control.sh")" = '@CONTROL_SHA@' ]
[ ! -e "$I" ] && [ ! -L "$I" ]
/bin/busybox mkdir "$I"
/bin/busybox chmod 755 "$I"
/bin/busybox cp "$S.service-helper" "$I/ssh-service.arm64"
/bin/busybox cp "$S.boot-hook.so" "$I/boot-hook.so"
/bin/busybox cp "$S.control.sh" "$I/control.sh"
/bin/busybox cp /etc/ld.so.preload "$I/preload.backup"
/bin/busybox chmod 700 "$I/ssh-service.arm64" "$I/control.sh"
/bin/busybox chmod 644 "$I/boot-hook.so"
/bin/busybox chmod 600 "$I/preload.backup"
[ "$(hash "$I/ssh-service.arm64")" = '@HELPER_SHA@' ]
[ "$(hash "$I/boot-hook.so")" = '@HOOK_SHA@' ]
[ "$(hash "$I/control.sh")" = '@CONTROL_SHA@' ]
[ "$(hash "$I/preload.backup")" = '@NEUTRAL_SHA@' ]
/usr/bin/ssh-keygen -q -t ecdsa -b 256 -N '' -f "$I/host_ecdsa"
/bin/busybox chmod 600 "$I/host_ecdsa" "$I/host_ecdsa.pub"
/bin/busybox sync
"$I/ssh-service.arm64" --launch
printf '%s\n' 'A7R5_SERVICE_STAGED_AUTOSTART_DISABLED'
