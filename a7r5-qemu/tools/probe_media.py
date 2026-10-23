"""一次独立的原厂 Fsys 虚拟卡验收，不启动相机应用，不访问物理介质。"""
import argparse
import hashlib
import json
import re
import socket
import subprocess

from media_candidate import MediaVM
from virtual_fat import SIZE, MARKER, read_files, photo_payloads


def export(vm):
    target=vm.out/'media-disk.img'
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(15);vm.connect_qmp(sock)
        with sock.makefile('rwb') as stream:
            if 'QMP' not in json.loads(stream.readline()):raise RuntimeError('QMP 握手不符')
            for cmd in ({'execute':'qmp_capabilities'}, {'execute':'pmemsave','arguments':{'val':0x41e600000,'size':SIZE,'filename':str(target)}}):
                stream.write(json.dumps(cmd).encode()+b'\n');stream.flush()
                while True:
                    reply=json.loads(stream.readline())
                    if 'error' in reply:raise RuntimeError(str(reply['error']))
                    if 'return' in reply:break
    return target


def verify(vm,image):
    log=vm.console.read_text(errors='replace').replace('\r','')
    for mode in (0,1):
        if not re.search(r'^FSYS_FILE_TEST_DONE result=0 verify_only='+str(mode)+r'$',log,re.M):raise ValueError('原厂 Fsys 未完成')
    rows=re.findall(r'^FSYS_IMAGE_EXPORTED physical=0x41e600000 bytes=4194304 fnv1a64=([0-9a-f]{16})$',log,re.M)
    if len(rows)!=1:raise ValueError('导出收据缺失或重复')
    raw=image.read_bytes();value=14695981039346656037
    for b in raw:value=((value^b)*1099511628211)&((1<<64)-1)
    if len(raw)!=SIZE or value!=int(rows[0],16):raise ValueError('主客体镜像不一致')
    files=read_files(raw);payload=bytes((i*37+9)&255 for i in range(4096))
    expected={'/SEED.TXT':MARKER,'/QTEST/PROBE.BIN':payload,**photo_payloads()}
    if files!=expected:raise ValueError('文件集合或内容不符')
    for index,data in enumerate(photo_payloads().values(),1):
        fnv=14695981039346656037
        for byte in data:fnv=((fnv^byte)*1099511628211)&((1<<64)-1)
        marker=f'FSYS_PHOTO_READ index={index} bytes={len(data)} fnv1a64={fnv:016x}'
        if not re.search('^'+re.escape(marker)+'$',log,re.M):raise ValueError('原厂 Fsys 读取 JPEG 的长度或摘要不符')
    check=subprocess.run(['/sbin/fsck_msdos','-n',str(image)],capture_output=True,text=True)
    (vm.out/'fsck.txt').write_text(check.stdout+check.stderr)
    if check.returncode:raise ValueError('FAT 独立检查失败，见 fsck.txt')
    return {'status':'original-fsys-verified','disk_sha256':hashlib.sha256(raw).hexdigest(),
            'files':{n:{'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest()} for n,d in files.items()},
            'scope':'原厂 Fsys 独立进程写入、卸载、二次挂载读取；尚未接相机应用媒体通知或回放'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('candidate');args=parser.parse_args()
    vm=MediaVM(args.candidate);result={'status':'failed'};error=None
    print('MEDIA_RUN',vm.out,flush=True)
    try:
        vm.start()
        commands=['mount -t tmpfs tmpfs /tmp; mount -t tmpfs tmpfs /setting',
            'mkdir -p /dev/cgroup; mount -t cgroup -o cpuset nodev /dev/cgroup; for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do mkdir -p /dev/cgroup/$group; echo 0 > /dev/cgroup/$group/cpuset.mems; echo 0 > /dev/cgroup/$group/cpuset.cpus; done',
            'insmod /kmod/devno.ko','insmod /usr/kmod/osal_utm.ko','insmod /usr/kmod/osal_uipc.ko',
            'insmod /usr/kmod/utimer.ko','cp /seed-backup.bin /setting/Backup.bin; insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0',
            'insmod /usr/kmod/stream.ko','insmod /usr/kmod/stream2.ko',
            'cp -a /seed-setting/. /setting/; insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin',
            'insmod /usr/kmod/dmm.ko DmmConfig=/setting/DmmCfg.bin','insmod /usr/kmod/grm_ma.ko',
            'export LD_LIBRARY_PATH=/usr/lib:/lib; export A7C2_FILE_MEDIA_TEST=1; cp /simulation/media-template.fat /image_mmca',
            '( LD_PRELOAD=/simulation/media-config.so /simulation/fsys-file-test && LD_PRELOAD=/simulation/media-config.so /simulation/fsys-file-test verify && LD_PRELOAD=/simulation/media-config.so /simulation/fsys-file-test photos; echo $? > /tmp/media-test.rc ) > /tmp/media-test.log 2>&1 & echo MEDIA_TEST_STARTED',
            'while [ ! -f /tmp/media-test.rc ]; do sleep 1; done; cat /tmp/media-test.log; test "$(cat /tmp/media-test.rc)" = 0']
        for i,command in enumerate(commands):
            result['last_step']=i;print('MEDIA_STEP',i,flush=True);vm.command(command,timeout=90)
        result.update(verify(vm,export(vm)))
    except BaseException as exc:error=exc;result['error']=repr(exc)
    finally:
        result['exit']=vm.close();(vm.out/'media-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if error:raise error
    if result['exit']!={'method':'qmp-quit','exit_code':0}:raise RuntimeError('非正常 QMP 退出')


if __name__=='__main__':main()
