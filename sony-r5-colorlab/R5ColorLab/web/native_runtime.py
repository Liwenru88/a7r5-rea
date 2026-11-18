"""训练、研究与验收共用的原生整数回放与BIN往返工具。"""
import hashlib,json
from pathlib import Path
import numpy as np
import core
from measured_response import get
from fit_bin_joint import grid_from
from native_scoring import color_metrics

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n')


def blob(entry):
    result=core.compiler.pack(core.compiler.config([entry],5))
    if core.compiler.pack(core.compiler.unpack(result))!=result:raise ValueError('BIN往返变化')
    return result


def predict(context,entry,inputs,response):
    entry=core.compiler.unpack(blob(entry))['entries'][0]
    model=context.build(**core.slot_native_parameters(context,entry))
    values=np.concatenate([model.color_only(inputs[i:i+8192])[:,2:7].mean(1)/16383
                           for i in range(0,len(inputs),8192)])
    return get(response).predict_cpu(values,grid_from(entry))


def combined_metrics(prediction,target,gray_prediction,gray_target):
    return dict(color_metrics(prediction,target),gray_rmse=color_metrics(gray_prediction,gray_target)['rgb_rmse'])

