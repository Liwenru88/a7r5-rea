"""单次USB事务；SSH上传与启动共享通道、失步标志和唯一退出许可。"""
import base64
import json
import os
from pathlib import Path
import shutil
from common import (ROOT, SOURCE_SHA, TARGET_SHA, PARTITION_BYTES, config, digest, load,
                    progress, render_template, safe, save, sha, write_payload)
import host
from policy import pre_service_failure
from transport import Channel
from capture_operation import Operation as CaptureOperation
from work_probe import Operation as WorkProbeOperation
from trust_operation import Operation as TrustOperation
from ssh_operation import Operation as SSHOperation


class JoinedSSH:
    def __init__(self, package, channel_factory=Channel):
        self.load = SSHOperation(package, 'load-once')
        self.start = SSHOperation(package, 'start-once')
        self.current = None
        self.channel = None
        self.factory = channel_factory
        self.safe_to_stop = False
        self.output = None

    def interface_checked(self, device, interface):
        for name, operation in (('load', self.load), ('start', self.start)):
            operation.output = self.output/name
            operation.output.mkdir(exist_ok=True, mode=0o700)
            operation.interface_checked(device, interface)

    def guard_packet(self, packet):
        if self.current is None:raise PermissionError('没有当前阶段')
        self.current.guard_packet(packet)

    def shared_channel(self, driver, operation, log):
        if self.channel is None:
            self.channel = self.factory(driver, operation, log)
        elif not self.channel.usable or self.channel.driver is not driver:
            raise PermissionError('传输失步或设备变化，禁止进入下一阶段')
        self.channel.operation = operation
        return self.channel

    def __call__(self, driver, output, log, report):
        self.output = Path(output);self.safe_to_stop = False
        phases = []
        try:
            for name, operation in (('load', self.load), ('start', self.start)):
                self.current = operation
                phase = dict(name=name);phases.append(phase)
                operation.channel_factory = self.shared_channel
                progress('上传并核对SSH程序' if name == 'load' else '启动SSH并核对公钥、监听回执与心跳')
                operation(driver, self.output/name, log, phase)
                if not operation.safe_to_stop or not phase.get('protocol_gate_passed'):
                    raise RuntimeError('SSH阶段不完整')
                save(self.output/(name+'-phase.json'), dict(phase, intermediate_USB_exit=False))
            if sum(p.get('fixed_writes_attempted', 0) for p in phases) != 5 or sum(p.get('trigger_attempts', 0) for p in phases) != 1:
                raise ValueError('SSH合并事务写入或触发次数不符')
            if not self.channel.usable:raise ValueError('最终通道未同步')
            self.safe_to_stop = True
            report.update(protocol_gate_passed=True, preload_unchanged=True, service_ready=True)
        finally:
            report.update(phases=phases, fixed_writes_attempted=sum(p.get('fixed_writes_attempted', 0) for p in phases),
                          trigger_attempts=sum(p.get('trigger_attempts', 0) for p in phases), preload_written=False,
                          debug_commands_sent=False, combined_upload_and_start=True)
            report['ssh_start_state']=('ready_verified' if report.get('service_ready') else
                'unconfirmed' if report['trigger_attempts'] else 'not_attempted')
            if phases:
                for key in ('upload_stage','upload_path','upload_failure'):
                    if key in phases[-1]:report[key]=phases[-1][key]


def package_base(job, run, baseline):
    package = job/'package';package.mkdir(mode=0o700)
    (package/'materials').mkdir(mode=0o700)
    cfg = config(run, baseline)
    return package, cfg


