"""Empirical grid response, using measured inverse coordinates and a TPS forward map.

No BT.601 transform, fixed RGB mixing matrix, or 1/256 gain is assumed here.
A snapshot is evidence-scoped and must predict independent nonzero grid captures.
"""
import hashlib
import json
from functools import lru_cache
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"vendor/fit_eval_python312"))
import numpy as np
from scipy.interpolate import NdBSpline
from scipy.optimize import least_squares
from scipy import sparse

SCHEMA = 'r5-measured-grid-response/1'
PRESET_SHA256 = '7e183f46f7acd739a12b7c2989e0ce245628a1f0d72d4f673f48945f4493b0af'

def legacy_proxy_response():
    return dict(schema=SCHEMA,preset='qaq-a7c2-2.01-c8328ad5',sha256=PRESET_SHA256,proxy_for='ILCE-7RM5')


def previous_r5_response():
    return {'schema': 'r5-measured-grid-response/1', 'preset': 'r5-paired-20261024', 'sha256': '6852ead83bf381215a8d721d1557cc73803f6ef60a0745971e8783144863c96b', 'model': 'ILCE-7RM5'}


def v2_response():
    return {'schema': 'r5-measured-grid-response/1', 'preset': 'r5-paired-20261024-v2', 'sha256': '8879499fbd9b24899dcbd8fee4135b806fdcba1fd18a677b090b7af212b85a45', 'model': 'ILCE-7RM5'}


def nonlinear_response():
    return dict(schema=SCHEMA,preset='r5-paired-20261102-nonlinear',sha256='a312761c8500e8a9ecb3b1b23ad27cf7709cb6eb8bf41c956970e1bdcc2c82f0',model='ILCE-7RM5')


def shared_response():
    return {'schema': 'r5-measured-grid-response/1', 'preset': 'r5-paired-20261102-shared-c1-c50', 'sha256': 'e794ece2fe8f4114eb241e376918bffbc4c182e9fadf0f6fa21d99fdd7a1b552', 'model': 'ILCE-7RM5'}

def default_response():
    return dict(schema=SCHEMA,preset='r5-paired-20261102-three-experts',sha256='3cecec3387acbd72524be42db34586237df0c2c7d458d4090467375d28fa0815',model='ILCE-7RM5')


def is_measured(value):
    return isinstance(value, dict) and value.get('schema') == SCHEMA

def require(value):
    if not is_measured(value):
        raise ValueError('请先导入 R5 实测网格响应标定 JSON；不能使用固定 3×3 矩阵替代实测模型')
    get(value)
    return value

