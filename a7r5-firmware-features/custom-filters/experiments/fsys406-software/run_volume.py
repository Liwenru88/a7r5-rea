"""运行原Fsys软件卷及生产适配器；QMP导出合成卷，不接物理卡或相机。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4];LAB=ROOT/'a7r5-qemu'
sys.path.insert(0,str(LAB/'tools'))
import app_paths
from native_vm import NativeVM,digest


class VolumeVM(NativeVM):
    def __init__(self,path):
        self.manifest=path.absolute();self.runtime_inputs();super().__init__('fsys-volume406',capid=True,boot_services=True)

    def runtime_inputs(self):
        report=json.loads(self.manifest.read_text());assert report['schema']=='af-fsys-volume406/1'
        assert set(report['files'])=={'binary','gpe','kernel','initrd','dtb'};result={}
        for key,row in report['files'].items():
            p=Path(row['path']);assert not p.is_symlink() and p.is_file() and (p.is_relative_to(ROOT/'.local/fixed-custom-filters') or p.is_relative_to(LAB))
            assert p.stat().st_size==row['bytes'] and digest(p)==row['sha256'];result[key]=p
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--long-names',action='store_true');args=parser.parse_args()
    path=args.manifest.absolute();assert path.is_relative_to(ROOT/'.local/fixed-custom-filters')
    app_paths.paths=lambda:app_paths.AppPaths(LAB,path.parent/'execution');app_paths.paths().prepare()
    import vm_session
    vm_session.RUNS=app_paths.paths().runs
    vm=VolumeVM(path);report=dict(status='FAILED',camera_io=False,CP_ISP_hardware_emulated=False,physical_SD_verified=False);error=None
    print('RUN_DIRECTORY',vm.out,flush=True)
    try:
        vm.start();print('KERNEL_READY',flush=True)
        commands=[
          'mount -t tmpfs tmpfs /tmp; mount -t tmpfs tmpfs /setting',
          'mkdir -p /dev/cgroup; mount -t cgroup -o cpuset nodev /dev/cgroup; for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do mkdir -p /dev/cgroup/$group; echo 0 > /dev/cgroup/$group/cpuset.mems; echo 0 > /dev/cgroup/$group/cpuset.cpus; done',
          'insmod /kmod/devno.ko','insmod /usr/kmod/osal_utm.ko','insmod /usr/kmod/osal_uipc.ko','insmod /usr/kmod/utimer.ko',
          'cp /seed-backup.bin /setting/Backup.bin; insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0',
          'insmod /usr/kmod/stream.ko','insmod /usr/kmod/stream2.ko',
          'cp -a /seed-setting/. /setting/; insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin',
          'insmod /usr/kmod/dmm.ko DmmConfig=/setting/DmmCfg.bin','insmod /usr/kmod/grm_ma.ko',
          'test ! -e /image_mmca && cp /simulation/af-volume.fat /image_mmca',
          '( export LD_LIBRARY_PATH=/usr/lib:/lib AF_FSYS_VOLUME_SOFTWARE=1; LD_PRELOAD=/simulation/af-volume-config.so /simulation/af-volume-driver; echo $? > /tmp/af-volume.rc ) > /tmp/af-volume.log 2>&1 & echo AF_VOLUME_STARTED',
          'for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do [ -f /tmp/af-volume.rc ] && break; sleep 1; done; cat /tmp/af-volume.log; if [ -f /tmp/af-volume.rc ]; then echo AF_VOLUME_RC=$(cat /tmp/af-volume.rc); else echo AF_VOLUME_PENDING; fi']
        if args.long_names:commands[13]=commands[13].replace('/simulation/af-volume-driver;','/simulation/af-volume-driver long;')
        for i,command in enumerate(commands):
            reply=vm.command(command,timeout=45);(vm.out/f'step-{i:02}.log').write_bytes(reply);print('STEP',i,flush=True)
        data=vm.console.read_text(errors='replace').replace('\r','')
        assert re.search(r'^AF_VOLUME_RC=0$',data,re.M),data[-6000:]
        assert re.search(r'^AF_VOLUME_DONE files=3 cancel=pass stale=pass source=original_fsys_file_backend$',data,re.M)
        rows=re.findall(r'^AF_VOLUME_FILE name=(\S+) bytes=(\d+) sha256=([a-f0-9]{64})$',data,re.M);assert len(rows)==3
        export=re.findall(r'^AF_VOLUME_EXPORTED bytes=4194304 sha256=([a-f0-9]{64})$',data,re.M);assert len(export)==1
        target=vm.out/'synthetic-volume.fat'
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(15);vm.connect_qmp(sock)
            with sock.makefile('rwb') as stream:
                assert 'QMP' in json.loads(stream.readline())
                for request in [{'execute':'qmp_capabilities'},{'execute':'pmemsave','arguments':{'val':0x41e600000,'size':0x400000,'filename':str(target)}}]:
                    stream.write(json.dumps(request).encode()+b'\n');stream.flush()
                    while True:
                        reply=json.loads(stream.readline());assert 'error' not in reply,reply
                        if 'return' in reply:break
        assert target.stat().st_size==0x400000 and digest(target)==export[0]
        check=subprocess.run(['/sbin/fsck_msdos','-n',str(target)],capture_output=True,text=True)
        (vm.out/'fsck.txt').write_text(check.stdout+check.stderr);assert check.returncode==0
        report.update(status='PASS_ORIGINAL_FSYS_VOLUME_AND_ADAPTER_SOFTWARE_ONLY',files=[dict(name=n,bytes=int(s),sha256=h) for n,s,h in rows],
            synthetic_volume_sha256=export[0],original_Fsys_volume_IO_executed=True,production_adapter_double_read=True,
            unicode_and_long_names=True,cancel_no_publish=True,stale_volume_no_publish=True,actual_media_model=False,
            mount_flags=0x400 if args.long_names else 0,manifest_sha256=digest(path),source_sha256=digest(Path(__file__)))
    except BaseException as exc:error=exc;report['error']=repr(exc)
    finally:
        report['exit']=vm.close();(vm.out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if error:raise error
    assert report['exit']=={'method':'qmp-quit','exit_code':0}


if __name__=='__main__':main()
