"""缓存只复用相同原生前端与输入；必须与独立旧回放逐值一致。"""
import copy
import numpy as np
import baseline,core
from edit_parameter_context import ParameterContext,RuntimeColor
from grid_models import default_response
from packed_training import native_prediction
from measured_response import get
from native_cached_forward import CachedForward
from fit_bin_joint import grid_from


def test_cached_grid_changes_input_mutation_and_native_changes_match_uncached():
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    response=default_response();cache=CachedForward(context,response)
    x=np.random.default_rng(42).integers(0,16384,(41,9,3),dtype=np.uint16)
    e=copy.deepcopy(core.presets()[0][0]);changed=copy.deepcopy(e)
    table=np.asarray(changed['grid_5x9x9']['coefficients']);table.flat[60]=1
    changed['grid_5x9x9']['coefficients']=table.tolist()
    def check(entry):
        expected=get(response).predict_cpu(native_prediction(context,entry,x),grid_from(entry))
        np.testing.assert_array_equal(cache(entry,x),expected)
    check(e);check(changed)
    assert cache.native_evaluations==1
    x[0,4,0]+=512;check(changed)
    assert cache.native_evaluations==2
    changed['gamma_native_129']=np.rint(np.array(changed['gamma_native_129'])*.97).astype(int).tolist()
    check(changed)
    assert cache.native_evaluations==3
