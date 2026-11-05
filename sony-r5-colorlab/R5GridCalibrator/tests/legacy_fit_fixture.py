from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model

LEGACY_OPTIONS=dict(coordinate_device="cpu",response_degree=1,hue24_balance=False,perceptual_mix=0,nonlinear_coordinates=False,structured_response=False,curvature_scale=1.,samples_per_pair=480,max_nfev=150)

def legacy_fit(*args, **kwargs):
    options=dict(LEGACY_OPTIONS)
    options.update(kwargs.pop("options",None) or {})
    return model.fit(*args,options=options,**kwargs)
