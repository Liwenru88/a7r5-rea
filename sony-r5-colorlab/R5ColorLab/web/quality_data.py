"""只读、按摘要绑定的离线照片验收集；HTTP 请求不能指定任意本机路径。"""
from pathlib import Path
import json
import shutil
import re
import hashlib
import numpy as np


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def load(identifier,runs,target_sha256):
    if identifier is None:return ()
    if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{64}',identifier):raise ValueError('照片验收集标识无效')
    root=Path(runs)/'_quality_sets'/identifier;path=root/'manifest.json'
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=identifier:raise ValueError('照片验收集清单摘要不符')
    manifest=json.loads(raw)
    if manifest['target_sha256']!=target_sha256:raise ValueError('照片验收集与训练目标不匹配')
    rows=[];scenes=set()
    for item in manifest['scenes']:
        name=item['file']
        if Path(name).name!=name or item['role'] not in ('development','holdout') or item['scene'] in scenes:raise ValueError('照片验收集路径、角色或场景无效')
        scenes.add(item['scene']);file=root/name
        if digest(file)!=item['sha256']:raise ValueError('照片验收集数据摘要不符')
        with np.load(file,allow_pickle=False) as data:
            inputs=data['inputs'].copy();target=data[manifest['target_key']].copy()
        if inputs.shape!=(len(target),9,3) or target.shape!=(len(inputs),3) or not np.isfinite(inputs).all() or not np.isfinite(target).all():raise ValueError('照片验收数据形状或数值无效')
        rows.append(dict(scene=item['scene'],role=item['role'],inputs=inputs,target=target))
    if {r['role'] for r in rows}!={'development','holdout'}:raise ValueError('照片验收集缺少开发或留出照片')
    return tuple(rows)


def bind(body,runs):
    identifier=body.get('quality_set')
    if not identifier:
        matches=[]
        for path in (Path(runs)/'_quality_sets').glob('*/manifest.json'):
            m=json.loads(path.read_text())
            if m['target_sha256']==body.get('target_sha256'):matches.append(path.parent.name)
        if len(matches)==1:identifier=matches[0];body['quality_set']=identifier
    if identifier:load(identifier,runs,body.get('target_sha256'))


def register(runs,manifest_path,target_sha256,target_key):
    """仅供本机离线命令登记已冻结数据，不复制或修改原照片。"""
    source=Path(manifest_path);data=json.loads(source.read_text())
    manifest=dict(schema='r5-quality-photo-set/1',target_sha256=target_sha256,target_key=target_key,scenes=data['scenes'])
    raw=(json.dumps(manifest,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode();identifier=hashlib.sha256(raw).hexdigest()
    folder=Path(runs)/'_quality_sets'/identifier
    if folder.exists():load(identifier,runs,target_sha256);return identifier
    folder.mkdir(parents=True)
    for row in manifest['scenes']:
        path=source.parent/row['file']
        if digest(path)!=row['sha256']:raise ValueError('待登记照片摘要不符')
        shutil.copy2(path,folder/row['file'])
    (folder/'manifest.json').write_bytes(raw);load(identifier,runs,target_sha256)
    return identifier
