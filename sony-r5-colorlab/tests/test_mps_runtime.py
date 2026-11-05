"""真实MPS与独立CPU数值定义的交叉验证，不允许设备不可用时冒报成功。"""
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'R5ColorLab/web'), str(ROOT/'R5ColorLab/scripts'), str(ROOT/'R5ColorLab/tests')]
import gpu_runtime
import test_gpu_stages as stage_fixtures


@pytest.fixture(scope='module', autouse=True)
def require_real_mps():
    assert torch.backends.mps.is_available(), '本套验收必须在真实MPS上运行'
    assert os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK', '0') == '0'
    torch.manual_seed(20261103)
    torch.set_num_threads(8)


def record(name, value):
    folder = os.environ.get('R5_MPS_EVIDENCE')
    if folder:
        path = Path(folder); path.mkdir(parents=True, exist_ok=True)
        (path/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def test_launcher_requests_mps_by_default_and_cpu_is_explicit(monkeypatch):
    path = ROOT/'R5ColorLab/launcher.py'
    spec = importlib.util.spec_from_file_location('mps_launcher_contract', path)
    launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)
    monkeypatch.delenv('R5_GPU_TRAINING', raising=False)
    monkeypatch.setattr(sys, 'argv', [str(path), '--check'])
    with patch.object(launcher.subprocess, 'call', return_value=0) as child:
        assert launcher.main() == 0
        assert child.call_args.kwargs['env']['R5_GPU_TRAINING'] == '1'
    monkeypatch.setattr(sys, 'argv', [str(path), '--cpu', '--check'])
    with patch.object(launcher.subprocess, 'call', return_value=0) as child:
        assert launcher.main() == 0
        assert child.call_args.kwargs['env']['R5_GPU_TRAINING'] == '0'


@pytest.fixture(scope='module')
def stages():
    stage_fixtures.GPUStageTests.setUpClass()
    return stage_fixtures.GPUStageTests('test_all_specialized_losses_and_gradients_match_cpu')


@pytest.mark.parametrize('mode', ['tone', 'gray', 'chroma', 'joint'])
def test_real_mps_native_losses_and_directional_gradients(stages, mode):
    from gpu_optimizer import StageObjective
    f = stages
    block = slice(104, None) if mode == 'tone' else slice(0, 104) if mode == 'chroma' else slice(None)
    objective = StageObjective(f.smooth, f.gray, f.target*16383, f.gray_target, f.weights,
        f.start, f.bundle, .35, 30, mode=mode, fixed=f.vector, indices=block,
        reference=f.reference, device='mps')
    values = f.vector[block]
    actual, gradient = objective.value_gradient_stage(values)
    rows = f.reference_residual(mode, values, block)
    expected = float(rows@rows)/len(f.weights)
    direction = np.random.default_rng(18).normal(size=len(values)); direction /= np.linalg.norm(direction)
    epsilon = 1e-5
    hi = f.reference_residual(mode, values+direction*epsilon, block)
    lo = f.reference_residual(mode, values-direction*epsilon, block)
    derivative = float(hi@hi-lo@lo)/(2*epsilon*len(f.weights))
    record('stage-'+mode, dict(device=str(objective.gpu.device), CPU_loss=expected,
        MPS_loss=actual, loss_absolute_error=abs(actual-expected), CPU_directional_derivative=derivative,
        MPS_directional_derivative=float(gradient@direction)))
    assert objective.gpu.device == 'mps'
    assert np.isfinite(gradient).all()
    np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=1e-4)
    np.testing.assert_allclose(gradient@direction, derivative, atol=2e-6, rtol=.03)


