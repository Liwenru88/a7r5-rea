"""创意外观隔离材料；只导入有摘要的研究副本，不读取设备或分区镜像。"""
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile

from runtime_manifest import LAB

LOCAL_BASE = LAB/'build/look-materials-77zf0trj'

CP_SHA = '903bb046b4525a55198c1312999857ee01f89859ba3de6f18ee107c46d63039a'
AP_SHA = 'b051590a61cf6fac9f0026601ca431405d9278d6ed3c814cf34f99164b0f3d3a'
PROP_SHA = '4a4ec0273185a2f3f08c3206e09c0d6a12b48f71a84d38f98d1247ca57d8bf8e'
DELTA_SHA = '71aa15a9dfe051e2a260cc1d9cf55d8cf985e787b5884c136516a2f73950f8ac'
MODEL_SHA = '15aa6b41d942807be5b947edcfd229602341648f0e295cb6bd3157373027a805'
SELECTOR_SHA = '6424bc4b2955f8f48bfa3903fddbc28b832d4d29fce3b908844504841f836366'
SPEC_SHA = 'f17b2fa689fd9b4364c9fdda9408ea7fc4c8d5386d08d4901029e4c158fe696b'
FIXED_PROP_SHA = '72a2ad1df701b717977b289c21d41473da8cd84ee9a1453d6c9368990db4ab1b'
STYLE_PROP_SHA = '1fdae63d018d6f9d73de43273cb2694ef93d78dea8dff68779751956401b1f8a'
NAMES = ('Classic Neg.', 'Classic Chrome', 'Nostalgic Neg.', 'Eterna',
         'GR Positive Film', 'GR Negative Film')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular(path, maximum=100_000_000):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('拒绝符号链接材料')
    # 先以非阻塞打开，再核对类型，避免设备、FIFO 和竞态更换。
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=maximum:
            raise ValueError('只接受受限长度的普通研究文件')
        raw=stream.read(maximum+1);after=os.fstat(stream.fileno())
        if len(raw)!=before.st_size or (before.st_mtime_ns,before.st_size)!=(after.st_mtime_ns,after.st_size):
            raise ValueError('材料读取期间变化')
        return raw


def prepare(research_root=None):
    """从项目内固定副本准备新材料；不再读取已删除的研究目录。"""
    source=LOCAL_BASE
    if research_root is not None:
        requested=Path(research_root).absolute()
        # 保留旧的工程根参数兼容性；也允许显式指定已有校验材料。
        if requested not in (LAB,LAB.parent):
            source=requested
    files,original=load(source)
    out=Path(tempfile.mkdtemp(prefix='look-materials-',dir=LAB/'build'))
    for name,raw in files.items():(out/name).write_bytes(raw)
    record=dict(original,files={n:{'bytes':len(r),'sha256':sha(r)} for n,r in files.items()},
        local_copy_source=str(source.relative_to(LAB)),
        camera_io=False,original_images_read=False,default_manifest_modified=False)
    (out/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return out


def load(folder):
    folder=Path(folder).absolute()
    if folder.parent!=LAB/'build' or not folder.name.startswith('look-materials-') or folder.is_symlink():
        raise ValueError('隔离材料目录越界')
    record=json.loads(regular(folder/'receipt.json',100000))
    expected={'cpapp-b.bin','ap-selector.bin','ap-map.bin','six-looks.json','rendering-model.json',
              'matrix-delta.bin','matrix-before.bin','matrix-fixed.bin','gamma-before.bin',
              *(f'slot{i}.raw-s8.bin' for i in range(1,7))}
    if record.get('schema') in (2,3,4,5,6,7):expected.add('style-property.bin')
    if record.get('schema') in (3,4,5,6,7):expected.update(('cp-matrix-source.bin','matrix-inline.json'))
    if record.get('schema')==7:expected.update(('cp-joint-source.bin','joint-layout.json'))
    if record.get('schema') not in (1,2,3,4,5,6,7) or set(record['files'])!=expected:
        raise ValueError('材料清单不完整')
    files={}
    for name,row in record['files'].items():
        raw=regular(folder/name)
        if len(raw)!=row['bytes'] or sha(raw)!=row['sha256']:raise ValueError('材料校验失败：'+name)
        files[name]=raw
    if record['schema'] in (2,3,4,5,6,7) and sha(files['style-property.bin'])!=STYLE_PROP_SHA:
        raise ValueError('风格属性身份不符')
    source=files['cp-matrix-source.bin'] if record['schema'] in (3,4,5,6,7) else files['cpapp-b.bin']
    if (sha(source),sha(files['matrix-before.bin']),sha(files['matrix-delta.bin']),
        sha(files['rendering-model.json']))!=(CP_SHA,PROP_SHA,DELTA_SHA,MODEL_SHA):
        raise ValueError('固定材料身份不符')
    if record['schema'] in (3,4):
        from look_matrix_embed import build
        rebuilt,report=build(source,files['matrix-delta.bin'],initialized_bss=record['schema']==4)
        if rebuilt!=files['cpapp-b.bin'] or json.loads(files['matrix-inline.json'])!=report:
            raise ValueError('内嵌 CP 重建或布局收据不符')
    if record['schema']==5:
        from look_matrix_compact import build
        rebuilt,report=build(source,files['matrix-delta.bin'])
        if rebuilt!=files['cpapp-b.bin'] or json.loads(files['matrix-inline.json'])!=report:
            raise ValueError('等长内嵌 CP 重建或布局收据不符')
    if record['schema']==6:
        from look_integrated import build
        rebuilt,report=build(source,files['matrix-delta.bin'])
        if rebuilt!=files['cpapp-b.bin'] or json.loads(files['matrix-inline.json'])!=report:
            raise ValueError('整合内嵌CP重建或布局收据不符')
    if record['schema']==7:
        from look_joint import SOURCE_SHA,TARGET_SHA,SPEC_SHA as joint_spec,NAMES as joint_names
        joint=json.loads(files['joint-layout.json'])
        if (sha(files['cp-joint-source.bin'])!=SOURCE_SHA or sha(files['cpapp-b.bin'])!=TARGET_SHA
            or sha(files['six-looks.json'])!=joint_spec or joint['target_sha256']!=TARGET_SHA
            or joint['source_sha256']!=SOURCE_SHA):
            raise ValueError('联合参数候选或来源身份不符')
    # 清单也不能授权替换原本固定的 AP 片段或六张表。
    if files['ap-map.bin']!=bytes.fromhex('00030201100f1112050d1314'):
        raise ValueError('AP 原生风格映射不符')
    spec_sha=joint_spec if record['schema']==7 else SPEC_SHA
    if (sha(files['ap-selector.bin']),sha(files['six-looks.json']),sha(files['matrix-fixed.bin']))!=(SELECTOR_SHA,spec_sha,FIXED_PROP_SHA):
        raise ValueError('AP 片段、槽位定义或修复属性身份不符')
    if files['gamma-before.bin']!=files['cpapp-b.bin'][0x108d080:0x108d080+576]:
        raise ValueError('迁移曲线与原件不一致')
    slots=json.loads(files['six-looks.json'])['slots']
    if tuple(s['name'] for s in slots)!=(joint_names if record['schema']==7 else NAMES):raise ValueError('槽位名称不符')
    for s in slots:
        if sha(files[s['table']])!=s['table_sha256']:raise ValueError('色表来源摘要不符')
    return files,record
