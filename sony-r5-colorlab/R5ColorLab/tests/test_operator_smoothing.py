"""Physical operator priors: independent native geometry and Torch parity."""
import copy
import struct
import unittest
from pathlib import Path
import numpy as np
import core
import parameter_smoothing as p


def config(unequal=False,quadratic=True):
    cfg=bytearray(0x228)
    angles=np.array([0,41,96,147,214,258,326,391,458,530,590,655,723,790,865,943] if unequal else np.arange(16)*64)
    spans=np.r_[np.diff(angles),1024-angles[-1]]
    struct.pack_into('<16H',cfg,6,*angles)
    struct.pack_into('<H',cfg,0x26,1)
    # Actual integer normalization need not multiply each span to exactly1.
    struct.pack_into('<16H',cfg,0x1e8,*np.rint(16384/spans).astype(int))
    struct.pack_into('<16f',cfg,0x1a8,*np.linspace(.6,1.3,16))
    struct.pack_into('<3f',cfg,0x208,1.,.95,1.07)
    struct.pack_into('<3f',cfg,0x214,23.,41.,17.)
    struct.pack_into('<H',cfg,0x220,1)
    struct.pack_into('<H',cfg,0x222,int(quadratic))
    return bytes(cfg)


class OperatorSmoothingTests(unittest.TestCase):
    def test_gamma_nonuniform_linear_zero_and_spike_and_reversal(self):
        x=np.geomspace(1,1000,128)-1;y=x/x[-1]*262143;c=np.zeros((6,16))
        rows=p.native_rows(c,y,x,30)
        self.assertLess(np.linalg.norm(rows),1e-12)
        spiked=y.copy();spiked[50]+=1000
        self.assertGreater(np.linalg.norm(p.native_rows(c,spiked,x,30)),.001)
        # Isolate negative-slope rows after the block and Gamma curvature.
        reverse=y.copy();reverse[10]=reverse[9]-500
        rr=p.native_rows(c,reverse,x,30)
        gamma_monotone=rr[7776+126:7776+126+127]
        self.assertGreater(np.linalg.norm(gamma_monotone),0)
        np.testing.assert_array_equal(p.native_rows(c,reverse,x,0),0)

    def test_actual_nonuniform_block_interpolation_and_positive_quadratic(self):
        rng=np.random.default_rng(42);c=rng.normal(0,.2,(6,16));cfg=config(True)
        w,wl,wr,dx,scales,diag,threshold,quad,enabled=p._geometry(cfg)
        self.assertTrue(quad and enabled)
        self.assertEqual(w.shape,(64,16));self.assertAlmostEqual(dx.sum(),1)
        angles=np.array(struct.unpack_from('<16H',cfg,6),float)
        norms=np.array(struct.unpack_from('<16H',cfg,0x1e8),float)
        scales=np.array(struct.unpack_from('<16f',cfg,0x1a8))
        diag=np.array(struct.unpack_from('<3f',cfg,0x208));th=np.array(struct.unpack_from('<3f',cfg,0x214))/16384
        positions=[];outputs=[]
        for i in range(16):
            end=angles[(i+1)%16]+(1024 if i==15 else 0)
            for f in (0,.25,.5,.75):
                pos=angles[i]+(end-angles[i])*f;positions.append(pos/1024)
                weights=np.array([end-pos,pos-angles[i]])*norms[i]/16384
                q=c[:,[i,(i+1)%16]]@weights
                z=(c[:,[i,(i+1)%16]]*scales[[i,(i+1)%16]])@weights
                a,b,cc,d,e,ff=q
                lin=np.array([[a+b+diag[0],-a,-b],[-cc,cc+d+diag[1],-d],[-e,-ff,e+ff+diag[0]]])
                a,b,cc,d,e,ff=z
                sq=np.array([[-a-b,a,b],[cc,-cc-d,d],[e,ff,-e-ff]])
                n=(p._PROBES*p._PROBES)@sq.T
                # Native only adds the positive branch above threshold.
                outputs.append(p._PROBES@lin.T+np.where(n>=0,np.maximum(n-th,0),0))
        positions=np.asarray(positions);out=np.asarray(outputs)
        dd=np.roll(positions,-1)-positions;dd[-1]+=1
        rate=(np.roll(out,-1,axis=0)-out)/dd[:,None,None]
        mid=(dd+np.roll(dd,1))/2;curve=(rate-np.roll(rate,1,axis=0))/mid[:,None,None]
        x=np.linspace(0,1000,128);y=x/x[-1]*262143
        rows=p.native_rows(c,y,x,100,config=cfg)
        np.testing.assert_allclose(rows[:3456].reshape(64,18,3),rate*np.sqrt(dd)[:,None,None]*p.RATES['block_rate']/np.sqrt(54),atol=2e-17)
        np.testing.assert_allclose(rows[3456:6912].reshape(64,18,3),curve*np.sqrt(mid)[:,None,None]*p.RATES['block_curvature']/np.sqrt(54),atol=2e-17)
        self.assertGreater(np.linalg.norm(rows[6912:7776]),0)
        # Setting coefficients to zero leaves a constant diagonal map, so a
        # nonuniform sector axis alone has no hue rate/curvature penalty.
        zero=p.native_rows(np.zeros((6,16)),y,x,100,config=cfg)
        np.testing.assert_allclose(zero[:7776],0,atol=1e-16)

    def test_cc1_true_branch_jacobian_not_rotating_circle_curvature(self):
        cc=np.array([.2,-.1,-.3,.4,1.4,1.7,1.8,1.2])
        jac=p._cc1_jacobians(cc,p._Numpy())
        def chroma(x):
            dr,db=x[:,0],x[:,1]
            cr=dr+db*np.where(db>=0,cc[0],cc[2]);cb=db+dr*np.where(dr>=0,cc[1],cc[3])
            return np.column_stack([.5*cr*np.where(cr>=0,cc[5],cc[7]),.5*cb*np.where(cb>=0,cc[4],cc[6])])
        direction=p._CC_DIRECTION
        for axis in range(2):
            step=np.zeros((1,2));step[0,axis]=1e-6
            diff=(chroma(direction+step)-chroma(direction-step))/(2e-6)
            np.testing.assert_allclose(diff,jac[:,:,axis],atol=2e-10)
        x=np.linspace(0,1000,128);y=x/x[-1]*262143;c=np.zeros((6,16))
        # Equal sign branches are a single linear transform: zero branch cost,
        # even though its output on a rotating circle has sinusoidal curvature.
        linear=np.array([.2,-.1,.2,-.1,1.4,1.7,1.4,1.7])
        self.assertLess(np.linalg.norm(p.native_rows(c,y,x,30,cc1=linear)[-320:]),1e-12)
        self.assertGreater(np.linalg.norm(p.native_rows(c,y,x,30,cc1=cc)[-320:-64]),0)
        large=linear.copy();large[4:]=12
        self.assertGreater(np.linalg.norm(p.native_rows(c,y,x,30,cc1=large)[-64:]),0)

    def test_numpy_torch_rows_and_gradients_all_native_components(self):
        import torch
        from gpu_tensor import TensorTools
        tools=TensorTools('cpu',torch.float64)
        rng=np.random.default_rng(8);c=rng.uniform(-.2,.2,(6,16))
        x=np.geomspace(1,2097121,128)-1;y=(x/x[-1])**.5*262143
        cc=np.array([.2,-.1,-.3,.4,1.4,1.7,1.8,1.2]);cfg=config(True)
        expected=p.native_rows(c,y,x,30,cc,cfg)
        tc=tools.tensor(c).requires_grad_(True);ty=tools.tensor(y).requires_grad_(True);tcc=tools.tensor(cc).requires_grad_(True)
        actual=p.native_rows_tensor(tools,tc,ty,tools.tensor(x),30,tcc,cfg)
        np.testing.assert_allclose(actual.detach().numpy(),expected,atol=2e-15)
        actual.square().sum().backward()
        for tensor in (tc,ty,tcc):self.assertTrue(torch.isfinite(tensor.grad).all())
        dc=rng.normal(size=c.shape);dy=rng.normal(size=y.shape);dcc=rng.normal(size=cc.shape);eps=1e-5
        def loss(t):
            r=p.native_rows(c+t*dc,y+t*dy,x,30,cc+t*dcc,cfg);return r@r
        fd=(loss(eps)-loss(-eps))/(2*eps)
        grad=float((tc.grad*tools.tensor(dc)).sum()+(ty.grad*tools.tensor(dy)).sum()+(tcc.grad*tools.tensor(dcc)).sum())
        self.assertAlmostEqual(fd,grad,delta=2e-9)

    def test_integer_native_cost_decodes_same_operator(self):
        from edit_parameter_context import ParameterContext,RuntimeColor
        folder=Path(p.__file__).resolve().parent/'data/chart/sony100mp_5300k_v45/capture'
        ctx=ParameterContext(RuntimeColor.from_capture(folder,16))
        c=np.array(struct.unpack_from('<96f',ctx.base.config,0x28))
        raw=ctx.cc1;bits=(raw[:4]&65535)>>2&511
        cc=np.r_[np.where(bits>255,bits-512,bits)/256,((raw[4:]&65535)>>3&255)/64]
        params=dict(matrix_payload=ctx.payload,cc1=ctx.cc1,gamma_y=ctx.gamma_y)
        rows=p.native_rows(c,ctx.gamma_y,ctx.axis,30,cc,ctx.base.config)
        self.assertEqual(p.native_cost(params,ctx.axis,30),float(rows@rows*255**2))
        self.assertLess(p.native_cost(params,ctx.axis,30),.1)
        self.assertEqual(p.native_cost(params,ctx.axis,0),0)


if __name__=='__main__':unittest.main()
