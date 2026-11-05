"""Frozen shared C1 response, without hue experts; same calibrated 81x3 model."""
import numpy as np
from paired_response import PairedModel, _c1_basis, _c1_basis_tensor


class SharedC1Model(PairedModel):
    def __init__(self, value, digest, identity=None):
        weights=np.asarray(value['response_weights'],float)
        if value.get('response_basis')!='rgb-hierarchical-c1-3x3x3' or weights.shape!=(81,3) or not np.isfinite(weights).all():
            raise ValueError('Expected finite shared C1 81x3 response')
        # Reuse the unchanged coordinate/stencil/fit machinery. Historical
        # PairedModel inference remains byte-for-byte intact for saved jobs.
        super().__init__(dict(value,response_basis='rgb-linear',response_weights=np.zeros((12,3)).tolist()),digest,identity)
        self.weights=weights
        self.value=dict(value,metadata=dict(model='ILCE-7RM5',physical_scope=value.get('scope','paired image capture')))
        self.shared_c1=True

    def response(self,rgb):
        return np.einsum('nb,cbo->nco',_c1_basis(np.asarray(rgb,float)),self.weights.reshape(3,27,3))/256

    def response_tensor(self,tools,rgb):
        return tools.torch.einsum('nb,cbo->nco',_c1_basis_tensor(tools,rgb),tools.tensor(self.weights.reshape(3,27,3)))/256
