"""本机C契约、AArch64编译及固定探针验证；不导入USB或SSH模块。"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parents[1]
RUN = '2f94aea65af84dc6ab01a667752d283c'
INSTALL = '/tmp/jiritsu/a7r5-ssh-service-' + RUN


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, *, expect=0, output=None):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    value = dict(command=[str(item) for item in command], exit_code=result.returncode,
                 stdout=result.stdout, stderr=result.stderr)
    if output:
        output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    if result.returncode != expect:
        raise RuntimeError('本机验证失败：' + repr(value))
    return value


def main():
    build = ROOT / 'build'
    build.mkdir(exist_ok=False)
    result = dict(camera_io=False, host_usb_enumeration=False, ssh_started=False,
                  guest_execution=False, original_images_modified=False, status='failed')
    try:
        native = '/usr/bin/clang'
        common = [native, '-std=c11', '-D_DARWIN_C_SOURCE', '-Wall', '-Wextra', '-Werror',
                  '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(ROOT / 'src')]
        run([*common, str(ROOT / 'tests/legacy_errno.c'), '-o', str(build / 'legacy-errno')])
        red = run([str(build / 'legacy-errno')], expect=1, output=ROOT / 'verification/legacy-red.json')
        assert 'LEGACY code=109 errno=30 actual_failure=permission_predicate' in red['stdout']
        result['old_stale_errno_reproduced'] = True
        run([*common, str(ROOT / 'tests/test_metadata.c'), '-o', str(build / 'test-metadata')])
        checked = run([str(build / 'test-metadata')], output=ROOT / 'verification/native-contract.json')
        assert 'cases=9 stale_errno_cleared=1 old_rejection_policy_preserved=1' in checked['stdout']
        result['native_cases'] = 9
        result['address_and_undefined_sanitizers'] = 'passed'

        # 用本机临时普通文件检查探针不会输出私钥内容或修改字节、类型和权限。
        with tempfile.TemporaryDirectory(prefix='metadata-only-', dir=ROOT / 'verification') as temporary:
            fixture = Path(temporary)
            directory = fixture / 'install'
            directory.mkdir(mode=0o700)
            secret = directory / 'host_ecdsa'
            sentinel = b'PRIVATE_KEY_CONTENT_MUST_NOT_BE_READ_OR_PRINTED_109\n'
            secret.write_bytes(sentinel)
            secret.chmod(0o644)
            before = (sha(secret), secret.stat().st_mode, secret.stat().st_uid)
            config = ('#define KEY109_RUN "' + RUN + '"\n#define KEY109_INSTALL '
                      + json.dumps(str(directory)) + '\n')
            (fixture / 'probe_config.h').write_text(config)
            run([*common, '-DNS_HOST_TEST', '-I', str(fixture), str(ROOT / 'src/key109_probe.c'),
                 '-o', str(build / 'probe-host')])
            observed = run([str(build / 'probe-host')], output=ROOT / 'verification/host-probe.json')
            assert sentinel.decode().strip() not in observed['stdout']
            assert observed['stdout'].count('KEY109_META1 ') == 2
            assert 'key_content_read=0 key_writes=0 ssh_started=0' in observed['stdout']
            assert 'label=private rc=0 errno=0 valid=1 mode=100644' in observed['stdout']
            assert before == (sha(secret), secret.stat().st_mode, secret.stat().st_uid)
            bad_args = run([str(build / 'probe-host'), '/arbitrary/path'], expect=64,
                           output=ROOT / 'verification/extra-path-refused.json')
            assert not bad_args['stdout']
            result['probe_fixed_paths_only'] = True
            result['host_fixture_bytes_and_mode_unchanged'] = True

        (build / 'probe_config.h').write_text('#define KEY109_RUN "' + RUN + '"\n'
                                            '#define KEY109_INSTALL ' + json.dumps(INSTALL) + '\n')
        libc = LAB / 'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
        target_common = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
                         '-std=c11', '-nostdlib', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
                         '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                         '-I', str(ROOT / 'src'), '-I', str(build)]
        binary = build / 'key109-metadata.arm64'
        run([*target_common, '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-fPIE', '-pie',
             '-Wl,--no-undefined', '-Wl,-e,_start', '-Wl,-z,max-page-size=65536',
             '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',
             str(ROOT / 'src/start.S'), str(ROOT / 'src/key109_probe.c'), str(libc), '-o', str(binary)],
            output=ROOT / 'verification/aarch64-build.json')
        from elftools.elf.elffile import ELFFile
        with binary.open('rb') as stream:
            elf = ELFFile(stream)
            assert elf.header['e_machine'] == 'EM_AARCH64' and elf.elfclass == 64 and elf.little_endian
            undefined = sorted({symbol.name for symbol in elf.get_section_by_name('.dynsym').iter_symbols()
                                if symbol['st_shndx'] == 'SHN_UNDEF' and symbol.name})
            allowed = {'__errno_location', 'getuid', 'geteuid', 'syscall', 'memset', 'snprintf', 'write'}
            assert set(undefined) <= allowed, undefined
            result['target_imports'] = undefined
        result['target_probe'] = dict(path=str(binary), bytes=binary.stat().st_size, sha256=sha(binary),
                                      executable_on_camera_verified=False, private_key_content_read=False)
        result['target_libc_sha256'] = sha(libc)

        candidate = ROOT / 'candidate'
        candidate.mkdir()
        original = (ROOT / 'proof/launcher.original.c').read_text()
        original_block = '    {struct stat st;if(lstat(INSTALL_DIR "/host_ecdsa",&st)||!S_ISREG(st.st_mode)||st.st_uid||(st.st_mode&077)){code=109;goto finish;}}'
        assert original.count(original_block) == 1
        replacement = '''    {
        struct key109_metadata key = key109_capture(INSTALL_DIR "/host_ecdsa");
        char row[512];
        int n = key109_format(row, sizeof(row), RUN_ID, "private", &key, 1);
        if (n < 0) { errno=0; code=125; goto finish; }
        if (ram_file("key109-metadata", row, (size_t)n)) { code=125; goto finish; }
        if (key109_private_reject(&key)) { errno=key.lookup_errno; code=109; goto finish; }
    }'''
        modified = original.replace('#include "private_account.h"', '#include "private_account.h"\n#include "key109_metadata.h"').replace(original_block, replacement)
        (candidate / 'launcher.c').write_text(modified)
        patch = ''.join(difflib.unified_diff(original.splitlines(True), modified.splitlines(True),
                                            fromfile='a/launcher.c', tofile='b/launcher.c'))
        patch += ''.join(difflib.unified_diff([], (ROOT / 'src/key109_metadata.h').read_text().splitlines(True),
                                             fromfile='/dev/null', tofile='b/key109_metadata.h'))
        (ROOT / 'launcher-key109-detail.patch').write_text(patch)
        # 只编译候选对象；合成配置不含用户密码，也不生成可启动SSH的安装载荷。
        config = dict(RUN_ID=RUN, INSTALL_DIR=INSTALL, RAM_NAME='a7r5-ssh-' + RUN,
                      PRIVATE_DIR='/var/run/a7r5-ssh-' + RUN, PASSWORD_HASH='$6$offline$test-only',
                      SSH_CONFIG='Port 2222\n', EXPECTED_PASSWD_SHA='4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398')
        (candidate / 'config.h').write_text(''.join('#define ' + key + ' ' + json.dumps(value) + '\n'
                                                 for key, value in config.items()) + '#define SSH_SECONDS 0\n')
        run([*target_common, '-I', str(candidate), '-I', str(ROOT / 'proof'),
             '-c', str(candidate / 'launcher.c'), '-o', str(build / 'launcher-instrumented.o')],
            output=ROOT / 'verification/candidate-compile.json')
        result.update(minimal_diagnostic_patch_compiled=True, original_policy_relaxed=False,
                      actual_key_metadata_observed=False, exact_device_reject_predicate_known=False,
                      production_sources_changed=False, status='passed')
    finally:
        result['source_provenance_unchanged'] = all(sha(path) == expected for path, expected
            in json.loads((ROOT / 'source-provenance.json').read_text()).items())
        (ROOT / 'verification/result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
