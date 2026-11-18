"""仅执行更新脚本的函数；硬件、挂载及文件写入命令全部替换为记录桩。"""
from pathlib import Path
import os
import re
import subprocess

import pytest

SCRIPT = Path(os.environ.get('A7R5_NOR_SCRIPT', Path(__file__).with_name('nor_loader_writer.sh')))

MOCKS = r'''
LOADER_EXTRACT_PATH=.
CPFIRMUP_COMMAND=rpc
PFORMAT_COMMAND=pformat
GET_LED_VALUE_COMMAND=led
SPICOMBOOT_COMMAND=ok
PORTSETTING_COMMAND=ok
SPICOM_COMMAND=ok
GET_MIS_HEADER=mis
GET_LSINUM_COMMAND=lsi
GET_BOOT_EXT_COMMAND=ext
GET_BOOT_DEVICE_COMMAND=dev
rpc() {
    printf 'RPC %s\n' "$*"
    case "$FAIL_KIND:$1" in
      erase:-e) return 7;; write:-f|write:-y) return 9;;
      mode:-m) return 8;; init:-i) return 255;;
      link:-l|standby:-c) return 255;; transfer:-u) return 11;;
    esac
    if [ "$1" = -i ]; then return "${FLASH_TYPE:-0}"; fi
    return 0
}
mock_log() { printf 'LOG %s\n' "$*"; }
led() { printf 'LED %s\n' "$*"; return 0; }
ok() { return 0; }
pformat() { printf 'PFORMAT %s\n' "$*"; [ "$FAIL_KIND" != pformat ]; }
mount() { printf 'MOUNT\n'; [ "$FAIL_KIND" != mount ]; }
umount() { printf 'UMOUNT\n'; [ "$FAIL_KIND" != umount ]; }
cp() { printf 'COPY %s\n' "$*"; [ "$FAIL_KIND" != copy ]; }
dd() { printf 'DD\n'; [ "$FAIL_KIND" != dd ]; }
insmod() { printf 'INSMOD\n'; [ "$FAIL_KIND" != insmod ]; }
tar() { printf 'TAR\n'; [ "$FAIL_KIND" != tar ]; }
mock_bksb() { printf 'BKSB\n'; [ "$FAIL_KIND" != bksb ]; }
mis() { printf '16\n'; if [ "$FAIL_KIND" = mis ]; then return 13; fi; }
lsi() { return 3; }
ext() { return 0; }
dev() { return 1; }
get_start_address_from_pformat() { printf '2097152\n'; }
get_size_from_pformat() { printf '65536\n'; }
get_enc_opt_from_pformat() { printf '%s\n' -f; }
'''


def run(tmp_path, action, failure='', flash_type=0, script=SCRIPT):
    source = script.read_text().replace('. /usr/bin/common.src', ': # 测试中不读取机身环境')
    main = re.search(r'^make_nor_loader_img(?:[ \t].*)?$', source, re.M)
    assert main
    definitions = source[:main.start()]
    for name in ('pcie_phy_fw.bin', 'cpapp-b.bin'):
        (tmp_path / name).write_bytes(b'fixture')
    (tmp_path / 'pformat_config.txt').write_text('cpapp-b.bin {\n ddr=1\n}\n')
    body = (definitions + MOCKS + '\n' + action).replace('updater_log.sh', 'mock_log').replace('bksb.elf', 'mock_bksb')
    result = subprocess.run(['/bin/sh', '-c', body],
                          cwd=tmp_path, env={**os.environ, 'FAIL_KIND': failure,
                                           'FLASH_TYPE': str(flash_type)},
                          text=True, capture_output=True, timeout=5)
    assert not any(message in result.stderr for message in ('not a valid identifier', 'syntax error', 'command not found'))
    return result


@pytest.mark.parametrize('function,failure', [
    ('erase_write_flash fixture 2097152 65536 -f 3', 'erase'),
    ('erase_write_flash fixture 2097152 65536 -f 3', 'write'),
    ('write_flash fixture 2097152 -f', 'write'),
    ('nor_update', 'erase'), ('nor_update', 'write'), ('nor_update', 'mode'),
    ('nor_update', 'dd'), ('nor_update', 'pformat'),
    ('set_xfer_mode_from_pformat cpapp-b.bin', 'mode'),
    ('set_xfer_mode_from_pformat cpapp-b.bin', 'init'),
    ('load_cp_updater', 'link'), ('load_cp_updater', 'standby'),
    ('load_cp_updater', 'transfer'), ('load_cp_updater', 'insmod'),
    ('make_nor_loader_img', 'tar'), ('make_nor_loader_img', 'mount'),
    ('make_nor_loader_img', 'copy'), ('make_nor_loader_img', 'bksb'),
    ('write_nor_loader_img', 'mount'), ('write_nor_loader_img', 'copy'),
    ('load_cp_updater', 'mis'), ('nor_update', 'mis'), ('update_ddrtraining', 'mis'),
])
def test_failed_device_or_preparation_step_is_not_reported_success(tmp_path, function, failure):
    result = run(tmp_path, function, failure)
    assert result.returncode != 0, result.stdout
    if failure == 'erase':
        assert 'RPC -f' not in result.stdout
    assert 'LOG NOR_FLASH END.' not in result.stdout


@pytest.mark.parametrize('flash_type', [0, 2])
def test_flash_type_exit_value_is_accepted_as_data(tmp_path, flash_type):
    result = run(tmp_path, 'nor_update', flash_type=flash_type)
    assert result.returncode == 0, result.stderr
    assert f'PFORMAT -f {flash_type}' in result.stdout
    assert 'LOG NOR_FLASH END.' in result.stdout


@pytest.mark.parametrize('size,erase_type,count', [(4096, 2, 1), (4097, 2, 2), (65536, 3, 1), (65537, 3, 2)])
def test_erase_does_not_cover_an_extra_unit_on_exact_boundary(tmp_path, size, erase_type, count):
    result = run(tmp_path, f'erase_write_flash fixture 2097152 {size} -f {erase_type}')
    assert result.returncode == 0
    index = 2097152 // (4096 if erase_type == 2 else 65536)
    assert f'RPC -e {erase_type} -a {index} -s {count}\n' in result.stdout


@pytest.mark.parametrize('stage', [
    'make_nor_loader_img', 'load_cp_updater', 'nor_update',
    'update_ddrtraining', 'write_nor_loader_img',
])
def test_top_level_aborts_after_failed_stage(tmp_path, stage):
    source = SCRIPT.read_text()
    main = re.search(r'^make_nor_loader_img(?:[ \t].*)?$', source, re.M)
    overrides = '\n'.join(f'{name}() {{ printf "STAGE {name}\\n"; return {7 if name == stage else 0}; }}'
                          for name in ('make_nor_loader_img', 'load_cp_updater', 'nor_update',
                                       'update_ddrtraining', 'write_nor_loader_img'))
    result = run(tmp_path, overrides + '\n' + source[main.start():])
    assert result.returncode != 0, result.stdout
    assert result.stdout.splitlines()[-1] == 'STAGE ' + stage
