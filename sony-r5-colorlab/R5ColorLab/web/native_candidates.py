"""保存真实原生参数候选，短名单只决定计算预算，不代替最终网格评分。"""
from pathlib import Path
import json
import hashlib
import math
import numpy as np


def append(path,params,vector,label,score,native_gray,pairs_sha256):
    path=Path(path)
    fields=dict(matrix_780f_hex=params['matrix_payload'].hex(),cc1_direct_raw=np.asarray(params['cc1']).astype(int).tolist(),gamma_7806_y=np.asarray(params['gamma_y']).astype(int).tolist())
    identity=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()
    row=dict(sha256=identity,parameters=fields,vector=np.asarray(vector).tolist(),label=label,score=float(score),native_gray=float(native_gray))
    if not np.isfinite(vector).all() or not all(math.isfinite(row[k]) for k in ('score','native_gray')):raise ValueError('候选含非有限数值')
    value=json.loads(path.read_text()) if path.exists() else dict(schema='r5-native-candidates/1',pairs_sha256=pairs_sha256,candidates=[])
    if value['pairs_sha256']!=pairs_sha256:raise ValueError('候选训练数据身份不符')
    value['candidates'].append(row)
    temporary=path.with_suffix('.pending');temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n');temporary.replace(path)


def shortlist(path,limit=4, *, expected_pairs_sha256=None):
    value=json.loads(Path(path).read_text());rows=value['candidates'];unique={}
    if expected_pairs_sha256 is not None and value['pairs_sha256']!=expected_pairs_sha256:
        raise ValueError('候选训练数据身份不符')
    for row in rows:
        expected=hashlib.sha256(json.dumps(row['parameters'],sort_keys=True).encode()).hexdigest()
        if expected!=row['sha256']:raise ValueError('候选参数摘要不符')
        if row['sha256'] not in unique or row['score']<unique[row['sha256']]['score']:unique[row['sha256']]=row
    ordered=sorted(unique.values(),key=lambda r:(r['score'],r['sha256']))
    if len(ordered)<=limit:return ordered
    # 同时保留原生灰阶较好、与 PC 最优点不同的分解，避免短名单全靠补偿曲线。
    chosen=[ordered[0],min(ordered,key=lambda r:r['native_gray'])]
    seen={r['sha256'] for r in chosen};result=list({r['sha256']:r for r in chosen}.values())
    for row in ordered:
        if len(result)>=limit:break
        if row['sha256'] not in seen:result.append(row);seen.add(row['sha256'])
    return result[:limit]
