"""固定原生前端的精确CPU缓存；只对已知线性整数网格响应启用。"""
from collections import OrderedDict
import copy,hashlib,json
import numpy as np
import core
from native_runtime import blob,predict
from packed_training import native_prediction
from measured_response import get
from fit_bin_joint import grid_from


class CachedForward:
    def __init__(self,context,response,limit=2):
        self.context=context;self.response=copy.deepcopy(response);self.limit=limit
        self.cache=OrderedDict();self.native_evaluations=0
        self.enabled=response.get('preset')=='r5-paired-20261107-nonlinear-he3'

    def __call__(self,entry,inputs):
        if not self.enabled:return predict(self.context,entry,inputs,self.response)
        entry=core.compiler.unpack(blob(entry))['entries'][0];inputs=np.asarray(inputs)
        native_key=json.dumps([entry[k] for k in ('gamma_native_129','cc1_delta','block13')],separators=(',',':'))
        if native_key not in self.cache:
            self.cache[native_key]={}
            while len(self.cache)>self.limit:self.cache.popitem(last=False)
        self.cache.move_to_end(native_key);bucket=self.cache[native_key]
        key=(inputs.dtype.str,inputs.shape,hashlib.sha256(np.ascontiguousarray(inputs).tobytes()).digest())
        if key not in bucket:
            native=native_prediction(self.context,entry,inputs);response=get(self.response)
            _,ids,weights=response.stencil(native);mix=response.response(native)
            bucket[key]=(native,ids,weights,mix);self.native_evaluations+=1
        native,ids,weights,mix=bucket[key]
        delta=(grid_from(entry)[ids]*weights[...,None]).sum(1)
        return np.clip(native+np.einsum('nc,nco->no',delta,mix),0,1)
