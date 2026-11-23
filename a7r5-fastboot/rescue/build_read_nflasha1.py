#!/usr/bin/env python3
"""生成只读工具 `host/read_nflasha1`：在模块自带 read_fastboot_usb 上追加
`oem partition dump nflasha 0x80 0xbf80`（整分区 25,100,288 字节）白名单。

不改变其它只读命令，也不加入任何 download/flash/erase。
"""
import hashlib
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent          # a7r5-fastboot/rescue
MODULE = HERE.parent
SRC = MODULE / 'native/read_fastboot_usb.c'
BUILD = HERE / 'build'
BIN = MODULE / 'host/read_nflasha1'
CLANG = '/usr/bin/clang'
NEEDLE = '!strcmp(s,"oem partition dump nflasha 0 0x80") ||'
ADDITION = '\n           !strcmp(s,"oem partition dump nflasha 0x80 0xbf80") ||'


def main():
    text = SRC.read_text()
    if 'nflasha 0x80 0xbf80' not in text:
        assert NEEDLE in text
        text = text.replace(NEEDLE, NEEDLE + ADDITION, 1)
    BUILD.mkdir(parents=True, exist_ok=True)
    source = BUILD / 'read_nflasha1.c'
    source.write_text(text)
    subprocess.run([CLANG, '-O2', '-Wall', '-Wextra', str(source), '-o', str(BIN),
                    '-framework', 'IOKit', '-framework', 'CoreFoundation'], check=True)
    blob = BIN.read_bytes()
    print('reader', len(blob), hashlib.sha256(blob).hexdigest())
    assert b'oem partition dump nflasha 0x80 0xbf80' in blob
    for banned in (b'flash:', b'erase:', b'download:'):
        assert banned not in blob, banned


if __name__ == '__main__':
    main()
