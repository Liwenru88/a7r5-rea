"""组合等长内嵌矩阵与既有type1声音候选；仅生成离线组件。"""
import argparse
import json
from pathlib import Path
import tempfile

from look_matrix_compact import build as compact,compile_copy
from look_matrix_embed import compile_helper,sha

SOUND_OFFSET=0x47f601-0x108000
OLD_INTEGRATED_SHA='fa52e3cb0ce5f49b3784176e191a75c7de1ffc41f232cd8d6ad784de178474bc'


def build(original,delta):
    cp,layout=compact(original,delta)
    if cp[SOUND_OFFSET-1:SOUND_OFFSET+3]!=bytes.fromhex('020f1c40'):
        raise ValueError('既有type1声音分派表前像不符')
    sound=bytearray(original);sound[SOUND_OFFSET]=2
    if sha(sound)!=OLD_INTEGRATED_SHA:raise ValueError('旧整合CP不能由同一色彩前像精确还原')
    output=bytearray(cp);output[SOUND_OFFSET]=2
    report=dict(layout)
    report.update(schema=3,layout='boot-copy-compact-with-type1',target_sha256=sha(output),
        matrix_only_CP_sha256=sha(cp),previous_integrated_CP_sha256=OLD_INTEGRATED_SHA,
        sound_speaker_verified=False,full_CP_boot_verified=False,
        device_deployment_ready=False,settings_writes_required_for_target_matrices=False)
    report['patches']=[*layout['patches'],dict(offset=SOUND_OFFSET,bytes=1,before='0f',after='02',
        reason='保留旧整合CP的type1声音分派；未证明扬声器发声')]
    return bytes(output),report


def prepare(folder):
    from look_materials import load
    from runtime_manifest import LAB
    files,receipt=load(folder)
    if receipt['schema']!=2:raise ValueError('整合只接受固定色彩前像，不叠加未知补丁')
    cp,report=build(files['cpapp-b.bin'],files['matrix-delta.bin'])
    out=Path(tempfile.mkdtemp(prefix='look-materials-integrated-',dir=LAB/'build'))
    compile_copy(out);compile_helper(out)
    files['cp-matrix-source.bin']=files['cpapp-b.bin'];files['cpapp-b.bin']=cp
    files['matrix-inline.json']=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
    for name,raw in files.items():(out/name).write_bytes(raw)
    receipt.update(schema=6,files={n:dict(bytes=len(r),sha256=sha(r)) for n,r in files.items()},
        CP_scope='equal-size matrix plus preserved type1 sound; offline package candidate, no device acceptance',
        device_deployment_ready=False)
    (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    load(out)
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--materials',type=Path,required=True)
    print(prepare(p.parse_args().materials))
