#!/bin/sh
#IM_Systemで直接コマンドを実行した場合、パスフレーズなしの鍵ファイルが生成されないため、スクリプト化

RES="1"

/usr/bin/ssh-keygen -q -b 256 -t ecdsa -N '' -f /tmp_network/ssh/ssh_host_ecdsa_key

if [ "$?" == "0" ]; then
  RES="0"
fi

exit "$RES"
