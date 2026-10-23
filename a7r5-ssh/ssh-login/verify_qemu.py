"""原厂NSS与私有账户视图的SSH集成；无NIC、无相机、无SD直通。"""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

import build


def original_passwd():
    image = build.LAB.parent / "a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha10.img"
    with image.open("rb") as stream:
        boot = stream.read(512)
        sector = struct.unpack_from("<H", boot, 11)[0]
        reserved = struct.unpack_from("<H", boot, 14)[0]
        roots = struct.unpack_from("<H", boot, 17)[0]
        fat_sectors = struct.unpack_from("<H", boot, 22)[0]
        start = (reserved + boot[16] * fat_sectors) * sector
        cluster_bytes = sector * boot[13]
        data = start + ((roots * 32 + sector - 1) // sector) * sector
        stream.seek(start)
        directory = stream.read(roots * 32)
        found = []
        for i in range(0, len(directory), 32):
            entry = directory[i:i + 32]
            if not entry[0]:
                break
            if entry[0] != 0xe5 and entry[11] != 15 and entry[:11].decode("ascii").strip().lower() == "passwd":
                found.append(entry)
        if len(found) != 1:
            raise ValueError("原始FAT账户文件不唯一")
        entry = found[0]
        cluster = struct.unpack_from("<H", entry, 26)[0]
        size = struct.unpack_from("<I", entry, 28)[0]
        if not 0 < size < cluster_bytes:
            raise ValueError("账户文件超出本次单簇读取范围")
        stream.seek(data + (cluster - 2) * cluster_bytes)
        raw = stream.read(size)
    if hashlib.sha256(raw).hexdigest() != build.PASSWD_SHA:
        raise ValueError("原始账户基线不符")
    return raw


def main():
    workspace = build.LAB.parent
    sys.path.insert(0, str(build.LAB))
    import lab
    import isolation_qemu
    import qemu_verify
    sys.path.extend(str(p) for p in (Path.home()/".codex/skills/ssh-skill/.venv/lib").glob("python*/site-packages"))
    import paramiko
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    sys.path.insert(0, str(workspace/"a7r5-qemu/tools"))
    import vm_session
    from native_vm import NativeVM
    from runtime_manifest import verified_inputs
    destination = build.ROOT/"verification"
    destination.mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="qemu-wildcard-", dir=destination))
    fixture = build.LAB/"analysis/network-20261020-v1"
    provenance = json.loads((fixture/"sources.json").read_text())
    files = {}
    for name in ("original/etc/nsswitch.conf", "original/etc/ssh/sshd_config"):
        raw = (fixture/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != provenance["files"][name]["sha256"]:
            raise ValueError("原厂配置证据摘要变化")
        files["/etc/" + name.removeprefix("original/etc/")] = raw
    files["/etc/passwd"] = original_passwd()
    private = ed25519.Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    secret = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(secret))
    candidate = build.build(out/"candidate", public, "0.0.0.0", 45, qemu_only=True)
    conflict = build.build(out/"conflict-candidate", public, "0.0.0.0", 20, qemu_only=True)
    early = build.build(out/"early-candidate", public, "0.0.0.0", 20, qemu_only=True)
    inputs = verified_inputs()
    before = {k:build.sha(p) for k,p in inputs.items()}
    vm_session.RUNS = out
    vm = NativeVM("wildcard-ssh", capid=True, boot_services=True)
    result = dict(status="failed", camera_io=False, guest_nic="none", host_tcp_connections=False,
                  candidate=candidate, original_nss_used=True, original_group_and_shadow_absence_preserved=True,
                  client_private_key_saved=False, input_sha256=before,lan_ipv4_required=False)
    ram = candidate["ram_directory"]
    try:
        vm.start()
        vm.command("mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root")
        for path,raw in files.items():
            isolation_qemu.put(vm,path,raw)
        isolation_qemu.put(vm,"/simulation/private-sshd",Path(candidate["binary"]).read_bytes(),"700")
        isolation_qemu.put(vm,"/simulation/conflict-sshd",Path(conflict["binary"]).read_bytes(),"700")
        isolation_qemu.put(vm,"/simulation/early-sshd",Path(early["binary"]).read_bytes(),"700")
        relay=build.LAB/"verification/qemu-jx_1vzc1/ssh-relay"
        if build.sha(relay)!="b2e94f220556e3bdc68e5ad3ea47a6386fe6cc4a83d9844e3713b869806d6dea":
            raise ValueError("既有串口回环中继摘要变化")
        isolation_qemu.put(vm,"/simulation/ssh-relay",relay.read_bytes(),"700")
        print("通配候选已上传QEMU RAM，无NIC/无LAN地址，正在核对摘要并启动",flush=True)
        uploaded=vm.command("/usr/bin/openssl dgst -sha256 /simulation/private-sshd")
        if candidate["binary_sha256"].encode() not in uploaded:
            raise ValueError("候选串口上传摘要不符")
        launch=vm.command("/simulation/private-sshd --launch",timeout=30)
        (out/"launch.txt").write_bytes(launch)
        if ("A7R5_PRIVATE_LAUNCH "+candidate["run_id"]+" READY").encode() not in launch:
            raise ValueError("私有SSH候选未READY")
        host=vm.command("sleep 1; cat "+ram+"/ready; cat "+ram+"/host-public-key; cat "+ram+"/started; cat /proc/net/tcp")
        (out/"ready-and-host-public.txt").write_bytes(host)
        match=re.search(rb"ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)",host)
        if not match:raise ValueError("没有本次可信主机公钥")
        host_key=base64.b64decode(match[1])
        import operation
        text=host.replace(b'\r',b'')
        started=re.search(rb'^A7R5_WILDCARD_STARTED [^\n]+\n',text,re.M)
        banner_serial=vm.command("echo BANNER_BEGIN; cat "+ram+"/banner; echo BANNER_END")
        (out/'banner-serial.txt').write_bytes(banner_serial)
        encoded=re.search(rb'\nBANNER_BEGIN\n(SSH-2\.0-[ -~]+)\nBANNER_END',banner_serial.replace(b'\r',b''))
        if not started or not encoded:raise ValueError('缺少通配启动或回环标识回执')
        # UART会转换换行；只在两种合法结尾中选择与客体原字节摘要一致的一种。
        expected=re.search(rb'banner_sha=([0-9a-f]{64})',started[0])[1].decode()
        choices=[encoded[1]+ending for ending in (b'\r\n',b'\n')]
        matching=[value for value in choices if hashlib.sha256(value).hexdigest()==expected]
        if len(matching)!=1:raise ValueError('串口标识不能还原到客体原字节摘要')
        banner=matching[0];(out/'banner.bin').write_bytes(banner)
        result['startup']=operation.startup(started[0],banner,candidate['run_id'])
        result['local_banner']=banner.decode('ascii')
        if not re.search(rb'00000000:08AE\s+[0-9A-F:]+\s+0A',text):raise ValueError('没有实际通配IPv4监听')
        result['wildcard_socket_verified']=True
        result["fixed_root_command"]=qemu_verify.connection(vm,paramiko,key,host_key)
        if not re.search(r"^Gid:\s+0\s+0\s+0\s+0\s*$",result["fixed_root_command"]["output"],re.M):
            raise ValueError("GID不是四项0")
        result["wrong_key"]=qemu_verify.connection(vm,paramiko,paramiko.ECDSAKey.generate(),host_key,expect_auth=False)
        # 第二个候选遇到已存在监听必须失败，不能终止或替换第一个实例。
        conflict_ram=conflict['ram_directory']
        conflict_sha=vm.command('/usr/bin/openssl dgst -sha256 /simulation/conflict-sshd')
        if conflict['binary_sha256'].encode() not in conflict_sha:raise ValueError('冲突候选摘要不符')
        conflict_output=vm.command('/simulation/conflict-sshd --launch; cat '+conflict_ram+'/result '+conflict_ram+'/child-result',timeout=30)
        (out/'conflict.txt').write_bytes(conflict_output)
        normalized=conflict_output.replace(b'\r',b'')
        if not re.search(rb'PRIVATE_RESULT code=114 errno=\d+ sshd_attempted=0 listener_observed=0 children_reaped=1 private_account_changed=1 local_banner_verified=0',normalized):raise ValueError('端口冲突没有受限停止')
        result['conflict_rejected_without_restart']=True
        result['original_instance_after_conflict']=qemu_verify.connection(vm,paramiko,key,host_key)
        print("通配监听、回环标识、正确密钥root命令及错误密钥拒绝通过；端口冲突未替换原实例，等待清理",flush=True)
        final=vm.command("sleep 48; cat "+ram+"/result; cat "+ram+"/child-result; /usr/bin/openssl dgst -sha256 /etc/passwd /etc/nsswitch.conf /etc/ssh/sshd_config; test ! -e /var/run/a7r5-ssh-"+candidate["run_id"],timeout=58)
        (out/"final.txt").write_bytes(final)
        clean=final.replace(b"\r",b"")
        if not re.search(rb"A7R5_PRIVATE_RESULT [0-9a-f]+ code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1\n",clean):
            raise ValueError("外部原件、监听或子树回收未通过")
        if b"PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1 local_banner_verified=1\n" not in clean:
            raise ValueError("私有SSH终态未通过")
        for raw in files.values():
            if hashlib.sha256(raw).hexdigest().encode() not in clean:raise ValueError("外部原厂账户或NSS/SSH配置变化")
        early_sha=vm.command('/usr/bin/openssl dgst -sha256 /simulation/early-sshd')
        if early['binary_sha256'].encode() not in early_sha:raise ValueError('提前退出候选摘要不符')
        early_ram=early['ram_directory']
        early_launch=vm.command('/simulation/early-sshd --launch; cat '+early_ram+'/started',timeout=40)
        pid_match=re.search(rb'A7R5_WILDCARD_STARTED '+early['run_id'].encode()+rb' pid=(\d+) bind=0.0.0.0:2222',early_launch)
        if not pid_match or int(pid_match[1])<=1:raise ValueError('未取得本次提前退出实验的唯一sshd PID')
        # 只向本次RAM回执绑定的前台sshd发TERM，不按名称终止，不影响相机。
        early_final=vm.command('/bin/busybox kill -TERM '+pid_match[1].decode()+'; sleep 3; cat '+early_ram+'/result '+early_ram+'/child-result; /usr/bin/openssl dgst -sha256 /etc/passwd /etc/nsswitch.conf /etc/ssh/sshd_config',timeout=15)
        (out/'early-exit.txt').write_bytes(early_launch+early_final)
        early_text=early_final.replace(b'\r',b'')
        if not re.search(rb'A7R5_PRIVATE_RESULT '+early['run_id'].encode()+rb' code=87 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1\n',early_text):raise ValueError('提前退出的父清理终态不符')
        if not re.search(rb'PRIVATE_RESULT code=116 errno=\d+ sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1 local_banner_verified=1\n',early_text):raise ValueError('提前退出未被明确记录为失败并清理')
        for raw in files.values():
            if hashlib.sha256(raw).hexdigest().encode() not in early_text:raise ValueError('提前退出后外部原件变化')
        result['early_exit_clean_verified']=True
        result.update(status="passed", parent_account_nss_config_unchanged=True,
                      private_var_not_visible_to_parent=True, descendant_cleanup_verified=True,
                      listener_absence_verified=True, live_device_tested=False)
    except BaseException as exc:
        result["error"]=type(exc).__name__+": "+str(exc)
        if not getattr(vm,"ssh_relay_active",False):
            try:(out/"diagnostic.txt").write_bytes(vm.command("cat "+ram+"/result "+ram+"/child-result "+ram+"/diagnostic; :",timeout=8))
            except Exception as error:result["diagnostic_error"]=str(error)
        raise
    finally:
        result["cleanup"]=vm.close()
        result["runtime_inputs_unchanged"]={k:build.sha(p) for k,p in verified_inputs().items()}==before
        result["console_sha256"]=build.sha(vm.console)
        (out/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(dict(output=str(out),status=result["status"],error=result.get("error"),cleanup=result["cleanup"]),ensure_ascii=False),flush=True)


if __name__=="__main__":main()