def prepare_capture(job, run, baseline, *, probe=False):
    template='work-probe.so' if probe else 'capture.so'
    if load(ROOT/'templates.json')['files'].get(template,{}).get('control_layout')!='ram-v2':
        raise ValueError('捕获模板不支持RAM控制文件，请重新构建客户端；未开始上传')
    package, cfg = package_base(job, run, baseline)
    cfg.update(capture_path='/tmp_wbshd/a7r5-capture-'+run+'/partition.bin',
               capture_control_layout='ram-v2',
               expected_output_begin='A7R5_CAPTURE_BEGIN '+run+'\n', expected_output_end='A7R5_CAPTURE_END '+run+'\n')
    if not probe:
        if load(ROOT/'templates.json')['files'][template].get('capture_format')!='ram-16k-v1':
            raise ValueError('捕获模板分块布局不符，请重新构建客户端；未开始上传')
        cfg['capture_format']='ram-16k-v1'
        if load(ROOT/'templates.json')['files'].get('capture-cleanup.so',{}).get('cleanup_policy')!='verified-current-ram-v2':
            raise ValueError('缺少本次RAM副本清理模板，请重新构建客户端；未开始上传')
        cfg['capture_cleanup_policy']='verified-current-ram-v2'
        write_payload(package/'materials/capture-cleanup.so',render_template('capture-cleanup.so',run))
    save(package/'config.json', cfg)
    write_payload(package/'materials/libJit.so', render_template(template, run))
    write_payload(package/'materials/ticket.bin', ('A7R5_LIBJIT '+run+'\n').encode())
    return package, (WorkProbeOperation if probe else CaptureOperation)(package)


def prepare_update(job, run, baseline, backup_manifest, *, force=False):
    if type(force) is not bool:raise ValueError('强制模式标记必须为布尔值')
    if force:
        template=load(ROOT/'templates.json')['files'].get('trust-force.so',{})
        if (template.get('control_layout')!='ram-v2' or template.get('force_policy')!='fixed-258-v1'
                or template.get('readback_format')!='planned-sectors-v2'
                or template.get('resource_policy')!='planned-sectors-32m-v1'):
            raise ValueError('缺少独立强制信任模板，请重新构建客户端')
        package,cfg=package_base(job,run,baseline);ram='/tmp_wbshd/a7r5-trust-'+run
        cfg.update(force_install=True,trust_control_layout='ram-v2',trust_readback_format='planned-sectors-v2',
            trust_resource_policy='planned-sectors-32m-v1',ram_dir=ram,
            journal_path=ram+'/journal',readback_path=ram+'/partition.logical',partition_bytes=PARTITION_BYTES,
            expected_output_begin='A7R5_TRUST_BEGIN_'+run+'\n',expected_output_end='A7R5_TRUST_END_'+run+'\n')
        save(package/'config.json',cfg)
        write_payload(package/'materials/libJit.so',render_template('trust-force.so',run))
        write_payload(package/'materials/ticket.bin',('A7R5_LIBJIT '+run+'\n').encode())
        for name in ('write-plan.json','trust-sectors.json'):shutil.copyfile(ROOT/name,package/'materials'/name)
        return package,TrustOperation(package)
    if backup_manifest is None:raise ValueError('请选择真实原厂备份记录，或明确选择强制安装')
    record = load(backup_manifest)
    if (record.get('kind') != 'backup' or not record.get('task_complete') or record.get('device_IO') is not True
            or record.get('simulation') is not False or record.get('backup_sha256') != SOURCE_SHA):
        raise ValueError('需要已完成且匹配原厂4.00前像的真实备份记录')
    before = safe(record['backup_file'], file=True).read_bytes()
    sectors = load(ROOT/'trust-sectors.json')
    if len(before) != PARTITION_BYTES or digest(before) != SOURCE_SHA:raise ValueError('备份文件变化或未适配')
    candidate = bytearray(before)
    for row in sectors['rows']:
        at = row['offset'];old = base64.b64decode(row['before'], validate=True);new = base64.b64decode(row['after'], validate=True)
        if len(old) != 512 or len(new) != 512 or candidate[at:at+512] != old:raise ValueError('备份扇区前像不符')
        candidate[at:at+512] = new
    if digest(candidate) != TARGET_SHA:raise ValueError('完整候选摘要不符')
    package, cfg = package_base(job, run, baseline)
    # 当前支持的SSH基础为原厂512换行；两种已知预加载分别有独立载荷。
    preload_name = record['preload_name']
    values = dict(cfg['preload_baselines'])
    if preload_name not in values:raise ValueError('备份预加载类型未适配')
    if load(ROOT/'templates.json')['files'].get('trust-'+preload_name+'.so',{}).get('control_layout')!='ram-v2':
        raise ValueError('信任更新模板不支持RAM控制文件，请重新构建客户端；未开始上传')
    ram = '/tmp_wbshd/a7r5-trust-'+run
    cfg.update(trust_control_layout='ram-v2',expected_preload_hex=values[preload_name], ram_dir=ram, journal_path=ram+'/journal',
               readback_path=ram+'/partition.logical', partition_bytes=PARTITION_BYTES,
               candidate_sha256=TARGET_SHA, source_sha256=SOURCE_SHA,
               expected_output_begin='A7R5_TRUST_BEGIN_'+run+'\n', expected_output_end='A7R5_TRUST_END_'+run+'\n')
    save(package/'config.json', cfg)
    write_payload(package/'materials/libJit.so', render_template('trust-'+preload_name+'.so', run))
    write_payload(package/'materials/ticket.bin', ('A7R5_LIBJIT '+run+'\n').encode())
    write_payload(package/'materials/candidate.logical.img', candidate)
    shutil.copyfile(ROOT/'write-plan.json', package/'materials/write-plan.json')
    return package, TrustOperation(package)