def get(value):
    if not is_measured(value):
        raise ValueError('Unknown measured grid response schema')
    return _cached(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')))

@lru_cache(maxsize=8)
def _cached(serialized):
    value = json.loads(serialized)
    if value.get('preset')=='r5-paired-20261102-shared-c1-c50':
        if value!=shared_response():raise ValueError('Shared C1 identity mismatch')
        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261102-shared-c1-c50.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('Shared C1 hash mismatch')
        from shared_c1_response import SharedC1Model
        return SharedC1Model(json.loads(raw),value['sha256'],identity=value)
    if value.get('preset')=='r5-paired-20261102-three-experts':
        if value!=default_response():raise ValueError('R5 three-expert snapshot identity mismatch')
        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261102-three-experts.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('R5 three-expert model hash mismatch')
        from paired_response import PairedModel
        return PairedModel(json.loads(raw),value['sha256'],identity=value)
    if value.get('preset')=='r5-paired-20261102-nonlinear':
        if value!=nonlinear_response():raise ValueError('R5 nonlinear snapshot identity mismatch')
        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261102-nonlinear.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('R5 nonlinear model hash mismatch')
        from paired_response import PairedModel
        return PairedModel(json.loads(raw),value['sha256'],identity=value)
    if value.get('preset')=='r5-paired-20261024-v2':
        if value!=v2_response():raise ValueError('R5 v2 snapshot identity mismatch')
        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261024-v2.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('R5 v2 model hash mismatch')
        from paired_response import PairedModel
        return PairedModel(json.loads(raw),value['sha256'],identity=value)
    if value.get('preset')=='r5-paired-20261024':
        if value!=previous_r5_response():raise ValueError('R5 snapshot identity mismatch')
        from pathlib import Path
        path=Path(__file__).resolve().parent/'data/r5/paired-20261024.json'
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('R5 measured model hash mismatch')
        from paired_response import PairedModel
        return PairedModel(json.loads(raw),value['sha256'],identity=value)
    if value.get('preset'):
        from pathlib import Path
        if value != legacy_proxy_response():raise ValueError('Unknown proxy snapshot identity')
        folder=Path(__file__).resolve().parent
        # Both standalone and original workspaces carry the same pinned snapshot.
        candidates=(folder.parent/'data/qaq/a7c2-2.01.virtual.npz',folder/'data/qaq/a7c2-2.01.virtual.npz')
        path=next((f for f in candidates if f.is_file()),None)
        if path is None:raise ValueError('缺少 QAQ 实测代理参数文件')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=PRESET_SHA256:raise ValueError('实测代理参数散列不匹配')
        with np.load(path,allow_pickle=False) as archive:
            metadata=json.loads(str(archive['metadata']))
            arrays={key:archive[key].tolist() for key in archive.files if key.startswith('base_')}
            anchors=archive['anchor_source'].tolist()
        value=dict(schema=SCHEMA,metadata={**metadata,'evidence':'QAQLeonard/a7c2-fl23-research @ c8328ad5; NPZ SHA256 '+PRESET_SHA256},
                   arrays=arrays,proxy_for='ILCE-7RM5',anchor_source=anchors,preset_verified=True)
    if len(serialized) > 16 * 1024 * 1024:
        raise ValueError('标定模型过大')
    return Model(value, hashlib.sha256(serialized.encode()).hexdigest())


# These are the two registry implementations recorded by retained formal jobs.
# Their original source copies and a legacy-class oracle are independently
# checked in test_response_provenance; this is not a general hash bypass.
_LEGACY_RESPONSE_IMPLEMENTATIONS = {
    'r5-paired-20261024-v2': frozenset({'ac25d665dde7fc285affb4be1a862a647c767e339cea0aa4b756e77693199428'}),
    'r5-paired-20261102-nonlinear': frozenset({'2ee8128f87491ac15e1885e32594620aa04c92aa7a4acd8bf15977fa5ce27ac5'}),
}
# Set only after the preserved legacy oracle and CPU/Torch parity tests pass.
_LEGACY_VERIFIED_INFERENCE_SHA256 = '47b0581148727a1e5d476d1881a75742296a001e071a3c388bd6dff68a78c9d4'


def _inference_ast(path, names=None):
    """Hash executable inference AST; fitting/regularizer edits are irrelevant.

    Imports are included, docstrings/comments are excluded. Explicit method and
    constant names keep a training-only change from invalidating a frozen grid.
    """
    import ast
    class WithoutDocstrings(ast.NodeTransformer):
        def generic_visit(self, node):
            node = super().generic_visit(node)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    node.body = node.body[1:]
            return node
    tree = WithoutDocstrings().visit(ast.parse(path.read_text()))
    if names is None:
        selected = tree.body
    else:
        selected = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        by_name = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                by_name[node.name] = node
                if isinstance(node, ast.ClassDef):
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            by_name[node.name + '.' + method.name] = method
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name): by_name[target.id] = node
        for name in names:
            if name not in by_name: raise ValueError('Missing response inference source: ' + name)
            selected.append(by_name[name])
    value = ast.dump(ast.Module(body=selected, type_ignores=[]), include_attributes=False)
    return hashlib.sha256(value.encode()).hexdigest()


