"""独立核对真实客体帧、Qt操作、虚拟存储身份及新客体恢复。"""
import argparse
import array
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

from PIL import Image

HERE=Path(__file__).resolve().parent
LAB=HERE.parents[1]
sys.path.insert(0,str(LAB/'tools'))
from headless_osd_capture import decode_export, HEADER, METADATA


def load(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def session(path):
    result=load(path/'sound-validation.json')
    assert result['status']=='PASS' and result['close']=={'method':'qmp-quit','exit_code':0}
    assert load(path/'cp/close.json')['exit_code']==0
    qt=load(path/'qt-research.json')
    assert qt['worker_exit_code']==0 and qt['worker_exit_status']=='ExitStatus.NormalExit'
    rows=result['actions']
    if (path/'qt-driver.json').exists():
        assert [x['screen'] for x in rows[-8:]]==[0,0x2d6]*4
    assert [x['action'] for x in qt['operations']]==[x['action'] for x in rows]+['STOP']
    assert all(x['source']=='QTest.mouseClick -> QPushButton.clicked -> worker' for x in qt['operations'])
    console=(path/'console.log').read_bytes()
    assert all(x not in console for x in (b'Entering exception monitor.',b'Kernel panic',b'OSD_HEADLESS_FAILED'))
    lut=[bytes(((v>>12)*17,((v>>8)&15)*17,((v>>4)&15)*17,(v&15)*17)) for v in range(65536)]
    frames=[path/'sound-baseline.bin']+[Path(x['png']).with_suffix('.bin') for x in rows]
    sequences=[]
    for frame in frames:
        raw=frame.read_bytes()
        decoded,info=decode_export(b'HEADLESS_OSD_BEGIN\n'+base64.b64encode(raw)+b'\nHEADLESS_OSD_END\n')
        assert decoded==raw
        metadata=load(frame.with_suffix('.json'))
        assert metadata['sha256']==info['sha256'] and metadata['sequence']==info['sequence']
        pixels=array.array('H',raw[HEADER+METADATA:])
        if sys.byteorder!='little':pixels.byteswap()
        with Image.open(frame.with_suffix('.png')) as png:
            assert png.size==(640,480) and png.convert('RGBA').tobytes()==b''.join(lut[v] for v in pixels)
        sequences.append(info['sequence'])
    assert all(a<b for a,b in zip(sequences,sequences[1:]))
    return dict(run=str(path),frames_verified=len(frames),Qt_clicks=len(qt['operations']),AP_exit=0,CP_exit=0,
                fixture_audio=True,source_json_sha256=digest(path/'sound-validation.json'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual',type=Path,required=True)
    parser.add_argument('--saved',type=Path,required=True)
    parser.add_argument('--restored',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sessions=[session(p.resolve()) for p in (args.manual,args.saved,args.restored)]
    manual=load(args.manual/'sound-actions.json')
    assert manual[29]['sound']['electronic_selected']==0 and manual[30]['sound']['electronic_selected']==2
    assert manual[32]['frame']['pixel_sha256']==manual[35]['frame']['pixel_sha256']
    files={name:base64.b64decode(data,validate=True) for name,data in load(args.saved/'exported-files.json').items()}
    profile=files['R5SOUND.PRO'];catalog=files['R5SOUND.IDX']
    assert len(profile)==96 and profile[:8]==b'R5SNDPF1' and struct.unpack_from('<I',profile,8)[0]==1
    assert struct.unpack_from('<I',profile,92)[0]==zlib.crc32(profile[:92])
    assert len(catalog)==624 and catalog[:8]==b'R5SNDIDX' and struct.unpack_from('<I',catalog,12)[0]==2
    assert struct.unpack_from('<I',catalog,24)[0]==zlib.crc32(catalog[32:])
    identities=[]
    for i in range(2):
        record=catalog[32+i*296:32+(i+1)*296];identity=record[256:288]
        blob=files['R5SN_'+identity.hex()+'.R5S']
        assert hashlib.sha256(blob[:416]).digest()==identity
        # 固定头部长度来自R5S格式，十档载荷摘要由运行时及转换器分别验证。
        assert len(blob)==struct.unpack_from('<I',record,288)[0]
        identities.append(identity)
    assert profile[12:44]==identities[0] and profile[52:84]==identities[1]
    assert struct.unpack_from('<II',profile,44)==(3,1) and struct.unpack_from('<II',profile,84)==(8,1)
    restored=load(args.restored/'sound-validation.json')
    state=restored['baseline']['sound']
    assert (state['count'],state['mechanical_selected'],state['electronic_selected'],state['mechanical_volume'],state['electronic_volume'])==(2,1,2,3,8)
    assert state['active_selected']==1 and state['installed_volume']==3
    assert b'R5_SOUND_LOG SCAN_BEGIN' not in (args.restored/'console.log').read_bytes()
    report=dict(schema='r5-sound-qemu-verification/1',status='PASS',date='2026-11-11',
                sessions=sessions,frames_verified=sum(x['frames_verified'] for x in sessions),
                Qt_clicks=sum(x['Qt_clicks'] for x in sessions),
                scenarios=['two Chinese names imported through production R5S reader','four native menu peers',
                           'browse without commit','ENTER commit','MENU cancels volume edit','independent selections and volumes',
                           'checksummed 96-byte profile from virtual VFAT','new guest no-card internal-library restore','MENU repeated open/close'],
                exported_files={k:{'bytes':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in files.items()},
                AP_sha256='63072c53ff5d9ed4b32f01175667e057f85c1cc83c6d5067337354c6c52c6eda',
                CP_sha256='0e5ba4553064b1143a7d407b14dd9b5b353c98d77bd0d87bbfc8a4e490f4f523',
                camera_io=False,DAT_generated=False,actual_audio_hardware=False,
                boundary='actual AP UI/import/storage/profile/scheduler; virtual card and audio backend; CP instruction sidecar is not full RTOS or hardware boot')
    with args.output.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report[k] for k in ('status','frames_verified','Qt_clicks','camera_io','actual_audio_hardware')},ensure_ascii=False))


if __name__=='__main__':main()