def test_shared_c1_mps_forward_input_and_grid_gradients():
    from measured_response import get
    from grid_models import default_response
    from gpu_color import paired_tensor
    from gpu_tensor import TensorTools
    model = get(default_response()); tools = TensorTools(device='mps')
    rng = np.random.default_rng(20261103)
    samples = np.r_[rng.uniform(.08,.92,(512,3)), np.repeat(np.linspace(0,1,65)[:,None],3,axis=1)]
    grid = rng.integers(-16,17,(405,3)).astype(float)
    x = tools.tensor(samples).requires_grad_(True); g = tools.tensor(grid).requires_grad_(True)
    cotangent = rng.normal(size=samples.shape)
    out = paired_tensor(tools,x,g,default_response())
    expected = model.predict_cpu(samples,grid)
    actual = out.detach().cpu().numpy()
    np.testing.assert_allclose(actual,expected,atol=3e-6,rtol=0)
    (out*tools.tensor(cotangent)).sum().div(len(samples)).backward()
    for kind, gradient in [('input',x.grad),('grid',g.grad)]:
        assert bool(torch.isfinite(gradient).all().cpu())
        direction=rng.normal(size=samples.shape if kind=='input' else grid.shape)
        if kind=='input': direction[(samples==0)|(samples==1)]=0
        direction/=np.linalg.norm(direction); eps=1e-5
        hi=model.predict_cpu(samples+eps*direction,grid) if kind=='input' else model.predict_cpu(samples,grid+eps*direction)
        lo=model.predict_cpu(samples-eps*direction,grid) if kind=='input' else model.predict_cpu(samples,grid-eps*direction)
        finite=float(((hi-lo)*cotangent).sum()/(2*eps*len(samples)))
        derivative=float((gradient*tools.tensor(direction)).sum().cpu())
        np.testing.assert_allclose(derivative,finite,atol=3e-6,rtol=.03)
    record('shared-c1',dict(device=str(out.device),samples=len(samples),maximum_error=float(np.max(np.abs(actual-expected))),input_and_grid_gradients_finite=True))


@pytest.mark.parametrize('version',['v4','v45'])
def test_complete_chart_native_integer_path_preserves_cpu(version):
    import baseline,v4_dataset,v45_dataset
    from edit_color_pipeline import RuntimeColor
    from compute_backend import render_native
    dataset=v4_dataset if version=='v4' else v45_dataset
    arrays,_=dataset.load(); inputs=arrays['input']
    model=RuntimeColor.from_capture(*baseline.resolve(dataset.DATASET_ID))
    expected=model.color_only(inputs)
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1'}):
        gpu_runtime.available.cache_clear()
        try:
            actual=render_native(model,inputs)
            backend=gpu_runtime.policy()['native_integer_backend']
        finally: gpu_runtime.available.cache_clear()
    mismatch=int(np.count_nonzero(actual!=expected))
    record('native-integer-'+version,dict(backend=backend,samples=len(inputs),shape=list(inputs.shape),mismatched_channels=mismatch,
        maximum_error=int(np.max(np.abs(actual.astype(int)-expected.astype(int))))))
    np.testing.assert_array_equal(actual,expected)


def test_explicit_cpu_mode_does_not_run_mps_initializer():
    import apple_gpu
    with patch.dict(os.environ, {'R5_GPU_TRAINING':'0'}):
        gpu_runtime.available.cache_clear()
        with patch.object(apple_gpu, 'SmoothGPU', side_effect=AssertionError('CPU模式不能创建GPU初始化器')):
            result, audit = apple_gpu.initialize(None, None, None, None, None, None, steps=1)
        assert result is None and audit['enabled'] is False
        gpu_runtime.available.cache_clear()


def test_real_stage_solver_keeps_cpu_acceptance_independent(stages, tmp_path):
    from scipy.optimize import least_squares
    from gpu_optimizer import StageObjective
    from training_progress import TrainingProgress
    f=stages;block=slice(0,104);values=f.vector[block];reference_modes=[]
    def residual(x):
        reference_modes.append(gpu_runtime.available())
        return f.reference_residual('chroma',x,block)
    def factory():
        return StageObjective(f.smooth,f.gray,f.target*16383,f.gray_target,f.weights,
            f.start,f.bundle,.35,30,mode='chroma',fixed=f.vector,indices=block,
            reference=f.reference,device='mps')
    progress=TrainingProgress(tmp_path/'progress.json')
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1','R5_GPU_STRICT':'1'}):
        gpu_runtime.available.cache_clear()
        try:
            result=progress.solve(least_squares,'真实MPS优化',residual,values,
                bounds=(values-.1,values+.1),max_nfev=20,gpu_objective=factory)
        finally: gpu_runtime.available.cache_clear()
    assert result.backend=='Apple Metal/MPS'
    assert reference_modes and not any(reference_modes), 'CPU验收不能再次分派到GPU'
    assert result.cpu_objective_after <= result.cpu_objective_before
    assert result.nfev<=20
    record('actual-solver',dict(backend=result.backend,evaluations=result.nfev,
        CPU_objective_before=result.cpu_objective_before,CPU_objective_after=result.cpu_objective_after,
        CPU_acceptance_independent=not any(reference_modes)))


