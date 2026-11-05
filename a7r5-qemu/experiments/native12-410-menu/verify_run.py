"""独立复核本次真实客体快照、Qt输入和QMP退出；不补画菜单。"""
import argparse
import array
import base64
import hashlib
import json
from pathlib import Path
import sys
from environment import LAB,AP_SHA,DAT_SHA
sys.path.insert(0,str(LAB/'tools'))
from headless_osd_capture import decode_export,HEADER,METADATA
from PIL import Image


def verify(run,isolated_control_only=False):
    run=run.absolute()
    if run.parent!=LAB/'runs' or not run.name.startswith('native-native12-410-'):raise ValueError('证据目录越界')
    closed=json.loads((run/'exit.json').read_text())
    if closed!={'method':'qmp-quit','exit_code':0}:raise ValueError('QMP未正常退出')
    console=(run/'console.log').read_bytes()
    if any(s in console for s in (b'Entering exception monitor.',b'OBS OSD_HEADLESS_FAILED ',b'Kernel panic')):
        raise ValueError('出现固件或图形异常')
    lut=[bytes(((v>>12)*17,((v>>8)&15)*17,((v>>4)&15)*17,(v&15)*17)) for v in range(65536)]
    frames=[]
    for path in [run/'native410-baseline-menu.bin',*run.glob('research-*.bin')]:
        raw=path.read_bytes()
        checked,info=decode_export(b'HEADLESS_OSD_BEGIN\n'+base64.b64encode(raw)+b'\nHEADLESS_OSD_END\n')
        if raw!=checked:raise ValueError('容器不符')
        values=array.array('H',raw[HEADER+METADATA:])
        if sys.byteorder!='little':values.byteswap()
        rgba=b''.join(lut[v] for v in values)
        with Image.open(path.with_suffix('.png')) as picture:
            if picture.size!=(640,480) or picture.convert('RGBA').tobytes()!=rgba:raise ValueError('PNG像素与客体帧不同')
        saved=json.loads(path.with_suffix('.json').read_text())
        if (saved['sha256'],saved['sequence'])!=(info['sha256'],info['sequence']):raise ValueError('帧回执不同')
        frames.append(dict(file=path.name,sequence=info['sequence'],pixel_sha256=hashlib.sha256(raw[HEADER+METADATA:]).hexdigest()))
    frames.sort(key=lambda r:r['sequence'])
    if not frames or any(a['sequence']>=b['sequence'] for a,b in zip(frames,frames[1:])):raise ValueError('帧序列不严格递增')
    qt=json.loads((run/'qt-research.json').read_text());actions=json.loads((run/'research-actions.json').read_text())
    if qt['worker_exit_code']!=0 or qt['worker_exit_status']!='ExitStatus.NormalExit':raise ValueError('Qt工作进程异常退出')
    if len(qt['operations'])!=len(actions)+1 or qt['operations'][-1]['action']!='STOP':raise ValueError('Qt输入和回执数量不同')
    for a,b in zip(qt['operations'],actions):
        if a['action']!=b['action'] or a['source']!='QTest.mouseClick -> QPushButton.clicked -> worker':raise ValueError('未通过Qt输入')
    e4=json.loads((run/'e4-audit.json').read_text()) if (run/'e4-audit.json').is_file() else None
    if isolated_control_only and (not e4 or e4['status']!='PASS_MENU_ISOLATION'):
        raise ValueError('有限控制链审计必须已有明确的菜单隔离E4回执')
    cycles=actions[-8:]
    if not isolated_control_only:
        if len(cycles)!=8 or any(r['action']!='MENU' for r in cycles):raise ValueError('缺少四轮菜单往返')
        pixels=[r['frame']['pixel_sha256'] for r in cycles]
        if pixels[0]==pixels[1] or any(p!=pixels[i%2] for i,p in enumerate(pixels)):raise ValueError('菜单往返像素不同')
    loading=json.loads((run/'loading-audit.json').read_text()) if (run/'loading-audit.json').is_file() else None
    findings=(['原生E4刷新未完成，十二项名称与参数加载通过，滤镜成功应用未验收',
               'Portra400左列简称仍有裁切，右栏Portra400NB全名可见'] if loading else
              ['自定义滤镜页面可打开，当前自然启动只显示关闭','当前英语界面下中文文本显示方框，原因未定位',
               '12款配置的SD导入、CP激活和实际颜色不属于本次成功证据'])
    if e4:
        if e4['status'] not in ('PASS','PASS_MENU_ISOLATION'):raise ValueError('E4审计未通过')
        findings=['Portra400左列简称仍有裁切，右栏Portra400NB全名可见']
        if e4.get('menu_isolation'):findings.append('只验证拍摄初始化前的原生菜单隔离场景；完整启动仍受0x4073/0x2040成像状态服务阻塞')
    report=dict(status='QEMU_MENU_AND_CONFIG_LOADING_VERIFIED_WITH_FINDINGS' if loading else 'QEMU_MENU_CAPTURE_VERIFIED_WITH_FINDINGS',
        AP_sha256=loading['AP_sha256'] if loading else AP_SHA,source_DAT_sha256=loading['source_DAT_sha256'] if loading else DAT_SHA,
        raw_png_frames_verified=len(frames),frames=frames,qt_clicks=len(qt['operations']),menu_cycles=0 if isolated_control_only else 4,
        close=closed,worker_exit_code=0,camera_io=False,filter_names_fixture=False,full_CP_emulated=False,
        findings=findings,
        photo_overlay_verified=False,console_sha256=hashlib.sha256(console).hexdigest())
    if isolated_control_only:report.update(status='QEMU_FILTER_CONTROL_ONLY_VERIFIED',menu_lifecycle_verified=False)
    with (run/('control-frame-audit.json' if isolated_control_only else 'frame-audit.json')).open('x') as f:json.dump(report,f,indent=2,ensure_ascii=False);f.write('\n')
    return {k:v for k,v in report.items() if k!='frames'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--isolated-control-only',action='store_true',help='仅审计隔离控制链原帧；明确不授予MENU往返验收')
    a=p.parse_args();print(json.dumps(verify(a.run,a.isolated_control_only),indent=2,ensure_ascii=False))