def prepare_ssh(job, run, baseline, password_hash=None, *, active=None):
    package, cfg = package_base(job, run, baseline)
    save(package/'config.json', cfg)
    prefix = '/tmp/jiritsu/a7r5-ljssh-'+run
    uploads = {prefix+'.service':'service.arm64', prefix+'.session':'session.arm64', prefix+'.sftp':'sftp-server.arm64'}
    for name in ('service.arm64', 'session.arm64', 'libJit.so'):
        # 停服不上传执行材料；结构仍从固定模板构造，口令哈希不影响停止请求。
        if active is not None and password_hash is None:password_hash = load(ROOT/'templates.json')['hash_marker']
        write_payload(package/'materials'/name, render_template('ssh-'+name, run, password_hash))
    shutil.copyfile(ROOT/'templates/sftp-server.arm64', package/'materials/sftp-server.arm64')
    write_payload(package/'materials/ticket.bin', ('A7R5_SSH_START '+run+'\n').encode())
    save(package/'materials/build.json', dict(run_id=run, prefix=prefix, ram_directory='/tmp_network/a7r5-libjit-ssh-'+run,
                                             ttl_seconds=0, uploads=uploads, autostart=False))
    if active is not None:
        previous = package/'.state/start-once';previous.mkdir(parents=True, mode=0o700)
        write_payload(previous/'host-public-key', base64.b64decode(active['host_public_key'], validate=True))
        return package, SSHOperation(package, 'stop-once')
    return package, JoinedSSH(package)


