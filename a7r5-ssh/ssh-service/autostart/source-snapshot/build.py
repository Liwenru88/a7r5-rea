"""私有SSH候选的本机构建；不包含相机执行或批准命令。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parent
PASSWD_SHA = "4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(directory, password_hash, address, seconds=0, *, qemu_only=False):
    import credentials
    if not credentials.valid_hash(password_hash):raise ValueError('只接受本次SHA512-crypt哈希格式')
    if address != "0.0.0.0":
        raise ValueError("本版本只允许固定通配IPv4地址0.0.0.0")
    if type(seconds) is not int or not (seconds==0 or 20 <= seconds <= 600):
        raise ValueError("寿命须为0（常驻）或20至600秒验证窗口")
    import uuid
    run = uuid.uuid4().hex
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)) or directory.is_relative_to("/dev"):
        raise ValueError("只允许新的本机普通目录")
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    private = "/var/run/a7r5-ssh-" + run
    install = "/tmp/jiritsu/a7r5-ssh-service-" + run
    configuration = f"""Port 2222
AddressFamily inet
ListenAddress {address}
HostKey {private}/host_ecdsa
PidFile {private}/sshd.pid
AuthorizedKeysFile none
PermitRootLogin yes
PubkeyAuthentication no
AuthenticationMethods password
PasswordAuthentication yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM no
StrictModes yes
AllowUsers root
MaxSessions 4
MaxStartups 1
MaxAuthTries 1
LoginGraceTime 10
AllowTcpForwarding no
AllowStreamLocalForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitTTY yes
PermitUserEnvironment no
PermitUserRC no
PrintLastLog no
UseDNS no
Subsystem sftp internal-sftp
PrintMotd no
LogLevel ERROR
"""
    values = dict(INSTALL_DIR=install, BOOT_TRIGGER="/simulation/boot-trigger" if qemu_only else "/usr/bin/bootin.elf", RUN_ID=run, RAM_NAME="a7r5-ssh-" + run, PRIVATE_DIR=private,
                  PASSWORD_HASH=password_hash, SSH_CONFIG=configuration,
                  EXPECTED_PASSWD_SHA=PASSWD_SHA)
    header = "".join("#define " + k + " " + json.dumps(v) + "\n" for k, v in values.items())
    (directory / "config.h").write_text(header + "#define SSH_SECONDS " + str(seconds) + "\n")
    libc = LAB / "vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so"
    binary = directory / "ssh-service.arm64"
    command = ["/opt/homebrew/opt/llvm/bin/clang", "--target=aarch64-linux-gnu",
               "--ld-path=/opt/homebrew/opt/lld/bin/ld.lld", "-nostdlib", "-ffreestanding", "-fno-builtin",
               "-fno-stack-protector", "-fPIE", "-pie", "-O2", "-Wall", "-Wextra", "-Werror",
               "-Wl,--no-undefined", "-Wl,-e,_start", "-Wl,-z,max-page-size=65536",
               "-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1", "-I", str(directory),
               str(LAB / "src/start.S"), str(ROOT / "launcher.c"), str(libc), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    receipt = dict(run_id=run, address=address, seconds=seconds, qemu_only=qemu_only,
                   account_fields_changed_in_private_view_only=True, live_execution_enabled=False,
                   startup_requires_lan_ipv4=False, host_network_probe_enabled=False,
                   command=command, compile_exit=result.returncode, stderr=result.stderr,
                   sources={str(p):sha(p) for p in (ROOT / "launcher.c", ROOT / "private_account.h", ROOT / "private_hostkey.h", LAB / "src/ns_abi.h", LAB / "src/ns_sha256.h")})
    if result.returncode:
        (directory / "build-failed.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise RuntimeError(result.stderr)
    hook=directory/'boot-hook.so'
    hook_command=command[:]
    start=hook_command.index(str(LAB/'src/start.S'))
    hook_command=hook_command[:start]+[str(ROOT/'boot_hook.c'),str(libc),'-o',str(hook)]
    hook_command=[arg for arg in hook_command if arg not in ('-fPIE','-pie','-Wl,-e,_start','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1')]
    hook_command[hook_command.index('-O2'):hook_command.index('-O2')]=['-fPIC','-shared']
    compiled=subprocess.run(hook_command,capture_output=True,text=True,timeout=60)
    if compiled.returncode:raise RuntimeError(compiled.stderr)
    receipt.update(hook_command=hook_command,hook_sha256=sha(hook),hook_bytes=hook.stat().st_size,
                   hook_source_sha256=sha(ROOT/'boot_hook.c'),daemon_no_ttl=seconds==0,
                   real_boot_verified=False,live_installation_approved=False)
    receipt.update(binary=str(binary), binary_sha256=sha(binary), binary_bytes=binary.stat().st_size,
                   install_directory=install,ram_directory="/tmp_network/a7r5-ssh-" + run)
    (directory / "build.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt
