"""私有SSH候选的本机构建；不包含相机执行或批准命令。"""
import hashlib
import ipaddress
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


def build(directory, public_key, address, seconds=60, *, qemu_only=False):
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+", public_key):
        raise ValueError("只接受一条无选项、无注释的Ed25519公钥")
    import base64
    raw = base64.b64decode(public_key.split()[1], validate=True)
    if len(raw) != 51 or raw[:19] != b"\0\0\0\x0bssh-ed25519\0\0\0\x20":
        raise ValueError("公钥结构不符")
    ip = ipaddress.IPv4Address(address)
    if str(ip) != address or not (ip.is_loopback if qemu_only else any(ip in ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))):
        raise ValueError("地址超出候选范围")
    if type(seconds) is not int or not 20 <= seconds <= 180:
        raise ValueError("寿命须在20至180秒")
    import uuid
    run = uuid.uuid4().hex
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)) or directory.is_relative_to("/dev"):
        raise ValueError("只允许新的本机普通目录")
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    private = "/var/run/a7r5-ssh-" + run
    configuration = f"""Port 2222
AddressFamily inet
ListenAddress {address}
HostKey {private}/host_ecdsa
PidFile {private}/sshd.pid
AuthorizedKeysFile {private}/authorized_keys
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
ChallengeResponseAuthentication no
UsePAM no
StrictModes yes
AllowUsers root
MaxSessions 1
MaxStartups 1
MaxAuthTries 1
LoginGraceTime 10
AllowTcpForwarding no
AllowStreamLocalForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitTTY no
PermitUserEnvironment no
PrintLastLog no
UseDNS no
ForceCommand /bin/busybox cat /proc/self/status
LogLevel ERROR
"""
    values = dict(RUN_ID=run, RAM_NAME="a7r5-ssh-" + run, PRIVATE_DIR=private,
                  LISTEN_IP=address, PUBLIC_KEY=public_key + "\n", SSH_CONFIG=configuration,
                  EXPECTED_PASSWD_SHA=PASSWD_SHA)
    header = "".join("#define " + k + " " + json.dumps(v) + "\n" for k, v in values.items())
    (directory / "config.h").write_text(header + "#define SSH_SECONDS " + str(seconds) + "\n")
    libc = LAB / "vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so"
    binary = directory / "private-sshd.arm64"
    command = ["/opt/homebrew/opt/llvm/bin/clang", "--target=aarch64-linux-gnu",
               "--ld-path=/opt/homebrew/opt/lld/bin/ld.lld", "-nostdlib", "-ffreestanding", "-fno-builtin",
               "-fno-stack-protector", "-fPIE", "-pie", "-O2", "-Wall", "-Wextra", "-Werror",
               "-Wl,--no-undefined", "-Wl,-e,_start", "-Wl,-z,max-page-size=65536",
               "-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1", "-I", str(directory),
               str(LAB / "src/start.S"), str(ROOT / "launcher.c"), str(libc), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    receipt = dict(run_id=run, address=address, seconds=seconds, qemu_only=qemu_only,
                   account_fields_changed_in_private_view_only=True, live_execution_enabled=False,
                   command=command, compile_exit=result.returncode, stderr=result.stderr,
                   sources={str(p):sha(p) for p in (ROOT / "launcher.c", ROOT / "private_account.h", LAB / "src/ns_abi.h", LAB / "src/ns_sha256.h")})
    if result.returncode:
        (directory / "build-failed.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        raise RuntimeError(result.stderr)
    receipt.update(binary=str(binary), binary_sha256=sha(binary), binary_bytes=binary.stat().st_size,
                   ram_directory="/tmp_network/a7r5-ssh-" + run)
    (directory / "build.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt
