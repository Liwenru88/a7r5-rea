"""D65 sRGB -> OKLab; Euclidean OKLab loss, not CIEDE2000."""
import numpy as np
M1=np.array([[.4122214708,.5363325363,.0514459929],[.2119034982,.6806995451,.1073969566],[.0883024619,.2817188376,.6299787005]])
M2=np.array([[.2104542553,.7936177850,-.0040720468],[1.9779984951,-2.4285922050,.4505937099],[.0259040371,.7827717662,-.8086757660]])
def oklab(rgb):
 x=np.clip(np.asarray(rgb),0,1);linear=np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
 return np.cbrt(linear@M1.T)@M2.T
def lab_jacobian(rgb):
 x=np.clip(np.asarray(rgb),0,1);linear=np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
 slope=np.where(x<=.04045,1/12.92,2.4/1.055*((x+.055)/1.055)**1.4)
 lms=linear@M1.T
 # Zero/near-zero channels are regularized for finite derivatives only.
 cube_slope=1/(3*np.maximum(lms,1e-8)**(2/3))
 return np.einsum('ok,nk,ki,ni->noi',M2,cube_slope,M1,slope)
def squash(e,scale):return e*np.sqrt(2/(np.sqrt(1+(e/scale)**2)+1)) if scale else e
def joint_residual(pred,target,scale,mix):
 rgb=squash(pred-target,scale/255)
 if not mix:return rgb
 return np.concatenate([rgb,np.sqrt(mix)*squash(oklab(pred)-oklab(target),.03)],axis=-1)
def metrics(pred,target):
 p=oklab(pred);t=oklab(target);d=p-t;cp=np.linalg.norm(p[:,1:],axis=1);ct=np.linalg.norm(t[:,1:],axis=1)
 de=np.linalg.norm(d,axis=1)*100
 sat=(target.max(1)-target.min(1))/np.maximum(target.max(1),1e-8)
 # Gate only on target, so predictions cannot disappear from evaluation by losing chroma.
 keep=(sat>=.15)&(ct>=.03)&(t[:,0]>=.08)&(t[:,0]<=.95)
 angle=abs(np.degrees(np.arctan2(p[:,2],p[:,1])-np.arctan2(t[:,2],t[:,1])));angle=np.minimum(angle,360-angle)
 return dict(count=len(p),deltaE_OK_mean=float(de.mean()),deltaE_OK_p95=float(np.percentile(de,95)),lightness_mae=float(abs(d[:,0]).mean()*100),chroma_mae=float(abs(cp-ct).mean()*100),hue_count=int(keep.sum()),hue_degrees_mae=float(angle[keep].mean()) if keep.any() else None,hue_degrees_p95=float(np.percentile(angle[keep],95)) if keep.any() else None,hue_predicted_near_gray_count=int(((cp<.03)&keep).sum()),hue_gate='target HSV S>=0.15, OKLab C>=0.03, 0.08<=L<=0.95; prediction never used for exclusion',units='OKLab differences x100; hue degrees; not CIEDE2000')
def torch_oklab(x,torch):
 linear=torch.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
 lms=linear@torch.as_tensor(M1.T,dtype=x.dtype,device=x.device)
 return torch.where(lms>0,torch.clamp(lms,min=1e-12).pow(1/3),torch.zeros_like(lms))@torch.as_tensor(M2.T,dtype=x.dtype,device=x.device)
