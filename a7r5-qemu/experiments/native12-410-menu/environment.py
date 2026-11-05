"""当前4.10独立菜单客体；固定输入，保留默认沙箱和清单。"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import re
import time
import socket
import struct

LAB=Path(__file__).resolve().parents[2]
ROOT=LAB.parent
sys.path.insert(0,str(LAB/'tools'))
from native_vm import NativeVM,dtb_properties,digest
from cpio_inputs import entries
from media_candidate import extract,patch_property

AP_SHA='25d79cffe07c44b094020d162e07ea2ac995cf929f1886dc5dbac6be78ba6520'
FONT_AP_SHA='a1e6a6472e200e5554426d54b73e1b031dfb2a75251a1854b124e223a08b68c5'
E4_AP_SHA='65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0'
UNIFIED_AP_SHA='e833e0290fe60207cc5d9d2b7a0a66b253f7ab0db99ed12afb2a0c47ca6f72f1'
UNIFIED_AP_SHAS=('5cd0f22949fc8134c59855ca91a5225722638bf9098fe3e1c74b61fdad603c43',UNIFIED_AP_SHA)
BIN_SHA='19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
CP_SHA='bb8eeaaeb9d13a4687605de6e01ccbe4adc500f595d2f8dbfe886eedd8a643d0'
DAT_SHA='1cc7ec6644c3a86a959341ff95b8904c633f12e8c9e4c6c58a0828568dcd4eb5'
DAT411_SHA='71cd3a680834b8559591509dc4dc76e3b1135b1657e22d593d0f7c6687e6cf1d'
BASE_GUEST_SHA='15089fc1b0a65dc7a198a2b11d9a56f6f55c746400e5cdc0122a9b878a768a53'


def save(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False);f.write('\n')


def fact(path):return dict(path=str(path.relative_to(LAB)),bytes=path.stat().st_size,sha256=digest(path))


def verified(record):
    result={}
    for name,row in record['files'].items():
        relative=Path(row['path']);path=LAB/relative
        if relative.is_absolute() or '..' in relative.parts or path.resolve()!=path.absolute() or fact(path)!=row:
            raise ValueError('客体材料身份／路径不符：'+name)
        result[name]=path
    return result


def build(output):
    output=output.absolute()
    if output.parent!=LAB/'build' or output.exists():raise ValueError('必须使用build下独立新目录')
    base=LAB/'build/aspect-guide406-20261026-01/guest-11'
    base_record=json.loads((base/'manifest.json').read_text());files=verified(base_record)
    if digest(files['initrd'])!=BASE_GUEST_SHA:raise ValueError('菜单支持客体不是固定guest11')
    module=ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined'
    current=module/'verification/2026-11-02-runtime/readback'
    manifest=json.loads((current/'manifest.json').read_text())
    if manifest['source']['sha256']!=DAT_SHA or digest(module/'releases/4.10/BODYDATA.DAT')!=DAT_SHA:
        raise ValueError('当前4.10包或解包来源不符')
    before=entries(files['initrd'])
    resources={};resource_replacements={}
    for name,row in manifest['components'].items():
        path=current/'components'/name
        if digest(path)!=row['sha256']:raise ValueError('解包组件身份不符：'+name)
        if name.startswith('usr/share/'):
            if before[name]['sha256']!=row['sha256']:resource_replacements[name]=path.read_bytes()
            resources[name]=row['sha256']
    ap=current/'components/usr/lib/appFw.so'
    cp=current/'components/cp/cpapp-b.bin'
    if not cp.is_file():
        candidates=[current/'components'/k for k,v in manifest['components'].items() if v['sha256']==CP_SHA]
        if len(candidates)!=1:raise ValueError('未找到唯一CP组件')
        cp=candidates[0]
    if digest(ap)!=AP_SHA or digest(cp)!=CP_SHA:raise ValueError('4.10组件不符')
    cp_name=[name for name in before if name.endswith('/cpapp-b.bin')]
    if len(cp_name)!=1:raise ValueError('旧客体CP文件不唯一')
    backup=current/'archive/0110_backup/SYSIPSX-DSLR/GL/CX89200_ALLLANG.bin'
    archive_rows={r['name']:r for r in manifest['entries']}
    if digest(backup)!=archive_rows['0110_backup/SYSIPSX-DSLR/GL/CX89200_ALLLANG.bin']['sha256']:
        raise ValueError('地区模板身份不符')
    output.mkdir(mode=0o700)
    replacements={**resource_replacements,'usr/lib/appFw.so':ap.read_bytes(),cp_name[0]:cp.read_bytes(),
                  'seed-backup.bin':backup.read_bytes(),'simulation/firmware-version.dat4':b'\x10\x04'}
    spec=importlib.util.spec_from_file_location('native410_cpio_rebuild',LAB/'tools/build-guest.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    candidate=output/'menu.cpio'
    builder.replace_cpio(files['initrd'],candidate,replacements)
    after=entries(candidate)
    changed=[k for k in before if before[k]!=after[k]]
    if before.keys()!=after.keys() or set(changed)!=set(replacements):raise ValueError('CPIO变更集合不符')
    for name,data in replacements.items():
        import hashlib
        if after[name]['sha256']!=hashlib.sha256(data).hexdigest():raise ValueError('替换回读不符')
        if before[name]['metadata']!=after[name]['metadata']:raise ValueError('CPIO元数据变化')
    raw=files['dtb'].read_bytes();props=dtb_properties(raw)
    bootargs=re.sub(rb'ramdisk_size=\d+',b'ramdisk_size='+str((candidate.stat().st_size+1023)//1024).encode(),props[('/chosen','bootargs')])
    raw=patch_property(raw,'/chosen','bootargs',bootargs)
    raw=patch_property(raw,'/chosen','linux,initrd-end',(0x440000000+candidate.stat().st_size).to_bytes(8,'big'))
    (output/'virt.dtb').write_bytes(raw)
    files.update(initrd=candidate,dtb=output/'virt.dtb')
    record=dict(schema='native12-410-menu/1',model='ILCE-7RM5',AP_sha256=AP_SHA,CP_sha256=CP_SHA,
        DAT_sha256=DAT_SHA,files={k:fact(v) for k,v in files.items()},
        base_initrd_sha256=BASE_GUEST_SHA,changed_entries=changed,resources_identical_to_package=resources,
        all_other_entries_identical=True,default_manifest_modified=False,camera_io=False,
        full_CP_emulated=False,filter_names_fixture=False,
        adaptations=base_record['simulation_adaptations'])
    record['adaptations']['firmware_identity']['source']={'major':4,'minor':10,'model':0x11030080,'dat_sha256':DAT_SHA}
    record['adaptations']['firmware_identity']['dat4_hex']='1004'
    save(output/'manifest.json',record)
    return output/'manifest.json'


def coherent_snapshot(read,advance):
    """暂停时可能恰逢只读观察器写入；只重采样，不补写客体字段。"""
    for attempt in range(20):
        raw=read(attempt)
        if len(raw)<12:raise RuntimeError('只读状态采样截断')
        magic=struct.unpack_from('<I',raw)[0]
        if magic==0x4d32314e:return raw
        if magic!=0:raise RuntimeError('只读状态身份不符')
        if attempt<19:advance()
    raise RuntimeError('只读状态采样持续未完成')


class MenuVM(NativeVM):
    def __init__(self,manifest):
        self.manifest_path=Path(manifest).absolute();self.runtime_inputs()
        super().__init__('native12-410',capid=True,boot_services=True)
        self.cp_service=None;self.loading_busy=False;self.loading_sequences=set()
        self.load_fault=None
        self.select_fault_counts={};self.select_fault_delivered=False
    def runtime_inputs(self):
        if not self.manifest_path.is_relative_to(LAB/'build'):raise ValueError('清单目录越界')
        record=json.loads(self.manifest_path.read_text())
        if (record['schema'],record['model'],record['CP_sha256'])!=('native12-410-menu/1','ILCE-7RM5',CP_SHA) or record['DAT_sha256'] not in (DAT_SHA,DAT411_SHA):
            raise ValueError('整合版清单身份不符')
        if record['DAT_sha256']==DAT411_SHA:
            identity=record.get('adaptations',{}).get('firmware_identity',{})
            if record['AP_sha256'] not in (FONT_AP_SHA,E4_AP_SHA,*UNIFIED_AP_SHAS) or identity.get('dat4_hex')!='1104' or identity.get('source',{}).get('dat_sha256')!=DAT411_SHA:
                raise ValueError('4.11版本材料不符')
        if record['AP_sha256']!=AP_SHA:
            if record['AP_sha256'] not in (FONT_AP_SHA,E4_AP_SHA,*UNIFIED_AP_SHAS) or record.get('base_AP_sha256')!=AP_SHA:raise ValueError('字体修订AP身份不符')
            if record['AP_sha256'] in (E4_AP_SHA,*UNIFIED_AP_SHAS):
                event=verified({'files':{'event':record['e4_menu_patch']}})['event'];event_record=json.loads(event.read_text())
                if (event_record['source_sha256'],event_record['target_sha256'],event_record['inverse_exact'])!=(FONT_AP_SHA,E4_AP_SHA,True):raise ValueError('E4菜单覆盖层来源不符')
            if record['AP_sha256'] in UNIFIED_AP_SHAS:
                patch=verified({'files':{'patch':record['unified_look_patch']}})['patch'];unified=json.loads(patch.read_text())
                if (unified['schema'],unified['source_sha256'],unified['target_sha256'],unified['inverse_exact'])!=('native12-unified-look/1',E4_AP_SHA,record['AP_sha256'],True):raise ValueError('统一入口覆盖层来源不符')
                icon_file=verified({'files':{'icons':record['unified_icons']}})['icons'];icons=json.loads(icon_file.read_text())
                sources={'usr/share/app/image_00_23_IPSX.uxc':'80637a7bb69ccf2ddc6308a148847d1f14a88aa2001e4fc7de04b3e4c83ef061',
                         'usr/share/app/image_00_32_IPSX.uxc':'d5ec718d642fa8b813cf05c45bb0bc53f68b9bc4152fe003f01cdc39efc8a9db'}
                if set(icons)!=set(sources) or any((v['source_sha256'],v['before_count'],v['after_count'],v['inverse_exact'])!=(sources[k],7844,7868,True) for k,v in icons.items()):raise ValueError('统一入口图标来源不符')
            verified({'files':{'font_patch':record['font_patch']}})
            self.loading_inputs=verified({'files':record['loading_inputs']})
            if set(self.loading_inputs)!={'cp','receiver','bin'} or digest(self.loading_inputs['cp'])!=CP_SHA or digest(self.loading_inputs['bin'])!=BIN_SHA:raise ValueError('加载服务材料身份不符')
        if set(record['files'])!={'binary','kernel','initrd','dtb','gpe'}:raise ValueError('研究输入不全')
        return verified(record)

    def start(self):
        inputs=self.runtime_inputs()
        if hasattr(self,'loading_inputs'):
            from cp_service import CPService
            self.cp_service=CPService(inputs,self.loading_inputs['cp'],self.loading_inputs['receiver'],self.out/'cp')
        super().start()

    def pump_loading(self):
        if not self.cp_service or self.loading_busy:return 0
        self.loading_busy=True;count=0
        try:
            while True:
                pattern=rb'OBS A7R5_N12_REQUEST seq=(\d+) size=(\d+) mailbox=0x41ec00000\r?\n'
                pending=[(int(seq),int(size)) for seq,size in re.findall(pattern,self.console.read_bytes()) if int(seq) not in self.loading_sequences]
                if not pending:break
                seq,size=pending[0]
                if not 1<=seq<=1000 or not 0<size<=4096:raise ValueError('模拟传输请求越界')
                self.set_native_paused(True)
                path=self.out/f'cp-request-{seq:03d}.bin'
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(5);self.connect_qmp(sock)
                    with sock.makefile('rwb') as stream:
                        if 'QMP' not in json.loads(stream.readline()):raise RuntimeError('QMP握手不符')
                        for request in ({'execute':'qmp_capabilities'},{'execute':'pmemsave','arguments':{'val':0x41ec00000,'size':64+size,'filename':str(path)}}):
                            stream.write(json.dumps(request).encode()+b'\n');stream.flush()
                            while True:
                                reply=json.loads(stream.readline())
                                if 'error' in reply:raise RuntimeError(str(reply))
                                if 'return' in reply:break
                raw=path.read_bytes()
                if struct.unpack_from('<II',raw)!=(seq,size) or len(raw)!=64+size:raise RuntimeError('传输保留区请求身份不符')
                packet=raw[64:]
                ack=self.cp_service.consume(packet)
                if not ack:raise RuntimeError('CP没有为当前请求返回回执')
                if self.load_fault=='bad-ack' and packet[0]==0xe8:
                    damaged=bytearray(ack);damaged[28]^=1;ack=bytes(damaged)
                    with (self.out/'fault-delivery.jsonl').open('a') as f:f.write(json.dumps({'scenario':'bad-ack','sequence':seq,'delivered':ack.hex()})+'\n')
                if self.load_fault=='bad-select-ack' and packet[0]==0xea and struct.unpack_from('<I',packet,12)[0]==7:
                    self.select_fault_counts[7]=self.select_fault_counts.get(7,0)+1
                    if self.select_fault_counts[7]==2 and not self.select_fault_delivered:
                        damaged=bytearray(ack);damaged[28]^=1;ack=bytes(damaged);self.select_fault_delivered=True
                        with (self.out/'fault-delivery.jsonl').open('a') as f:f.write(json.dumps({'scenario':'bad-select-ack','sequence':seq,'selected':7,'delivered':ack.hex()})+'\n')
                encoded=''.join('\\%03o'%b for b in ack)
                command=f"printf '{encoded}' > /tmp/n12-ack-{seq}.tmp && mv /tmp/n12-ack-{seq}.tmp /tmp/n12-ack-{seq}"
                super().command(command,timeout=15)
                self.loading_sequences.add(seq);count+=1
        finally:self.loading_busy=False
        return count

    def loading_state(self,label):
        if not self.cp_service:return None
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',label):raise ValueError('状态证据名称不符')
        self.set_native_paused(True);path=self.out/f'loading-state-{label}.raw'
        size=json.loads(self.manifest_path.read_text()).get('readonly_AP_state_bytes',1224)
        if size not in (1224,1264):raise ValueError('只读状态结构长度不符')
        def read(attempt):
            sample=path.with_suffix(f'.sample-{attempt:02d}.raw')
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(5);self.connect_qmp(sock)
                with sock.makefile('rwb') as f:
                    if 'QMP' not in json.loads(f.readline()):raise RuntimeError('只读采样QMP握手不符')
                    for q in ({'execute':'qmp_capabilities'},{'execute':'pmemsave','arguments':{'val':0x41ec02000,'size':size,'filename':str(sample)}}):
                        f.write(json.dumps(q).encode()+b'\n');f.flush()
                        while True:
                            reply=json.loads(f.readline())
                            if 'error' in reply:raise RuntimeError(str(reply))
                            if 'return' in reply:break
            raw=sample.read_bytes()
            if len(raw)!=size:raise RuntimeError('只读状态采样长度不符')
            return raw
        def advance():
            self.set_native_paused(False);time.sleep(.005);self.pump_loading();self.set_native_paused(True)
        raw=coherent_snapshot(read,advance);path.write_bytes(raw)
        _,mask,selected=struct.unpack_from('<III',raw)
        names=[]
        for n in range(12):
            off=128+n*88
            names.append({'number':n+1,'short':raw[off:off+24].split(b'\0')[0].decode(),
                          'full':raw[off+24:off+88].split(b'\0')[0].decode()})
        state=dict(available_mask=mask,selected=selected,names=names,AP_worker_words=list(struct.unpack_from('<20I',raw,16)),
                   AP_transfer_words=list(struct.unpack_from('<8I',raw,96)),source='read-only snapshot of production AP state and getters; no writes')
        state.update(command_state=struct.unpack_from('<I',raw,12)[0],native_refresh=dict(zip(('wait','done','object','expected_params','AP_base'),struct.unpack_from('<IIQQQ',raw,1184))))
        if size==1264:
            state['selection_file']=dict(bytes_read=struct.unpack_from('<i',raw,1224)[0],hex=raw[1228:1252].hex(),pending=bool(struct.unpack_from('<I',raw,1252)[0]))
        save(path.with_suffix('.json'),state)
        return state

    def command(self,code,timeout=90):
        if self.cp_service:self.pump_loading()
        data=super().command(code,timeout=timeout)
        if self.cp_service:self.pump_loading()
        if code.startswith('/simulation/headless-osd-export'):
            # 输入观察日志可能打断同一串口上的Base64；仅剥离固定格式，整帧FNV仍由原解码器校验。
            noise=(rb'OBS A7R5_INPUT_COMPLETED key=0x[0-9a-f]+ status=(?:0x[0-9a-f]+|0) frame_sequence=\d+ result=0\r?\n|'
                   rb'OBS A7R5_N12_REQUEST seq=\d+ size=\d+ mailbox=0x41ec00000\r?\n|'
                   rb'OBS A7R5_N12_ACK seq=\d+ size=(?:32|44|128) inbound=1\r?\n')
            data,count=re.subn(noise,b'',data)
            if count:
                with (self.out/'export-noise.jsonl').open('a') as f:f.write(json.dumps({'known_input_records_removed':count})+'\n')
            self.set_native_paused(True)
        return data

    def wait_native_screen(self,expected):
        if not self.cp_service:return super().wait_native_screen(expected)
        from menu_live import FirmwareMonitor
        accepted=(expected,) if isinstance(expected,int) else tuple(expected)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            FirmwareMonitor(self.console).check();self.pump_loading()
            if self.last_native_screen() in accepted:return
            if self.process.poll() is not None:raise RuntimeError('页面等待时QEMU退出')
            time.sleep(.01)
        raise RuntimeError('原生加载候选页面不符')

    def prime_native_menu(self):
        if not self.cp_service:return super().prime_native_menu()
        if getattr(self,'native_primed',False):raise RuntimeError('拒绝重复首次初始化')
        from menu_live import key_command
        self.wait_native_screen(0x2d6);steps=[]
        sequence=(('MENU',0x355),('MENU',0x2d6)) if getattr(self,'menu_isolation',False) else (('MENU',0x355),('MENU',0x2d6),('MENU',0x1e9),('ENTER',0),('MENU',0x2d6))
        for key,expected in sequence:
            before=self.last_native_screen();self.command(key_command(key),timeout=30);self.wait_native_screen(expected)
            # 保留原初始化的一秒稳定期，分段服务CP，避免阻塞原一秒ACK预算。
            for _ in range(20):self.command('sleep 0.05',timeout=45)
            steps.append({'key':key,'before':before,'after':expected})
        self.native_primed=True
        save(self.out/'native-initialization.json',dict(status='ready',steps=steps,touch_guide_acknowledged_by_original_enter=not getattr(self,'menu_isolation',False),menu_isolation=getattr(self,'menu_isolation',False),settings_persistence='guest RAM only'))

    def close(self):
        result=super().close()
        if self.cp_service:self.cp_service.close()
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    print(build(p.parse_args().output))
