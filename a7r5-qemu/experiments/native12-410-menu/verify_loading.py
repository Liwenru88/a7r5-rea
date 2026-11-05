"""独立检查BIN投影、生产AP名称状态、真实CP传输及拒绝/复用行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib
from environment import LAB,BIN_SHA,verified,save
from cp_service import CPService


def expected(raw):
    if hashlib.sha256(raw).hexdigest()!=BIN_SHA:raise ValueError('原BIN身份不符')
    names=[];compact={}
    for index in range(12):
        record=raw[128+2452*index:128+2452*(index+1)]
        slot=struct.unpack_from('<I',record)[0]
        if slot!=index+1:raise ValueError('记录槽位不符')
        names.append(dict(number=slot,short=record[4:28].split(b'\0')[0].decode(),full=record[28:92].split(b'\0')[0].decode()))
        # 用v4文件布局独立展开CP线上格式，不调用生产编解码器。
        value=bytearray(2392);value[:24]=record[4:28];value[32:1172]=record[92:1232]
        struct.pack_into('<I',value,1172,1);value[1176:2391]=record[1232:2447];compact[slot]=bytes(value)
    return names,compact


def inspect(run,manifest):
    record=json.loads(manifest.read_text());inputs=verified(record);loading=verified({'files':record['loading_inputs']})
    raw=loading['bin'].read_bytes();names,compact=expected(raw)
    result=json.loads((run/'native410-menu.json').read_text());baseline=result['loading_state']
    messages=json.loads((run/'cp/messages.json').read_text())
    scenario=result['scenario']
    if json.loads((run/'exit.json').read_text())!={'method':'qmp-quit','exit_code':0}:raise ValueError('AP未正常退出')
    cp_close=json.loads((run/'cp/close.json').read_text())
    if cp_close['exit_code'] or cp_close['method']!='semihosting-SYS_EXIT_EXTENDED':raise ValueError('CP未正常退出')
    for r in messages:
        p=bytes.fromhex(r['request']);ack=bytes.fromhex(r['reply'])
        if not ack:raise ValueError('真实CP未返回ACK')
        if p[0]==0xe7:
            if len(ack)!=44 or struct.unpack_from('<I',ack,36)[0]:raise ValueError('实际传输ACK拒绝')
            if p[2]==2 and p[32:]!=compact[struct.unpack_from('<I',p,16)[0]]:raise ValueError('CP参数与BIN投影不一致')
    if scenario in ('valid','bad-select-ack'):
        if baseline['available_mask']!=4095 or baseline['names']!=names:raise ValueError('名称未完整发布')
        if baseline['AP_worker_words'][14:17]!=[29552,30,4095]:raise ValueError('原AP读取／解码状态不符')
        if baseline['AP_transfer_words'][1:6]!=[3,0,5,1,14]:raise ValueError('原AP没有精确完成十四次传输')
        puts=[r for r in messages if r['request'].startswith('e70302')]
        seals=[r for r in messages if r['request'].startswith('e70303')]
        if len(puts)!=12 or len(seals)!=1 or struct.unpack_from('<I',bytes.fromhex(seals[0]['reply']),40)[0]!=4095:raise ValueError('CP十二项未完整封存')
        storage=(run/'internal-storage.log').read_bytes()
        if hashlib.md5(raw).hexdigest().encode()+b'  /usr/data/lut/R5NATIVE.BIN' not in storage:raise ValueError('内部文件回读摘要不符')
    else:
        if baseline['available_mask'] or any(x['short'] or x['full'] for x in baseline['names']):raise ValueError('失败加载发布了配置名称')
        if scenario=='bad-ack' and any(r['request'].startswith('e703') for r in messages):raise ValueError('错误容量ACK仍开始了参数传输')
        if scenario=='invalid-bin' and any(struct.unpack_from('<I',bytes.fromhex(r['request']),16)[0] for r in messages if r['request'].startswith('e801')):raise ValueError('损坏BIN被当成有效配置')
    report=dict(status='QEMU_CONFIG_LOADING_VERIFIED',scenario=scenario,available_mask=baseline['available_mask'],names=baseline['names'],
        CP_messages=len(messages),CP_heap_allocations=max((r['heap_allocations'] for r in messages),default=0),
        AP_sha256=record['AP_sha256'],CP_sha256=record['CP_sha256'],source_DAT_sha256=record['DAT_sha256'],
        camera_io=False,full_CP_RTOS_emulated=False,ISP_image_acceptance=False,AP_CP_lifecycle='private simulated SD/storage/OSAL; real AP worker and CP receiver instructions')
    save(run/'loading-audit.json',report)
    return report,inputs,loading,messages


def receiver_regression(inputs,loading,messages,output):
    output.mkdir(mode=0o700)
    cp=CPService(inputs,loading['cp'],loading['receiver'],output/'cp')
    requests=[bytes.fromhex(r['request']) for r in messages if bytes.fromhex(r['request'])[0] in (0xe8,0xe7)]
    if len(requests)!=15:raise ValueError('主流程不是一次探测及十四次传输')
    checks=[]
    try:
        bad=bytearray(requests[0]);bad[28]^=1
        if cp.consume(bad):raise ValueError('损坏探测被接受')
        checks.append('损坏容量探测不分配堆、不返回成功')
        for i,p in enumerate(requests):
            if i==2:
                bad=bytearray(p);bad[-1]^=1;reply=cp.consume(bad)
                if not reply or struct.unpack_from('<I',reply,36)[0]==0 or struct.unpack_from('<I',reply,40)[0]!=0:raise ValueError('损坏PUT仍发布槽位')
                checks.append('损坏参数PUT拒绝，received_mask保持0')
                # 拒绝可能终止事务。用原生产BEGIN重新开始同一未发布代际。
                # 下一段使用全新CP检验完整有效主流程，不伪造重试兼容性。
                break
            reply=cp.consume(p)
    finally:cp.close()
    cp=CPService(inputs,loading['cp'],loading['receiver'],output/'reuse')
    try:
        for p in requests:
            reply=cp.consume(p)
            if not reply:raise ValueError('有效主流程没有ACK')
            if p[0]==0xe7 and struct.unpack_from('<I',reply,36)[0]:raise ValueError('有效主流程被拒绝')
        before=cp.messages[-1]['heap_allocations'];reply=cp.consume(requests[1])
        if struct.unpack_from('<III',reply,32)!=(0x35424c53,0,4095) or cp.messages[-1]['heap_allocations']!=before or before!=1:raise ValueError('相同配置BEGIN没有复用已封存代际')
        checks.append('十二项有效主流程封存；相同mask/CRC复用且堆分配保持1次')
    finally:cp.close()
    save(output/'verification.json',dict(checks=checks,passed=True,camera_io=False))
    return checks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--receiver-regression',type=Path)
    a=p.parse_args();r,inputs,loading,messages=inspect(a.run.absolute(),a.manifest.absolute())
    if a.receiver_regression:r['receiver_regression']=receiver_regression(inputs,loading,messages,a.receiver_regression.absolute())
    print(json.dumps(r,ensure_ascii=False,indent=2))