def inference_sources(response):
    """Exact response paths used by CPU, Metal, preview and signed-byte export."""
    get(response)  # Includes model JSON SHA and full pinned identity validation.
    here = Path(__file__).resolve().parent
    common = {
        'measured_response.py': ('is_measured', 'require', 'get', '_cached'),
        'paired_coordinates.py': None,
        '../scripts/residual_grid.py': ('SHAPE', 'NODES', 'stencil', 'coefficients', 'pack', 'unpack'),
        'gpu_tensor.py': ('TensorTools.__init__', 'TensorTools.tensor', 'stencil_tensor'),
    }
    if response.get('preset', '').startswith('r5-paired-'):
        common.update({
            'paired_response.py': ('_DETAIL_INDICES', '_EXPERT_DIRECTIONS', '_c1_basis', '_c1_basis_tensor',
                'PairedModel.__init__', 'PairedModel.coordinates', 'PairedModel.stencil',
                'PairedModel.response', 'PairedModel.coordinates_tensor', 'PairedModel.response_tensor',
                'PairedModel.predict', 'PairedModel.predict_cpu'),
            'gpu_color.py': ('paired_tensor', 'paired_numpy'),
        })
    else:
        common['measured_response.py'] = ('Model.__init__', 'Model.coordinates', 'Model.forward', 'Model.stencil', 'Model.predict')
    if response.get('preset')=='r5-paired-20261102-shared-c1-c50':
        common['shared_c1_response.py']=None
    sources = {name: _inference_ast(here / name, names) for name, names in sorted(common.items())}
    if response.get('preset')!='r5-paired-20261102-shared-c1-c50':
        # A new disjoint registry arm cannot execute for an old identity.
        # Remove only its exact audited source when fingerprinting old paths;
        # any edit inside this arm prevents removal and fails old validation.
        addition = "    if value.get('preset')=='r5-paired-20261102-shared-c1-c50':\n        if value!=shared_response():raise ValueError('Shared C1 identity mismatch')\n        raw=(__import__('pathlib').Path(__file__).resolve().parent/'data/r5/paired-20261102-shared-c1-c50.json').read_bytes()\n        if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('Shared C1 hash mismatch')\n        from shared_c1_response import SharedC1Model\n        return SharedC1Model(json.loads(raw),value['sha256'],identity=value)\n"
        class OldRegistryPath:
            def read_text(self):
                source=(here/'measured_response.py').read_text()
                if source.count(addition)!=1:raise ValueError('Shared registry dispatch changed')
                return source.replace(addition,'',1)
        sources['measured_response.py']=_inference_ast(OldRegistryPath(),common['measured_response.py'])
    return sources


