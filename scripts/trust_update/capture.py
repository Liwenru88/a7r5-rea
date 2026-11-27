"""自动转存 cnflasha1：构建转存运行包、执行一次 0336 会话，并把完整镜像持久化到主机。

本模块只负责「把机内一号分区原样取回本机」这一段闭环：
1. 在相机 RAM 盘（/tmp_wbshd）内分块转存 25,100,288 字节，机内两次读取摘要必须一致；
2. 主机逐块下载并立即 fsync，完整镜像摘要必须等于机内整分区摘要；
3. 只有本机镜像已完整落盘并复核后，才允许删除机内 RAM 副本；
4. 任一步失败都保留现场，不自动重试、不发出第二次触发。
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

import builder
from operations import KitCaptureOperation, LibjitCaptureOperation
import usb_session

CAPTURE_OPERATIONS = {'libjit': LibjitCaptureOperation, 'kit': KitCaptureOperation}


class CaptureGateError(RuntimeError):
    """转存安全门控失败；携带完整机内报告，供上层写入 result.json 与恢复提示。"""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def progress(message):
    print(f'[trust-update] {message}', flush=True)


def stop_result_ok(report):
    """STOP 返回或内核报 -9（相机先重启 USB）都视为已请求退出服务通道。"""
    return report.get('service_stop_result') == 'returned' or (
        report.get('service_stop_result') == 'stalled'
        and report.get('service_stop_backend_error_code') == -9
    )


def verify_report(report, *, engine):
    """转存会话安全门控：任何一项不满足都不得进入信任写入。"""
    failures = []
    if report.get('failure'):
        failures.append(f'转存会话失败：{report["failure"]}')
    for key, message in (
        ('protocol_gate_passed', '机内转存协议门控未通过'),
        ('native_capture_complete', '机内转存未完成'),
        ('capture_verified', '本机下载镜像未通过整区摘要校验'),
        ('capture_cleanup_verified', '本次机内 RAM 副本清理未通过校验'),
        ('preload_unchanged', '/etc/ld.so.preload 未保持或未准确还原'),
    ):
        if report.get(key) is not True:
            failures.append(message)
    if report.get('capture_cleanup_state') != 'complete':
        failures.append(f'机内 RAM 副本清理状态为 {report.get("capture_cleanup_state")!r}')
    if report.get('capture_download_chunks') != report.get('capture_expected_chunks'):
        failures.append('本机分块下载数量与编译模板不一致')
    if report.get('partition_writes') != 0:
        failures.append('转存会话出现分区写入记录')
    if report.get('trigger_attempts') != 2:
        failures.append(f'转存+清理触发次数应为 2，实际为 {report.get("trigger_attempts")!r}')
    if report.get('fixed_writes_attempted') != 4:
        failures.append(f'转存+清理固定写入次数应为 4，实际为 {report.get("fixed_writes_attempted")!r}')
    if report.get('service_stop_attempts') != 1 or not stop_result_ok(report):
        failures.append(
            f'STOP 退出服务通道未按预期完成（attempts={report.get("service_stop_attempts")!r}, '
            f'result={report.get("service_stop_result")!r}）'
        )
    if engine == 'kit' and report.get('debug_commands_sent') is not True:
        failures.append('kit 转存未发出 DEBUG 触发')
    return failures


def run_capture(
    engine,
    baseline,
    out_dir,
    *,
    timeout_seconds=300,
    run_id=None,
    builder_mod=builder,
    session_fn=usb_session.run_session,
    fixture_target=None,
    log_fn=None,
):
    """构建转存运行包并执行一次完整会话；返回运行包、证据目录与机内报告。"""
    if engine not in CAPTURE_OPERATIONS:
        raise ValueError(f'不支持的引擎类型：{engine}')
    log = log_fn or progress
    out_dir = Path(out_dir)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_id = run_id or uuid.uuid4().hex
    package = out_dir / 'package'
    log(f'正在编译 cnflasha1 只读转存载荷 (引擎={engine}, 会话={run_id[:8]})...')
    builder_mod.build_capture_package(package, engine, run_id, baseline, fixture_target=fixture_target)
    operation = CAPTURE_OPERATIONS[engine](package)
    session_dir = out_dir / 'session'
    log('正在进入服务通道转存 cnflasha1 并在机内校验后清理本次 RAM 副本（请勿断电或拔插 USB）...')
    report = session_fn(session_dir, operation, timeout_seconds=timeout_seconds)
    failures = verify_report(report, engine=engine)
    if failures:
        raise CaptureGateError('自动转存未通过安全门控：' + '；'.join(failures), report)
    return {
        'run_id': run_id,
        'package': str(package),
        'session': str(session_dir),
        'report': report,
        'chunk_count': operation.chunk_count,
        'chunk_bytes': operation.chunk_bytes,
        'partition_bytes': operation.partition_bytes,
    }


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError('镜像写入失败')
        view = view[written:]


def _fsync_path(path, *, directory=False):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0) | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
        if hasattr(fcntl, 'F_FULLFSYNC') and not directory:
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    finally:
        os.close(fd)


def _write_json(path, payload):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        _write_all(fd, (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        os.fsync(fd)
        if hasattr(fcntl, 'F_FULLFSYNC'):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    finally:
        os.close(fd)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def persist_image(session_dir, image_path, *, report, run_id, chunk_count, chunk_bytes, partition_bytes):
    """把逐块下载结果合并成本机 cnflasha1 镜像，fsync + 读回复核后写回执。

    逐块文件在下载阶段已经各自 fsync，属于持久化证据；本函数只负责合并、复核与回执。
    合并或复核失败时删除本次未完成的镜像文件，避免留下看似可用的半成品。
    """
    session_dir = Path(session_dir)
    image_path = Path(image_path)
    expected_digest = report.get('capture_sha256')
    if not expected_digest:
        raise ValueError('转存报告缺少机内整分区摘要')

    receipt_path = image_path.with_name(image_path.name + '.receipt.json')
    manifest_path = image_path.with_name(image_path.name + '.chunks.json')
    manifest = []
    digest = hashlib.sha256()
    fd = os.open(image_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        for index in range(chunk_count):
            chunk_path = session_dir / f'partition-chunk-{index:03d}.bin'
            chunk = chunk_path.read_bytes()
            expected = min(chunk_bytes, partition_bytes - index * chunk_bytes)
            if len(chunk) != expected:
                raise ValueError(f'本机转存分块 {index} 长度不符：{len(chunk)} != {expected}')
            digest.update(chunk)
            manifest.append({'index': index, 'bytes': len(chunk), 'sha256': hashlib.sha256(chunk).hexdigest()})
            _write_all(fd, chunk)
        os.fsync(fd)
        if hasattr(fcntl, 'F_FULLFSYNC'):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    except BaseException:
        os.close(fd)
        image_path.unlink(missing_ok=True)
        raise
    os.close(fd)

    if image_path.stat().st_size != partition_bytes:
        image_path.unlink(missing_ok=True)
        raise ValueError(f'本机镜像长度不符：{image_path.stat().st_size} != {partition_bytes}')
    if digest.hexdigest() != expected_digest:
        image_path.unlink(missing_ok=True)
        raise ValueError('本机镜像流式摘要与机内整分区摘要不符')
    if _sha256_file(image_path) != expected_digest:
        image_path.unlink(missing_ok=True)
        raise ValueError('本机镜像落盘后重新读取摘要与机内整分区摘要不符')
    _fsync_path(image_path.parent, directory=True)

    receipt = {
        'run_id': run_id,
        'bytes': partition_bytes,
        'sha256': expected_digest,
        'chunks': chunk_count,
        'chunk_bytes': chunk_bytes,
        'file': image_path.name,
        'device': '/dev/cnflasha1',
        'device_number': '252:129',
        'capture_twice_matched': True,
        'preload_unchanged': True,
        'partition_writes': 0,
    }
    _write_json(receipt_path, receipt)
    _write_json(manifest_path, {'run_id': run_id, 'sha256': expected_digest, 'chunks': manifest})
    _fsync_path(receipt_path.parent, directory=True)

    # 镜像、回执与逐块清单均已落盘并复核，本机分块副本只是中间产物。
    for index in range(chunk_count):
        (session_dir / f'partition-chunk-{index:03d}.bin').unlink()
    return receipt