def run(request, job, *, session_module=None, host_module=host):
    # 实机入口只接受已经提权的固定动作；测试从内部显式注入协议替身。
    if os.geteuid() != 0 and session_module is None:raise PermissionError('缺少macOS管理员授权')
    run_id = request['run_id'];kind = request['kind']
    if kind not in ('backup', 'update', 'ssh_start', 'ssh_stop'):raise ValueError('设备动作无效')
    force=request.get('force_install',False)
    if type(force) is not bool or force and kind!='update':raise ValueError('强制模式仅用于信任安装')
    before = host_module.snapshot(job, 'initial')
    if before.get('kind') != 'ordinary' or before.get('model') != 'ILCE-7RM5' or not before.get('media') or not before.get('drivers'):
        raise ValueError('未识别到A7R5的MSC连接；操作未开始，请在机身选择MSC，必要时重新拔插')
    if kind == 'backup':package, operation = prepare_capture(job, run_id, before)
    elif kind == 'update':package, operation = prepare_update(job, run_id, before, request.get('backup_manifest'),force=force)
    elif kind == 'ssh_start':package, operation = prepare_ssh(job, run_id, before, request['password_hash'])
    else:
        active = request['active'];run_id = active['run_id']
        # 本次端口从实时MSC身份取得；停止仍核对原实例的会话号及主机公钥。
        package, operation = prepare_ssh(job, run_id, before, active=active)
    if session_module is None:
        from system_dump import session as session_module
    save(job/'baseline.json', before)
    (job/'ATTEMPT_LOCK').mkdir(mode=0o700)
    operation.output = job/'session'
    progress('正在执行，请保持供电与USB连接，不要拔插、关机或切换模式')
    report = session_module.run_session(operation.output, 'libusb', _operation=operation)
    save(job/'session-result.json', report)
    expected = {'backup':(4, 2), 'update':(2, 1), 'ssh_start':(5, 1), 'ssh_stop':(1, 0)}[kind]
    operation_complete = (not report.get('failure') and report.get('protocol_gate_passed') is True
                and report.get('preload_unchanged') is True and report.get('fixed_writes_attempted') == expected[0]
                and report.get('trigger_attempts') == expected[1] and report.get('service_stop_attempts') == 1)
    if kind=='update' and getattr(operation,'sector_readback',False):
        verified=(all(report.get(key) is True for key in ('native_write_complete','native_full_readback_verified',
            'native_reopened_readback_verified','planned_sector_readback_verified'))
            and report.get('trust_readback_format')=='planned-sectors-v2' and report.get('trust_readback_scope')=='planned-sectors'
            and report.get('trust_readback_completed_chunks')==report.get('trust_readback_total_chunks')==9
            and report.get('trust_readback_bytes')==132096 and report.get('patch_sectors')==258)
    else:
        verified=report.get({'backup':'capture_verified','update':'complete_partition_readback_verified',
            'ssh_start':'service_ready','ssh_stop':'service_ended'}[kind]) is True
    operation_complete=operation_complete and verified
    if kind=='backup':operation_complete=operation_complete and report.get('capture_cleanup_verified') is True
    complete = operation_complete and report.get('service_stop_result') == 'returned'
    value = dict(kind=kind, run_id=run_id, task_complete=bool(complete), device_IO=True, simulation=session_module.__name__ != 'system_dump.session',
                 USB_recovered=False, screen_confirmation_pending=True, can_replug=bool(complete), automatic_retry=False,
                 baseline=before, report=report)
    if kind=='update':value['force_install']=force
    if kind == 'backup' and report.get('capture_verified') is True and report.get('backup_persisted') is True:
        raw = job/'session/partition1.logical.bin'
        if raw.stat().st_size != PARTITION_BYTES or sha(raw) != report['capture_sha256']:raise ValueError('完整备份复核失败')
        value.update(backup_complete=True, backup_sha256=sha(raw), backup_relative='session/partition1.logical.bin',
                     trust_state={SOURCE_SHA:'original', TARGET_SHA:'installed'}.get(sha(raw), 'unsupported'),
                     preload_name=next(name for name, text in load(package/'config.json')['preload_baselines'] if text == report['expected_preload_hex']))
    def observe_recovery():
        try:
            proof = host_module.observe(before, lambda label, timeout=5:host_module.snapshot(job, label, timeout, before['location_id']))
            save(job/'host-recovery.json', proof);value['USB_recovered'] = proof['recovered']
        except Exception as error:
            value['recovery_error'] = str(error)
    stalled = (operation_complete and report.get('service_stop_result') == 'stalled'
               and report.get('service_stop_backend_error_code') == -9)
    if stalled:
        # STOP的STALL不是成功回执；仅靠随后同端口MSC媒体和驱动稳定恢复确认退出。
        # 不补发STOP，不吞掉原错误，也不在机内验证失败时进入此分支。
        progress('机内验证已完成，退出请求返回STALL；仅观察MSC恢复，不重复发送请求')
        observe_recovery()
        if value['USB_recovered']:
            complete = True
            value.update(task_complete=True, can_replug=True, stop_confirmation='stable_msc_after_stall')
    if not complete:
        value['error'] = report.get('failure') or report.get('service_stop_error') or '任务、回执或唯一退出条件未全部通过；保留连接与现场，不重试'
        if pre_service_failure(value):
            value.update(recovery_kind='pre_service_failure', can_replug=True)
        return value
    if kind == 'ssh_start':
        value['host_public_key'] = base64.b64encode((job/'session/host-public-key').read_bytes()).decode()
    if not stalled:
        progress('机内操作与退出请求已完成，正在等待MSC恢复；如机身提示选择连接模式，请选择MSC')
        observe_recovery()
    return value
