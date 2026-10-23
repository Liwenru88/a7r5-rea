#!/usr/bin/env python3
"""有界探测原厂应用启动链；不启用未经适配的菜单内存补丁。"""
import argparse
import hashlib
import json
import base64
import re
from vm_session import LAB, RUNS
from native_vm import NativeVM
from menu_live import snapshot_message, key_command, KEYS, FirmwareFault, FirmwareMonitor
from headless_osd_capture import decode_export, HEADER, METADATA
from menu_bridge import run_live, atomic_json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--without-bluetooth', action='store_true')
    parser.add_argument('--software-gpe', action='store_true')
    parser.add_argument('--capid', action='store_true')
    parser.add_argument('--boot-services', action='store_true')
    parser.add_argument('--model-trace', action='store_true')
    parser.add_argument('--gui-trace', action='store_true')
    parser.add_argument('--apply-menu', action='store_true')
    parser.add_argument('--initial-privacy', action='store_true', help='研究入口：从原菜单请求固定的首次隐私说明，不自动确认')
    parser.add_argument('--media-candidate', help='独立研究：仅加载已逐项核对的虚拟文件卡候选')
    parser.add_argument('--virtual-media-rm', action='store_true',help='仅在独立介质候选中启用受限 MediaRM 文件卡模型')
    parser.add_argument('--cp-init-capture', action='store_true', help='独立研究：观察完整初始化请求，经预留 RAM 导出，不替代 CP 回复')
    parser.add_argument('--keys', default='', help='仅接受逗号分隔的固定导航键名')
    parser.add_argument('--live-bridge', help='本机图形入口创建的独占控制目录')
    parser.add_argument('--candidate-inputs', choices=['delete-dial', 'fn-display', 'display-playback', 'option-help', 'all-inputs', 'neutral-fn', 'waited-fn', 'privacy-fn', 'privacy-disp', 'privacy-playback', 'initial-fn', 'initial-disp', 'initial-playback', 'initial-up', 'initial-inspect', 'initial-controls'], help='仅诊断固定候选；不启用实体控制')
    args = parser.parse_args()
    if args.boot_services and not args.capid:
        parser.error('--boot-services requires --capid')
    if args.apply_menu and not args.gui_trace:
        parser.error('--apply-menu requires --gui-trace')
    if args.gui_trace and not (args.software_gpe and args.capid and args.boot_services):
        parser.error('--gui-trace requires --software-gpe --capid --boot-services')
    keys = args.keys.split(',') if args.keys else []
    if len(keys)>20 or any(k not in KEYS for k in keys) or (keys and not args.apply_menu):
        parser.error('--keys requires menu and at most 20 whitelisted keys')
    if args.live_bridge and (keys or not args.apply_menu):
        parser.error('--live-bridge requires menu and cannot combine --keys')
    if args.candidate_inputs and (args.live_bridge or keys or not args.apply_menu):
        parser.error('--candidate-inputs requires menu and cannot combine live bridge or keys')
    if args.media_candidate and (args.live_bridge or args.candidate_inputs!='initial-playback' or not args.gui_trace):
        parser.error('--media-candidate requires exclusive --candidate-inputs initial-playback research')
    if args.virtual_media_rm and not args.media_candidate:
        parser.error('--virtual-media-rm requires verified --media-candidate')
    if args.cp_init_capture and (not args.virtual_media_rm or args.candidate_inputs!='initial-playback'):
        parser.error('--cp-init-capture requires --virtual-media-rm --candidate-inputs initial-playback')
    if args.gui_trace:
        from PIL import Image  # 启动虚拟器前确认宿主画面解码依赖。
    imdb = 'libIMDB-no-bluetooth.so' if args.without_bluetooth else 'libIMDB.so'
    if args.software_gpe and hashlib.sha256((LAB / 'sdk/lib/libgpe.so').read_bytes()).hexdigest() != '80fc6236379933f80c2689aa002e0cf39483da8d45e876705d2a427cd1a2a7d1':
        raise ValueError('GPE 库不匹配已验证布局')
    switches = ('export A7R5_APPLY_MENU=1; ' if args.apply_menu else '') + ('export A7R5_GUI_TRACE=1 MENU_HEADLESS_OSD=1 MENU_OSD_OBSERVE=1 QEMU_SOFTWARE_LZ77=1; ' if args.gui_trace else '') + ('export A7R5_MODEL_TRACE=1; ' if args.model_trace else '') + ('export A7R5_SKIP_BT_WRAPPER=1; ' if args.without_bluetooth else '') + (
        'export QEMU_SOFTWARE_GPE=1 QEMU_GPE_RGBA4444=1; ' if args.software_gpe else '') + (
        'export QEMU_CAPID_SERVICE=1; ' if args.capid else '') + (
        'export QEMU_SA_ADDRESS_SERVICE=1 QEMU_HDMI_FORMAT_SERVICE=1 QEMU_HDMI_PHOTO_SERVICE=1 '
        'QEMU_DISPLAY_INFO_SERVICE=1 QEMU_DMM_SERVICE=1; ' if args.boot_services else '')
    if args.candidate_inputs:
        switches += 'export A7R5_INPUT_RECEIPTS=1 A7R5_INPUT_TRACE=1; '
        if args.candidate_inputs.startswith('initial-'):
            switches += 'export A7R5_INITIAL_PRIVACY_NOTICE=1; '
    if args.cp_init_capture:
        switches += 'export A7R5_CP_INIT_CAPTURE=1; '
    if args.live_bridge:
        # 只注册固定页面请求；由客户端显式发起，不自动确认隐私说明。
        switches += 'export A7R5_INITIAL_PRIVACY_NOTICE=1 A7R5_INPUT_COMPLETIONS=1; '
    if args.initial_privacy:
        if not args.apply_menu or args.candidate_inputs or args.live_bridge or keys:
            parser.error('--initial-privacy requires standalone menu research')
        switches += 'export A7R5_INITIAL_PRIVACY_NOTICE=1; '
    if args.media_candidate:
        from media_candidate import MediaVM
        vm = MediaVM(args.media_candidate)
        switches += 'export A7C2_FILE_MEDIA_TEST=1 A7R5_NATIVE_MENU_REENTRY=1; '
        if args.virtual_media_rm:switches += 'export A7R5_VIRTUAL_MEDIA_RM=1; '
        if args.virtual_media_rm and args.model_trace:switches += 'export A7R5_MEDIA_WAIT_TRACE=1; '
    else:
        vm = NativeVM('app', capid=args.capid, boot_services=args.boot_services)
    if args.live_bridge:
        bridge = Path(args.live_bridge)
        if bridge.is_symlink() or bridge.resolve().parent != RUNS.resolve() or not re.fullmatch('ui-[0-9a-f]{32}', bridge.name):
            raise ValueError('控制目录越界')
        vm.live_bridge = bridge
        (bridge/'owned-run').write_text(str(vm.out)+'\n')
    result = {'backend': 'native', 'status': 'failed', 'model': 'ILCE-7RM5', 'firmware': '4.00', 'menu_verified': False,
              'without_bluetooth': args.without_bluetooth, 'software_gpe': args.software_gpe,
              'capid': args.capid, 'boot_services': args.boot_services}
    error = None
    media_model_records = b''
    try:
        vm.start()
        commands = [
            'mount -t tmpfs tmpfs /tmp; '
            'mount -t tmpfs tmpfs /setting; mount -t tmpfs tmpfs /tmp_wbshd',
            'mkdir -p /dev/cgroup; mount -t cgroup -o cpuset nodev /dev/cgroup; '
            'for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do '
            'mkdir -p /dev/cgroup/$group; echo 0 > /dev/cgroup/$group/cpuset.mems; echo 0 > /dev/cgroup/$group/cpuset.cpus; done',
            'insmod /kmod/devno.ko', 'insmod /usr/kmod/osal_utm.ko', 'insmod /usr/kmod/osal_uipc.ko',
            'insmod /usr/kmod/utimer.ko',
            'cp /seed-backup.bin /setting/Backup.bin; insmod /usr/kmod/backup.ko Backup_load=1 Backup_save=0',
            'insmod /usr/kmod/stream.ko', 'insmod /usr/kmod/stream2.ko',
            'cp -a /seed-setting/. /setting/; insmod /usr/kmod/osal_ulogio.ko ulogio_initfile=/setting/ulogio.bin',
            'insmod /usr/kmod/dmm.ko DmmConfig=/setting/DmmCfg.bin', 'insmod /usr/kmod/grm_ma.ko',
            '/simulation/seed-power-on 1', 'insmod /usr/kmod/upm.ko',
            'insmod /usr/kmod/udate.ko && /simulation/seed-date-clock', 'insmod /usr/kmod/kikilog.ko',
            'MENU_OBSERVE_SELFTEST=1 LD_PRELOAD=/simulation/menu-observe-a7r5-baseline.so /simulation/check-menu-observe',
            'mkdir -p /setting/updater /mnt; cp /simulation/firmware-version.dat4 /setting/updater/dat4; '
            'mknod /dev/ram1 b 1 1; ln -s /dev/ram1 /dev/nflasha1; '
            'dd if=/simulation/firmware-identity.fat of=/dev/ram1 bs=4096',
            f'cp /simulation/{imdb} /usr/lib/libIMDB.so; export LD_LIBRARY_PATH=/usr/lib:/lib; '
            'export QEMU_NO_CP_UPDATER=1; ' + switches +
            "LD_PRELOAD=/simulation/menu-observe-a7r5-baseline.so /usr/bin/bootin.elf 'target=qemu ' dmode=3 > /dev/ttyAMA0 2>&1 & echo A7R5_IM_PID=$!",
            'sleep 15; echo A7R5_LOADER_LOG_BEGIN; tail -n 350 /tmp/menu-load.log; echo A7R5_LOADER_LOG_END; ps; cat /proc/modules',
        ]
        if args.media_candidate:
            commands.insert(-2,'cp /simulation/media-template.fat /image_mmca')
            commands[-2]=commands[-2].replace('LD_PRELOAD=/simulation/menu-observe-a7r5-baseline.so /usr/bin/bootin.elf',
                'LD_PRELOAD=/simulation/media-config.so:/simulation/menu-observe-a7r5-baseline.so /usr/bin/bootin.elf')
        for index, command in enumerate(commands):
            if args.live_bridge and (Path(args.live_bridge)/'cancel').exists():
                raise RuntimeError('启动已取消，未继续客体初始化')
            result['last_step'] = index
            result['last_command'] = command
            print(f'APP_STEP {index}: {command}', flush=True)
            vm.command(command, timeout=60)
            if args.virtual_media_rm:
                observed=vm.console.read_text(errors='replace')
                if 'MEDIA_RM_UNSUPPORTED ' in observed or re.search(r'MEDIA_RM_NOTIFY [^\n]* result=-',observed):
                    raise RuntimeError('虚拟 MediaRM 出现未支持请求或通知失败，停止本次候选')
        if args.initial_privacy:
            from menu_bridge import capture
            capture(vm,'initial-privacy-before')
            vm.command('touch /tmp/a7r5-request-initial-privacy',timeout=30)
            vm.wait_native_screen(0x1e3)
            _, frame=capture(vm,'initial-privacy-notice')
            result['initial_privacy_frame']=frame
        elif args.candidate_inputs:
            if args.candidate_inputs != 'delete-dial':
                from function_batch import run
                result['input_batch'] = run(vm, profile=args.candidate_inputs)
                if args.media_candidate:
                    from media_playback_check import run as check_playback
                    result['media_playback_check']=check_playback(vm,result['input_batch'])
            else:
                from input_batch import run
                result['input_batch'] = run(vm)
        elif args.live_bridge:
            result.update(run_live(vm,args.live_bridge))
        elif args.gui_trace:
            result['snapshots'] = []
            for index, key in enumerate(['INITIAL']+keys):
                if key != 'INITIAL':
                    vm.command(key_command(key)+' && sleep 1', timeout=30)
                if b'OBS OSD_HEADLESS_FAILED ' in vm.console.read_bytes():
                    raise RuntimeError('图形消费者已停止，拒绝以旧帧验收')
                data = vm.command('/simulation/headless-osd-export', timeout=90)
                raw, info = decode_export(data)
                snapshot = snapshot_message(data)
                info['pixel_sha256'] = hashlib.sha256(raw[HEADER+METADATA:]).hexdigest()
                info['key'] = key
                name = f'snapshot-{index:02d}-{key}'
                (vm.out / (name+'.bin')).write_bytes(raw)
                (vm.out / (name+'.png')).write_bytes(base64.b64decode(snapshot['png']))
                (vm.out / (name+'.json')).write_text(json.dumps(info, indent=2)+'\n')
                result['snapshots'].append(info)
        result['status'] = 'application-probe-collected'
    except Exception as exc:
        error = exc
        result['error'] = str(exc)
    finally:
        # 协议拒绝/断言可能恰好插入图像传输；先在主机核对根因，禁止为诊断再次恢复客体。
        if args.media_candidate and error is not None and not isinstance(error,(TimeoutError,FirmwareFault)):
            try:FirmwareMonitor(vm.console).check()
            except (FirmwareFault,OSError) as fault:
                result['initial_error']=str(error)
                error=fault if isinstance(fault,FirmwareFault) else FirmwareFault('无法复核失败控制台，停止客体请求：'+str(fault))
                result['error']=str(error)
        # 串口超时后原命令可能未结束，禁止再向该串口追加诊断命令。
        if args.media_candidate and not isinstance(error,(TimeoutError,FirmwareFault)) and vm.process is not None and vm.process.poll() is None:
            try:
                media_model_records=vm.command('if [ -f /tmp/media-model.log ]; then cat /tmp/media-model.log; fi',timeout=30)
                (vm.out/'media-model.log').write_bytes(media_model_records)
                if b'MEDIA_RM_UNSUPPORTED ' in media_model_records or re.search(rb'MEDIA_RM_NOTIFY [^\n]* result=-',media_model_records):
                    raise RuntimeError('模型日志包含协议拒绝或通知失败，不能验收媒体')
                if args.virtual_media_rm and args.model_trace:
                    # 先采集固定的小表；线程清单较大，不能让它拖延描述符现场。
                    topology=vm.command('found=0; for p in /proc/[0-9]*/comm; do read name < $p; if [ "$name" = im.elf ]; then found=$((found+1)); pid=${p#/proc/}; pid=${pid%/comm}; echo MEDIA_PIN_APP_PID=$pid; /simulation/media-readmem /proc/$pid/mem 0x8e04030 1200 appFw.so pins && /simulation/media-readmem /proc/$pid/mem 0x59253d0 1200 appFw.so pins-template || break; fi; done; test "$found" = 1',timeout=20)
                    (vm.out/'media-pin-topology.log').write_bytes(topology)
                    if topology.count(b'PIN_TOPOLOGY_DONE count=50 readonly=1')!=2:
                        raise RuntimeError('没有取得两份完整拓扑表，不能以空输出验收')
                    vm.set_native_paused(True)
                    config=vm.command('test -n "$pid" && /simulation/media-readmem /proc/$pid/mem 0x89bd3d0 4 appFw.so && /simulation/media-readmem /proc/$pid/mem 0x89bd140 192 appFw.so',timeout=20)
                    (vm.out/'media-model-config.log').write_bytes(config)
                    vm.set_native_paused(True)
                if args.virtual_media_rm and args.model_trace:
                    pids=re.findall(rb'^MEDIA_PIN_APP_PID=([0-9]+)\r?$',topology,re.M)
                    if len(pids)!=1:raise RuntimeError('原厂应用进程身份不唯一')
                    pid=int(pids[0])
                    tasks=vm.command(f'echo MEDIA_APP_PID={pid}; cat /proc/{pid}/maps && echo MEDIA_MAPS_DONE',timeout=30)
                else:
                    tasks=vm.command("for p in /proc/[0-9]*/comm; do read name < $p; if [ \"$name\" = im.elf ]; then pid=${p#/proc/}; pid=${pid%/comm}; echo MEDIA_APP_PID=$pid; cat /proc/$pid/maps; fi; done",timeout=30)
                (vm.out/'media-app-tasks.log').write_bytes(tasks)
                if args.virtual_media_rm and args.model_trace:
                    # 仅取公共/媒体序列和四个子任务线程，不输出全部线程清单。
                    registers=vm.command('test -n "$pid" && count=0; for t in /proc/$pid/task/*/comm; do read name < "$t"; case "$name" in SeqQueueCommon|SeqQueueMedia|SeqThreadPool[0-3]) tid=${t%/comm}; tid=${tid##*/}; echo MEDIA_SEQUENCE_THREAD=$name:$tid; /simulation/media-regs "$tid" || break; count=$((count+1)); test "$count" -lt 6 || break;; esac; done; test "$count" = 6',timeout=30)
                    (vm.out/'media-sequence-registers.log').write_bytes(registers)
                    trace=vm.command('if [ -f /tmp/media-wait-trace.log ]; then cat /tmp/media-wait-trace.log; fi',timeout=15)
                    (vm.out/'media-wait-trace.log').write_bytes(trace)
                result['media_diagnostic_mode']=('original process maps, bounded model/future trace and six paused/detached sequence snapshots'
                    if args.virtual_media_rm and args.model_trace else 'original process maps only')
            except Exception as diagnostic_error:
                result['media_diagnostic_error']=str(diagnostic_error)
        if args.cp_init_capture and vm.process is not None and vm.process.poll() is None:
            try:
                from cp_request_capture import export_capture
                result['cp_init_capture']=export_capture(vm)
            except Exception as capture_error:
                result['cp_init_capture_error']=str(capture_error)
        result['cleanup'] = vm.close()
        if args.media_candidate:
            records=media_model_records if media_model_records else vm.console.read_bytes()
            imaging=b'\n'.join(line for line in records.splitlines() if line.startswith((b'MEDIA_IMAGING_',b'MEDIA_OUTPUT_',b'MEDIA_DATAFLOW_',b'MEDIA_NEXT_',b'MEDIA_FUTURE_',b'MEDIA_AUX_')))
            (vm.out/'media-imaging.log').write_bytes(imaging)
            result['media_candidate']=str(vm.candidate)
            result['media_application_verified']=False
        if args.live_bridge:
            path=Path(args.live_bridge)/'status.json'
            if path.exists():
                state=json.loads(path.read_text())
                if state['state']!='failed':
                    state.update(state='stopped' if result['cleanup']['exit_code']==0 else 'failed',cleanup=result['cleanup'])
                    atomic_json(path,state)
    result['console'] = str(vm.console)
    result['console_sha256'] = hashlib.sha256(vm.console.read_bytes()).hexdigest()
    (vm.out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    if error:
        raise error


if __name__ == '__main__':
    main()
