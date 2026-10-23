#!/bin/sh
# 固定上传路径与摘要；不启用自启，不覆盖已有安装，失败保留部分材料供核对。
set -eu
PATH=/bin:/usr/bin:/usr/sbin
export PATH
umask 077
I='/tmp/jiritsu/a7r5-ssh-service-2f94aea65af84dc6ab01a667752d283c'
S='/tmp/jiritsu/a7r5-2f94aea65af84dc6ab01a667752d283c'
hash() { [ -f "$1" ] && [ ! -L "$1" ] || return 1; value=$(/usr/bin/openssl dgst -sha256 "$1") || return 1; printf '%s' "${value##* }"; }
[ "$(hash /etc/ld.so.preload)" = 'f33ab12d20ffae0e2aa71cc286f76c44f3eb0a277a1751746dbf3686d72e6e60' ]
[ "$(hash /etc/passwd)" = '4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398' ]
[ ! -e /etc/shadow ] && [ ! -L /etc/shadow ]
[ "$(hash /usr/sbin/sshd)" = 'a6b871ef0da3990ea0d25d7996ee79c3bfc29385d4eb1670892814c0e1472534' ]
[ "$(hash /version.txt)" = '34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b' ]
[ "$(hash "$S.service-helper")" = 'd3d486f6144f157293e5c2f69b5a34ee8e8f901bdcaf76084b5de44a30f147d2' ]
[ "$(hash "$S.boot-hook.so")" = '5fbd9e122ca311d5ac5d5058b8338fd014a70b5d55b51b5b458d6410ac005fd1' ]
[ "$(hash "$S.control.sh")" = 'bb77f983dbd17cf4fd71992103e51ccc6ec48a1f2bc03b27b2748092175cc46a' ]
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
[ "$(hash "$I/ssh-service.arm64")" = 'd3d486f6144f157293e5c2f69b5a34ee8e8f901bdcaf76084b5de44a30f147d2' ]
[ "$(hash "$I/boot-hook.so")" = '5fbd9e122ca311d5ac5d5058b8338fd014a70b5d55b51b5b458d6410ac005fd1' ]
[ "$(hash "$I/control.sh")" = 'bb77f983dbd17cf4fd71992103e51ccc6ec48a1f2bc03b27b2748092175cc46a' ]
[ "$(hash "$I/preload.backup")" = 'f33ab12d20ffae0e2aa71cc286f76c44f3eb0a277a1751746dbf3686d72e6e60' ]
/usr/bin/ssh-keygen -q -t ecdsa -b 256 -N '' -f "$I/host_ecdsa"
/bin/busybox chmod 600 "$I/host_ecdsa" "$I/host_ecdsa.pub"
/bin/busybox sync
"$I/ssh-service.arm64" --launch
printf '%s\n' 'A7R5_SERVICE_STAGED_AUTOSTART_DISABLED'
