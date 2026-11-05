"""独立逐像素复核已停机的真实客体帧；照片标记未出帧时明确保留缺口。"""
import argparse
import array
import base64
import hashlib
import json
from pathlib import Path
import sys

from environment import LAB
sys.path.insert(0,str(LAB/'tools'))
from headless_osd_capture import decode_export,HEADER,METADATA
from PIL import Image


def verify(run,cycle_start=None):
    run=run.absolute()
    if run.parent!=LAB/'runs' or not run.name.startswith('native-aspect406-'):
        raise ValueError('证据目录越界')
    closed=json.loads((run/'exit.json').read_text())
    if closed!={'method':'qmp-quit','exit_code':0}:raise ValueError('未正常退出')
    console=(run/'console.log').read_bytes()
    if b'Entering exception monitor.' in console or b'OBS OSD_HEADLESS_FAILED ' in console:
        raise ValueError('该次运行有固件或图形异常')
    lut=[bytes(((v>>12)*17,((v>>8)&15)*17,((v>>4)&15)*17,(v&15)*17)) for v in range(65536)]
    frames=[]
    for path in run.glob('*.bin'):
        raw=path.read_bytes()
        checked,info=decode_export(b'HEADLESS_OSD_BEGIN\n'+base64.b64encode(raw)+b'\nHEADLESS_OSD_END\n')
        if checked!=raw:raise ValueError('容器校验不符')
        values=array.array('H',raw[HEADER+METADATA:])
        if sys.byteorder!='little':values.byteswap()
        rgba=b''.join(lut[v] for v in values)
        with Image.open(path.with_suffix('.png')) as picture:
            if picture.size!=(640,480) or picture.convert('RGBA').tobytes()!=rgba:
                raise ValueError('PNG 与原始像素不一致：'+path.name)
        saved=json.loads(path.with_suffix('.json').read_text())
        if (saved['sha256'],saved['sequence'])!=(info['sha256'],info['sequence']):
            raise ValueError('帧记录不一致')
        frames.append({'file':path.name,'sequence':info['sequence'],
                       'pixel_sha256':hashlib.sha256(raw[HEADER+METADATA:]).hexdigest()})
    frames.sort(key=lambda row:row['sequence'])
    if not frames or any(a['sequence']>=b['sequence'] for a,b in zip(frames,frames[1:])):
        raise ValueError('帧序列不严格递增')
    actions=json.loads((run/'research-actions.json').read_text())
    if not any(row['model']=='model=16 switch=0 ratio=5 opacity=12' for row in actions):
        raise ValueError('未读回开启和 2.35:1')
    cycles=None
    if cycle_start is not None:
        selected=actions[cycle_start:cycle_start+8]
        if len(selected)!=8 or any(row['action']!='MENU' for row in selected):
            raise ValueError('四轮 MENU 操作证据不完整')
        menu=selected[0]['frame']['pixel_sha256'];photo=selected[1]['frame']['pixel_sha256']
        if menu==photo or any(row['frame']['pixel_sha256']!=(menu if i%2==0 else photo)
                              for i,row in enumerate(selected)):
            raise ValueError('MENU 往返像素不一致')
        cycles={'count':4,'menu_pixel_sha256':menu,'photo_pixel_sha256':photo}
    qt=json.loads((run/'qt-research.json').read_text())
    if qt['worker_exit_code'] or qt['worker_exit_status']!='ExitStatus.NormalExit' or qt['ticks']<10:
        raise ValueError('Qt/工作进程退出或事件循环异常')
    off=next(row for row in actions if row['frame'].get('shooting_mode')=='M' and 'switch=1' in (row['model'] or ''))
    on=next(row for row in actions if row['frame'].get('shooting_mode')=='M' and 'switch=0 ratio=5' in (row['model'] or ''))
    report={'status':'menu-selection-verified-photo-overlay-not-verified',
            'raw_png_frames_verified':len(frames),'frames':frames,'menu_cycles':cycles,
            'qt_clicks':len(qt['operations']),'worker_exit_code':0,'close':closed,
            'console_sha256':hashlib.sha256(console).hexdigest(),
            'photo_off_frame':off['png'],'photo_on_235_frame':on['png'],
            'photo_overlay_pixels_changed':off['frame']['pixel_sha256']!=on['frame']['pixel_sha256'],
            'complete_photo_overlay_verified':False,'camera_io':False}
    (run/'frame-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return {k:v for k,v in report.items() if k!='frames'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--cycle-start',type=int)
    args=parser.parse_args()
    print(json.dumps(verify(args.run,args.cycle_start),ensure_ascii=False,indent=2))
