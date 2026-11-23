#!/usr/bin/env python3
"""生成只允许 `download:<sparse>` + `flash:nflasha1` 的救援写入器（离线构建，不运行）。

输入：`assets/rescue-to-original.sparse`（把本事务写过的 258 个扇区恢复成写前内容）。
输出：`host/rescue_writer`（macOS arm64）。
"""
import argparse
import hashlib
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent          # a7r5-fastboot/rescue
MODULE = HERE.parent                                     # a7r5-fastboot
REPO = MODULE.parent
SRC = (REPO / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/'
              'upstream/analysis/r5_verifykey_skip_flash_20261014/partition1_usb.c')
BUILD = HERE / 'build'
CLANG = '/usr/bin/clang'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sparse', type=pathlib.Path,
                        default=MODULE / 'assets/rescue-to-original.sparse')
    parser.add_argument('--output', type=pathlib.Path,
                        default=MODULE / 'host/rescue_writer')
    args = parser.parse_args()
    sparse = args.sparse.read_bytes()
    sparse_sha = hashlib.sha256(sparse).hexdigest()

    text = SRC.read_text()
    text = re.sub(r'static int allowed\(const char \*s\) \{.*?\n\}',
                  'static int allowed(const char *s) { return !strncmp(s,"download:/",10) || '
                  '!strcmp(s,"flash:nflasha1"); }', text, count=1, flags=re.S)
    text = text.replace('ce51008ae51696004488b02ae291b23390edcea70870d0c60280ebeccd1a53ee', sparse_sha)
    marker = 'static int command(const char *arg) {\n'
    guard = ('    int is_flash=!strcmp(arg,"flash:nflasha1"); '
             'if(is_flash && (!download_approved || write_sent)) return -1; '
             'if(is_flash) write_sent=1;\n')
    text = text.replace(marker, marker + guard, 1)
    text = text.replace('static unsigned char staged[524288];',
                        'static int download_approved=0, data_sent=0, write_sent=0;\n'
                        'static unsigned char staged[524288];', 1)
    text = text.replace('if(!memcmp(b,"OKAY",4)){if(saved_path)',
                        'if(!memcmp(b,"OKAY",4)){if(!strncmp(arg,"download:/",10)){'
                        'if(!data_sent){fprintf(stderr,"DOWNLOAD OKAY BEFORE DATA\\n");return -1;}'
                        'download_approved=1;}if(saved_path)', 1)
    text = text.replace('downloading=0;continue;', 'data_sent=1;downloading=0;continue;', 1)
    text = text.replace('int main(int argc,char **argv) {\n    setbuf(stdout,NULL);',
                        'int main(int argc,char **argv) {\n    setbuf(stdout,NULL); '
                        'if(argc!=3 || strncmp(argv[1],"download:/",10) || '
                        'strcmp(argv[2],"flash:nflasha1")) return 2;', 1)

    BUILD.mkdir(parents=True, exist_ok=True)
    source = BUILD / 'rescue_writer.c'
    source.write_text(text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([CLANG, '-O2', '-Wall', '-Wextra', str(source), '-o', str(args.output),
                    '-framework', 'IOKit', '-framework', 'CoreFoundation'], check=True)
    blob = args.output.read_bytes()
    print('sparse', sparse_sha)
    print('writer', len(blob), hashlib.sha256(blob).hexdigest())
    assert sparse_sha.encode() in blob and b'flash:nflasha1' in blob and b'flash:nflasha2' not in blob


if __name__ == '__main__':
    main()