def runtime_fingerprint(response):
    manifest = dict(schema='r5-grid-response-inference/1', response=response,
                    sources=inference_sources(response))
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_saved_runtime(identity):
    """Check new double bindings, or a narrowly certified old implementation.

    Never edits historical result identities or silently selects today's model.
    The legacy branch is scoped to known source hashes AND current inference.
    """
    response = identity['response']
    current_registry = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    current_sources = inference_sources(response)
    recorded_runtime = identity.get('response_runtime_sha256')
    if recorded_runtime is not None:
        if (identity.get('response_implementation_sha256') not in (current_registry, '288a86611ee4cc9fe9aa4caf896f597d44ff406807d1703f7b9d88bbde5d8cb1') or
                recorded_runtime != runtime_fingerprint(response)):
            raise ValueError('实测响应推理实现已变化，请重新训练压缩网格')
        return
    known = _LEGACY_RESPONSE_IMPLEMENTATIONS.get(response.get('preset'), frozenset())
    inference_digest = hashlib.sha256(json.dumps(current_sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (identity.get('response_implementation_sha256') not in known or
            inference_digest != _LEGACY_VERIFIED_INFERENCE_SHA256):
        raise ValueError('历史实测响应未通过已知实现与推理等价核验，请重新训练压缩网格')

class Model:
    def __init__(self, value, digest):
        self.value, self.sha256 = value, digest
        meta = value['metadata']
        self.proxy=value.get('preset_verified') is True and meta.get('model')=='ILCE-7CM2'
        if (meta.get('model') != 'ILCE-7RM5' and not self.proxy) or not all(isinstance(meta.get(k), str) and meta[k].strip() for k in ('firmware', 'physical_scope', 'evidence')):
            raise ValueError('需要明确机型、固件、测量范围与原始采集来源的 R5 标定；拒绝 A7C2 响应')
        a = value['arrays']
        def arr(name):
            out = np.asarray(a[name], dtype=float)
            if not np.isfinite(out).all():raise ValueError('Nonfinite calibration array: '+name)
            return out
        self.knots, self.inverse, self.scale = [arr(k) for k in ('base_knots','base_inverse','base_scale')]
        n = len(self.knots)-4
        if (self.knots.ndim != 1 or not 4 <= n <= 20 or np.any(np.diff(self.knots)<0)
            or self.knots[3] != 0 or self.knots[-4] != 1
            or self.inverse.shape != (n**3,3) or self.scale.shape != (3,) or np.any(self.scale<=0) or np.any(self.scale>1)):
            raise ValueError('Invalid cubic inverse map or measured coefficient scales')
        self.x,self.a,self.b,self.shift,self.norm = [arr('base_forward_'+k) for k in ('x','a','b','shift','scale')]
        m=len(self.x)
        if (self.x.shape!=(m,3) or not 4<=m<=2048 or self.a.shape!=(m,3) or self.b.shape!=(4,3)
            or self.shift.shape!=(3,) or self.norm.shape!=(3,) or np.any(self.norm<=0)):
            raise ValueError('Invalid thin-plate spline forward response')
        if self.proxy:
            self.validation=dict(source='author-supplied measured A7C2 snapshot',independent_revalidated=False,
                R5_calibrated=False,new_scene_camera_verified=False,source_sha256=PRESET_SHA256)
            return
        check=value['validation']
        source=np.asarray(check['source_rgb'],float)
        tables=np.asarray(check['tables'],float)
        actual=np.asarray(check['observed_rgb'],float)
        if (check.get('independent') is not True or not isinstance(check.get('evidence'),str) or not check['evidence'].strip()
            or source.ndim!=2 or source.shape[1]!=3 or not 25<=len(source)<=8192
            or tables.ndim!=3 or tables.shape[1:]!=(405,3) or not 1<=len(tables)<=8
            or actual.shape!=(len(tables),len(source),3)
            or not all(np.isfinite(v).all() for v in (source,tables,actual))
            or np.any((source<0)|(source>1)) or np.any((actual<0)|(actual>1))
            or np.any(tables!=np.rint(tables)) or np.any((tables<-64)|(tables>63)) or not np.any(tables)):
            raise ValueError('需要独立非零网格拍摄及至少25个留出色块，不能只用零表验收')
        errors=np.concatenate([np.abs(self.predict(source,t)-y).ravel()*255 for t,y in zip(tables,actual)])
        self.validation=dict(mae_8bit=float(errors.mean()),p95_8bit=float(np.percentile(errors,95)),
                             independent=True,samples=len(source),tables=len(tables))
        if self.validation['mae_8bit']>2.5 or self.validation['p95_8bit']>8:
            raise ValueError('实测响应未通过独立网格预测门槛（MAE≤2.5、P95≤8）：'+str(self.validation))

    def probes(self,count,seed=20261022):
        from scipy.spatial import cKDTree
        anchors=np.asarray(self.value.get('anchor_source',[]),float)
        if anchors.ndim!=2 or anchors.shape[1]!=3 or len(anchors)<8:
            raise ValueError('Measured model requires source anchors for in-gamut compression probes')
        keep=(anchors.min(1)>.015)&(anchors.max(1)<.985);anchors=anchors[keep]
        if len(anchors)<8:raise ValueError('Insufficient measured source anchors')
        nearest=cKDTree(anchors).query(anchors,k=8)[1]
        rng=np.random.default_rng(seed);a=rng.integers(len(anchors),size=count)
        b=nearest[a,rng.integers(1,8,size=count)];w=rng.uniform(.15,.85,(count,1))
        return anchors[a]*(1-w)+anchors[b]*w

    def coordinates(self,rgb):
        design=NdBSpline.design_matrix(np.ascontiguousarray(rgb,dtype=float), (self.knots,)*3,(3,)*3,extrapolate=True)
        design.resize((len(rgb),len(self.inverse)))
        return design @ self.inverse

    def forward(self, coordinates, derivative=False):
        points=np.asarray(coordinates,float);parts=[]
        for start in range(0,len(points),128):
            at=points[start:start+128];d=at[:,None,:]-self.x[None,:,:];r2=(d*d).sum(2)
            if derivative:
                parts.append(np.einsum('nmi,mo->nio',d*(np.log(np.maximum(r2,1e-300))+1)[:,:,None],self.a)+self.b[1:]/self.norm[:,None])
            else:
                kernel=.5*r2*np.log(np.maximum(r2,1e-300))
                parts.append(kernel@self.a+np.c_[np.ones(len(at)),(at-self.shift)/self.norm]@self.b)
        return np.concatenate(parts) if parts else np.empty((0,3,3) if derivative else (0,3))

    def stencil(self, rgb):
        from residual_grid import stencil
        coordinates=self.coordinates(rgb)
        # Existing stencil accepts chroma axes centred at zero; measured axes are all 0..1.
        ids,weights=stencil(np.clip(coordinates,0,1)-[0,.5,.5])
        return coordinates,ids,weights

    def predict(self,rgb,table,clip=True):
        source=np.asarray(rgb,float)
        if source.ndim!=2 or source.shape[1]!=3 or not np.isfinite(source).all():raise ValueError('Expected finite Nx3 RGB')
        coordinates,ids,weights=self.stencil(source)
        corrections=(np.asarray(table)[ids]*weights[...,None]).sum(1)
        # Anchor to source zero-grid RGB, as in current nativefit.Problem.
        output=source+np.clip(self.forward(coordinates+corrections*self.scale),0,1)-np.clip(self.forward(coordinates),0,1)
        return np.clip(output,0,1) if clip else output

    def fit(self,base,target,weights,strength=.01):
        from pc_stages import neighbor_design
        base,target=np.asarray(base,float),np.asarray(target,float)
        weights=np.asarray(weights,float)
        if base.shape!=target.shape or weights.shape!=(len(base),) or np.any(weights<=0) or not np.isfinite(weights).all() or not np.isfinite(target).all():raise ValueError('Invalid measured-grid training data')
        coordinates,ids,w=self.stencil(base)
        design=sparse.coo_matrix((w.ravel(),(np.repeat(np.arange(len(base)),8),ids.ravel())),shape=(len(base),405)).tocsr()
        regularizer=sparse.kron(neighbor_design((5,9,9)),sparse.eye(3),format='csr')*np.sqrt(strength/405)/256
        mass=np.sqrt(weights/weights.sum())
        zero=np.clip(self.forward(coordinates),0,1)
        def values(v):
            at=coordinates+(design@v.reshape(405,3))*self.scale
            forward=self.forward(at)
            raw=base+np.clip(forward,0,1)-zero
            return at,forward,raw
        def loss(v):
            _,_,raw=values(v)
            return np.r_[((np.clip(raw,0,1)-target)*mass[:,None]).ravel(),regularizer@v]
        def jac(v):
            at,forward,raw=values(v)
            derivative=self.forward(at,derivative=True)*self.scale[None,:,None]
            derivative*=((forward>0)&(forward<1))[:,None,:]*((raw>0)&(raw<1))[:,None,:]
            rows=[];cols=[];data=[]
            for channel in range(3):
                for output in range(3):
                    rows.append(np.repeat(np.arange(len(base))*3+output,8));cols.append((ids*3+channel).ravel())
                    data.append((w*derivative[:,channel,output,None]*mass[:,None]).ravel())
            matrix=sparse.coo_matrix((np.concatenate(data),(np.concatenate(rows),np.concatenate(cols))),shape=(len(base)*3,1215)).tocsr()
            return sparse.vstack((matrix,regularizer),format='csr')
        initial=np.zeros(1215)
        result=least_squares(loss,initial,jac=jac,bounds=(-64,63),method='trf',tr_solver='lsmr',max_nfev=100,ftol=1e-6,xtol=1e-6,gtol=1e-7)
        vector=result.x if np.isfinite(result.fun).all() and np.linalg.norm(result.fun)<=np.linalg.norm(loss(initial)) else initial
        table=np.clip(np.rint(vector.reshape(405,3)),-64,63).astype(np.int8)
        return table,dict(model_sha256=self.sha256,regularization=strength,training_only=True,
            objective='measured inverse coordinates + trilinear signed7 offsets + nonlinear forward response; source-anchored',
            evaluations=result.nfev,converged=bool(result.success),calibration_validation=self.validation,
            physical_scope=self.value['metadata']['physical_scope'],new_scene_camera_verified=False)