def test_cpu_reference_is_nested_and_does_not_disable_other_threads():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    barrier=threading.Barrier(2,timeout=5)
    def reference_worker():
        with gpu_runtime.cpu_reference():
            assert not gpu_runtime.available()
            with gpu_runtime.cpu_reference(): assert not gpu_runtime.available()
            barrier.wait(); barrier.wait()
        return gpu_runtime.available()
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1'}), ThreadPoolExecutor(1) as pool:
        future=pool.submit(reference_worker)
        barrier.wait();assert gpu_runtime.available();barrier.wait()
        assert future.result()


def test_failed_gpu_stage_has_explicit_fallback_and_strict_stop(tmp_path):
    from scipy.optimize import least_squares
    from training_progress import TrainingProgress
    def unavailable(): raise ValueError('故意触发数值门禁')
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1','R5_GPU_STRICT':'0'}):
        progress=TrainingProgress(tmp_path/'fallback.json')
        result=progress.solve(least_squares,'fallback',lambda x:x-2,[0.],max_nfev=8,gpu_objective=unavailable)
        np.testing.assert_allclose(result.x,[2.],atol=1e-9)
        assert progress.convergence[0]['backend']=='GPU fallback'
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1','R5_GPU_STRICT':'1'}):
        progress=TrainingProgress(tmp_path/'strict.json')
        with pytest.raises(RuntimeError,match='严格模式'):
            progress.solve(least_squares,'strict',lambda x:x-2,[0.],max_nfev=8,gpu_objective=unavailable)


def test_default_shared_grid_mps_fit_is_consistent_and_exportable():
    from measured_response import get
    from grid_models import default_response
    from gpu_grid_refine import refine
    from continuity_grid import constrain
    from output_continuity import ProbeBank
    identity=default_response(); model=get(identity);rng=np.random.default_rng(81)
    x=rng.uniform(.12,.88,(384,3)); target_grid=np.tile([4,-3,2],(405,1))
    target=model.predict_cpu(x,target_grid); weights=np.ones(len(x))
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'0'}): cpu_grid,cpu_audit=model.fit(x,target,weights,.001)
    with patch.dict(os.environ,{'R5_GPU_TRAINING':'1'}):
        mps_grid,mps_audit=model.fit(x,target,weights,.001)
        refined,refinement=refine(mps_grid,x,target,weights,weights,1,.35,identity,None,30)
        bank=ProbeBank()
        final,continuity=constrain(refined,x,target,weights,identity,30,(bank,bank.rgb,30),evaluations=2,device='mps')
    cpu_prediction=model.predict_cpu(x,cpu_grid);mps_prediction=model.predict_cpu(x,final)
    baseline=float(np.mean((x-target)**2));cpu_error=float(np.mean((cpu_prediction-target)**2));mps_error=float(np.mean((mps_prediction-target)**2))
    difference=float(np.sqrt(np.mean((cpu_prediction-mps_prediction)**2)))
    assert mps_audit['backend']=='Apple Metal/MPS'
    assert refinement['cpu_final_objective_check'] and refinement['after']<=refinement['before']
    assert continuity['after']<=continuity['before']
    assert cpu_error<baseline and mps_error<baseline
    assert difference<1/255, '两种求解器的输出差异需小于一个8位码值的均方根'
    import core
    e=core.presets()[0][0]; e.update(number=24,short_name='TEST24',full_name='GPU容量测试')
    e['grid_5x9x9']['coefficients']=final.T.reshape(3,5,9,9).astype(int).tolist()
    binary=core.compiler.pack(core.config([e]))
    assert binary[:8]==b'R5CUST5\0' and core.compiler.unpack(binary)['entries'][0]==e
    record('shared-grid-fit',dict(backend=mps_audit['backend'],baseline_MSE=baseline,CPU_MSE=cpu_error,
        MPS_MSE=mps_error,CPU_MPS_prediction_RMSE=difference,MPS_solver=mps_audit,
        integer_refinement=refinement,continuity=continuity,export_version=5,export_slot=24,
        fitted_parameter_equality_required=False))
