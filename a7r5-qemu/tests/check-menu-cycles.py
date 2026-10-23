"""独立检查真实菜单反复开关，关闭帧允许黑色；不启动 VM。"""
import argparse,base64,hashlib,json,re,sys
from pathlib import Path
from PIL import Image
LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
from headless_osd_capture import decode_export,HEADER,METADATA


def saved_frames(name,prefix="snapshot-",live=False,require_complex=True):
    if not re.fullmatch('native-app-[a-z0-9_]+',name):raise ValueError('非原生证据目录')
    run=LAB/'runs'/name
    console=(run/'console.log').read_bytes()
    if live:
        result={'backend':'native','cleanup':None,'console_finalized':False}
    else:
        result=json.loads((run/'result.json').read_text())
        assert result['backend']=='native' and result['cleanup']=={'method':'qmp-quit','exit_code':0}
        assert hashlib.sha256(console).hexdigest()==result['console_sha256']
    assert not re.search(rb'Entering exception monitor\.|^OBS OSD_HEADLESS_FAILED ',console.replace(b'\r',b''),re.M)
    rows=[]
    for path in sorted(run.glob(prefix+'*.bin')):
        raw=path.read_bytes()
        checked,info=decode_export(b'HEADLESS_OSD_BEGIN\n'+base64.b64encode(raw)+b'\nHEADLESS_OSD_END\n')
        assert checked==raw
        pixels=raw[HEADER+METADATA:];rgba=bytearray()
        for i in range(0,len(pixels),2):
            v=pixels[i]|pixels[i+1]<<8;rgba.extend(((v>>12)*17,((v>>8)&15)*17,((v>>4)&15)*17,(v&15)*17))
        with Image.open(path.with_suffix('.png')) as pic:
            assert pic.size==(640,480) and pic.convert('RGBA').tobytes()==rgba
            black=pic.convert('RGB').getbbox() is None
            # 简洁的原厂水平仪/提示页可能少于 17 色；菜单验收默认仍要求复杂画面。
            if not black and require_complex:assert pic.convert('RGB').getcolors(16) is None
        meta=json.loads(path.with_suffix('.json').read_text())
        assert meta['sha256']==info['sha256'] and meta['sequence']==info['sequence']
        rows.append({'image':str(path.with_suffix('.png').relative_to(LAB)),
             'sequence':info['sequence'],'pixel_source_seq':info['pixel_source_seq'],
             'pixel_sha256':hashlib.sha256(pixels).hexdigest(),'container_sha256':info['sha256'],'black':black})
    assert rows and all(a['sequence']<b['sequence'] for a,b in zip(rows,rows[1:]))
    return rows,result


def check(name):
    frames,result=saved_frames(name)
    assert len(frames)>=3 and len(frames)%2==1
    initial=frames[0]['pixel_sha256'];assert not frames[0]['black']
    for i,f in enumerate(frames[1:],1):
        if i%2:assert f['pixel_sha256']!=initial and f['pixel_sha256']==frames[1]['pixel_sha256'],('菜单未返回同一拍摄信息页',i)
        else:assert f['pixel_sha256']==initial and not f['black'],('MENU 未重新打开同一真实菜单',i)
    return {'run':name,'cycles':len(frames)//2,'frames':frames,'cleanup':result['cleanup'],
            'closed_view':'original shooting information UI; sensor video not implemented'}


def main():
    p=argparse.ArgumentParser();p.add_argument('run');a=p.parse_args()
    value=check(a.run)
    (LAB/'logs/native-menu-cycles.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'cycles_verified':value['cycles'],'run':a.run}))


if __name__=='__main__':main()
