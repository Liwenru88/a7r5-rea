"""神经教师、完整原生参数联合求解与自适应舍入的同任务闭环。"""
import copy
import time
from pathlib import Path

import numpy as np

from joint_fit import JointObjective, native_basis, solve, delta_e_squared

POLICY = 'teacher-native-rounding/1'
SOURCES = ('teacher_joint.py', 'neural_teacher.py', 'native_rounding.py', 'joint_fit.py',
           'apple_gpu.py', 'integer_grid.py')


def fingerprint():
    import core
    return {name: core.sha(Path(__file__).with_name(name).read_bytes()) for name in SOURCES}


def failures(metrics, baseline, best_color):
    from integer_grid import selection_failures
    rejected = selection_failures(metrics, baseline, best_color)
    if metrics['delta_e00_p95'] > baseline['delta_e00_p95'] + 1e-10:
        rejected.append('delta_e00_p95')
    return rejected


class StudentObjective(JointObjective):
    def student_loss(self, vector, table, teacher, guard_scale):
        from gpu_color import paired_tensor
        native = (self.gpu.render(vector)/16383 + self.offset).clamp(0, 1)
        loss = self.loss(native, table, vector, guard_scale)
        rgb = paired_tensor(self.tools, native[:self.ntrain], table, self.response)
        if teacher is not None:
            loss = loss + .15 * (rgb-teacher).square().mean()
        # 真实训练目标的尾部损失独立约束，不追随教师的局部错误。
        de = delta_e_squared(self.tools, self.tools.lab(rgb), self.target_lab)
        tail = self.torch.topk(de, max(1, int(.05*self.ntrain))).values.mean()
        return loss + self.perceptual * .000005 * tail


def refine(config, grid, context, inputs, target, train, weights, eligible, gray, validation,
           response, bank, probe_base, bin_base, strength, perceptual, smoothing, progress=None,
           *, seconds=180, teacher_steps=2000, guard_steps=1000, evaluations=240,
           rounding_steps=300):
    import core
    from compute_backend import render_native
    from edit_parameter_context import ParameterContext
    from fit_anchor_native import SmoothNative, vector_for
    from fit_bin_joint import blend_entries, grid_from, projected
    from gpu_runtime import available, cpu_reference
    from integer_grid import candidate_metrics, polish_grid, repair_grid
    from measured_response import get
    from native_rounding import RoundedGPU, Rounding
    import neural_teacher
    from patch_sampling import center_mean

    if not available():
        raise RuntimeError('神经教师联合拟合需要Metal/MPS')
    if (not np.isfinite(seconds) or seconds <= 0 or teacher_steps < 1 or guard_steps < 0
            or evaluations < 1 or rounding_steps < 1):
        raise ValueError('训练步数与预算必须有效')
    train = np.asarray(train)
    if (train.ndim != 1 or train.dtype.kind not in 'iu' or len(train) != len(np.unique(train))
            or np.any(train < 0) or np.any(train >= len(inputs)) or not len(train)
            or gray.dtype != bool or validation.dtype != bool
            or gray.shape != (len(inputs),) or validation.shape != gray.shape
            or not gray.any() or not validation.any() or validation[train].any()
            or not np.isin(np.flatnonzero(gray), train).all()
            or not np.isfinite(inputs).all() or not np.isfinite(target).all()):
        raise ValueError('训练、灰阶与验证集不一致或含非有限值')
    selected_config = core.compiler.unpack(core.compiler.pack(config))
    seed, = selected_config['entries']
    if any(any(row) for row in seed['cc1_delta'][1:]) or any(m != seed['block13'][0] for m in seed['block13'][1:]):
        raise ValueError('神经联合拟合要求共享照明端点')
    seed['grid_5x9x9'] = dict(coefficients=grid.T.reshape(3, 5, 9, 9).tolist())
    if not np.array_equal(inputs, np.broadcast_to(inputs[:,4:5], inputs.shape)):
        raise ValueError('连续颜色教师首版要求平坦色卡输入')
    started = time.perf_counter()
    deadline = started + seconds
    model = get(response)
    measure = candidate_metrics(target[gray], target[validation], response, bank,
                                 strength, perceptual, include_p95=True)
    baseline = measure(grid, bin_base[gray], bin_base[validation], probe_base)
    teacher, teacher_audit = neural_teacher.fit(inputs[:,4]/16383, target, train, gray, validation,
        bank, bank.inputs(context.base)[:,4]/16383, model.predict_cpu(probe_base, grid),
        model.predict_cpu(bin_base[gray], grid), baseline, strength, perceptual, progress,
        steps=teacher_steps, guard_steps=guard_steps)
    if not teacher_audit['accepted']:
        teacher = None
    audit = dict(policy=POLICY, backend='Apple Metal/MPS', full_batch=True,
        sources=fingerprint(), teacher=teacher_audit, stages=[], candidates=[],
        validation_before=baseline, time_budget_seconds=seconds,
        validation_used_for_gradient=False, test_used_for_selection=False,
        initialization='frozen accepted BIN', training_samples=len(train))
    warm = context.build(**core.slot_native_parameters(context, seed))
    initial = vector_for(ParameterContext(warm))
    smooth = SmoothNative(context, np.concatenate((inputs[train], bank.inputs(warm))))
    exact = np.concatenate((bin_base[train], probe_base))
    objective = StudentObjective(smooth, initial, exact, target[train], np.ones(len(train)),
        np.flatnonzero(gray[train]), bank, grid, response, perceptual, smoothing, strength)
    tools, torch = objective.tools, objective.torch
    teacher = None if teacher is None else teacher.to(tools.device)
    best_entry, best_metrics = copy.deepcopy(seed), baseline
    candidate_inputs = np.concatenate((inputs[gray], inputs[validation], bank.inputs(context.base)))
    ngray, nvalid = int(gray.sum()), int(validation.sum())
    repairable = []

    def consider(entry, label):
        nonlocal best_entry, best_metrics
        # 量化后打包/回读和CPU原生计算是唯一接受边界。
        proposed = core.compiler.config([entry], core.compiler.format_version(config))
        blob = core.compiler.pack(proposed)
        entry, = core.compiler.unpack(blob)['entries']
        native = context.build(**core.slot_native_parameters(context, entry))
        with cpu_reference():
            base = center_mean(render_native(native, candidate_inputs))/16383
        gray_base, valid_base, probes = np.split(base, (ngray, ngray+nvalid))
        metrics = measure(grid_from(entry), gray_base, valid_base, probes)
        rejected = failures(metrics, baseline, best_metrics['color_score'])
        audit['candidates'].append(dict(label=label, bin_sha256=core.sha(blob),
                                       metrics=metrics, rejected_by=rejected))
        if not rejected:
            best_entry, best_metrics = entry, metrics
        if metrics['rgb_rmse'] < baseline['rgb_rmse'] and metrics['delta_e00_mean'] < baseline['delta_e00_mean']:
            repairable.append((len(rejected), entry, (gray_base, valid_base, probes)))

    current = np.r_[np.zeros(121), grid.ravel()/32]
    continuous_vector = initial
    continuous_table = grid.astype(float)
    # 单一学生轨迹逐渐释放Gamma分辨率；不重复训练两个原生模型。
    for controls, scale in ((17, 1.), (33, 10.), (128, 30.)):
        if time.perf_counter() >= deadline-25:
            break
        objective.initial = tools.tensor(continuous_vector)
        objective.basis = tools.tensor(native_basis(smooth, controls))
        n = objective.basis.shape[1]
        current = np.r_[np.zeros(n), continuous_table.ravel()/32]

        def loss(values):
            return objective.student_loss(objective.vector(values[:n]),
                values[n:].reshape(405,3)*32, teacher, scale)

        values, stage = solve((tools, loss), current, [(-2.,2.)]*n+[(-2.,63/32)]*1215,
            min(deadline-20, time.perf_counter()+seconds/5), evaluations, progress,
            f'教师辅助：{controls}点Gamma、CC1、矩阵与网格联合求解')
        continuous_vector = objective.vector(tools.tensor(values[:n])).detach().cpu().numpy().astype(float)
        continuous_table = values[n:].reshape(405,3)*32
        stage.update(gamma_controls=controls, native_controls=n)
        audit['stages'].append(stage)
        nearest = projected(seed, smooth.params(continuous_vector))
        nearest['grid_5x9x9'] = dict(coefficients=np.clip(np.rint(continuous_table),-64,63).astype(int).T.reshape(3,5,9,9).tolist())
        for fraction in (1., .25, .0625, .015625):
            consider(blend_entries(seed, nearest, fraction), f'continuous-{controls}-{fraction}')
        grid_only=copy.deepcopy(seed)
        grid_only['grid_5x9x9']=copy.deepcopy(nearest['grid_5x9x9'])
        consider(grid_only,f'continuous-grid-only-{controls}')

    # 所有字段的软舍入共享一个输出损失，最终硬化后再经真实整数模型验收。
    rounded_gpu = RoundedGPU(smooth, compact_flat=True)
    rounding = Rounding(tools, tools.tensor(continuous_vector),
        rounded_gpu.gamma(tools.tensor(continuous_vector)), tools.tensor(continuous_table))
    objective.gpu = rounded_gpu
    logits = rounding.initial.clone().requires_grad_(True)
    optimizer = torch.optim.Adam([logits], lr=.03)
    best_round_loss = float('inf')
    for step in range(rounding_steps):
        if time.perf_counter() >= deadline-8:
            break
        optimizer.zero_grad(set_to_none=True)
        vector, gamma, table, soft = rounding.values(logits)
        rounded_gpu.override_gamma = gamma
        fraction = step/max(rounding_steps-1,1)
        loss = objective.student_loss(vector, table, teacher, 30.)
        loss = loss + .00001*rounding.penalty(soft, fraction)
        if not bool(torch.isfinite(loss)):
            raise ValueError('自适应舍入产生非有限损失')
        loss.backward()
        optimizer.step()
        if step == 0 or (step+1)%100 == 0 or step+1 == rounding_steps:
            score = float(loss.detach().cpu())
            best_round_loss = min(best_round_loss, score)
            if progress:
                progress(stage='联合量化：CC1、矩阵、Gamma与网格自适应舍入', state='running',
                    loss_sample=('rounding-Adam',step+1,score,best_round_loss))
            with torch.no_grad():
                vector, gamma, table, _ = rounding.values(logits, hard=True)
                vector = vector.cpu().numpy().astype(float)
                entry = projected(seed, smooth.params(vector))
                entry['gamma_native_129'] = np.rint(gamma.cpu().numpy()*8).astype(int).tolist()+[seed['gamma_native_129'][-1]]
                entry['grid_5x9x9'] = dict(coefficients=table.cpu().numpy().astype(int).T.reshape(3,5,9,9).tolist())
            for amount in (1., .25, .0625):
                consider(blend_entries(seed,entry,amount),f'adaptive-rounding-{step+1}-{amount}')
            grid_only=copy.deepcopy(seed)
            grid_only['grid_5x9x9']=copy.deepcopy(entry['grid_5x9x9'])
            consider(grid_only,f'rounding-grid-only-{step+1}')
    rounded_gpu.override_gamma = None
    # 从最近可行整数配方收尾，教师只排序提案；接受仍使用真实目标与固定保护。
    native = context.build(**core.slot_native_parameters(context, best_entry))
    with cpu_reference():
        base = center_mean(render_native(native, inputs[train]))/16383
        validation_base = center_mean(render_native(native, inputs[validation]))/16383
        probes = center_mean(render_native(native, bank.inputs(native)))/16383
    audit['integer_rounds']=[]
    for sweep in range(8):
        if time.perf_counter()>=deadline:
            break
        previous_table=grid_from(best_entry).copy()
        proposed, moves = polish_grid(grid_from(best_entry), base, target[train], gray[train],
            probes, response, bank, strength, baseline, proposal_target=None if teacher is None else teacher.cpu().numpy(),
            proposal_table=np.clip(np.rint(continuous_table),-64,63).astype(np.int8),
            deadline=deadline,step_sizes=(1,2,4),validation_data=(validation_base,target[validation]),
            protect_color_p95=True)
        if moves:
            entry = copy.deepcopy(best_entry)
            entry['grid_5x9x9'] = dict(coefficients=proposed.T.reshape(3,5,9,9).tolist())
            consider(entry,f'integer-polish-{sweep+1}')
        applied=int(np.count_nonzero(grid_from(best_entry)!=previous_table))
        audit['integer_rounds'].append(dict(sweep=sweep+1,moves=moves,applied_coefficients=applied))
        if progress:
            progress(stage='最终整数网格：真实目标与颜色P95逐步验收',state='round_done',
                integer_round=dict(sweep=sweep+1,proposed_moves=moves,applied_moves=applied,
                    metrics=best_metrics,gray_passed=True,saturation_passed=True,
                    rejected_candidates=int(bool(moves) and not applied)))
        if not applied:
            break
    for _, entry, (gray_base, _, probes) in sorted(repairable,key=lambda row:row[0])[:2]:
        if time.perf_counter() >= deadline:
            break
        table, moves = repair_grid(grid_from(entry),gray_base,target[gray],probes,response,bank,
                                   strength,baseline,deadline=deadline)
        if moves:
            entry=copy.deepcopy(entry)
            entry['grid_5x9x9']=dict(coefficients=table.T.reshape(3,5,9,9).tolist())
            consider(entry,'guard-repair')
    # 软舍入不能覆盖原生内部整数表的离散效应。用当前可行BIN上的GPU梯度
    # 排序小步提案，逐项交给真实CPU整数渲染与完整保护验收。
    warm=context.build(**core.slot_native_parameters(context,best_entry))
    native_vector=vector_for(ParameterContext(warm))
    with cpu_reference():
        exact=np.concatenate((center_mean(render_native(warm,inputs[train]))/16383,
                              center_mean(render_native(warm,bank.inputs(warm)))/16383))
    smooth=SmoothNative(context,np.concatenate((inputs[train],bank.inputs(warm))))
    local=StudentObjective(smooth,native_vector,exact,target[train],np.ones(len(train)),
        np.flatnonzero(gray[train]),bank,grid_from(best_entry),response,perceptual,smoothing,strength)
    local.gpu=RoundedGPU(smooth,compact_flat=True)
    v=tools.tensor(native_vector).requires_grad_(True)
    gamma=local.gpu.gamma(v).detach().requires_grad_(True)
    local.gpu.override_gamma=gamma
    loss=local.student_loss(v,tools.tensor(grid_from(best_entry)),teacher,30.)
    vg,gg=torch.autograd.grad(loss,(v,gamma))
    gradient=np.r_[vg[:8].detach().cpu().numpy()*np.r_[np.full(4,1/256),np.full(4,1/64)],
        vg[8:104].detach().cpu().numpy()/1024,gg[1:].detach().cpu().numpy()/8]
    audit['native_integer_search']=dict(proposals=0,accepted=0,ranking='teacher-assisted GPU gradient; CPU integer acceptance')
    for parameter in np.argsort(-np.abs(gradient),kind='stable')[:48]:
        if time.perf_counter()>=deadline:
            break
        direction=-1 if gradient[parameter]>0 else 1
        if parameter<8:
            index=(3,0,1,2,7,4,5,6)[parameter]
            steps=(4,)
        elif parameter<104:
            component,sector=divmod(int(parameter)-8,16)
            steps=(1,2)
        else:
            index=int(parameter)-104+1
            steps=(1,8)
        for step in (size*sign for size in steps for sign in (direction,-direction)):
            if time.perf_counter()>=deadline:
                break
            entry=copy.deepcopy(best_entry)
            if parameter<8:
                value=entry['cc1_delta'][0][index]+step
                if not (-1024 if index<4 else 0)<=value<=1023:
                    continue
                entry['cc1_delta'][0][index]=value
            elif parameter<104:
                value=entry['block13'][0][sector][component]+step
                if not -8192<=value<=8191:
                    continue
                for matrix in entry['block13']:
                    matrix[sector][component]=value
            else:
                curve=entry['gamma_native_129']
                value=curve[index]+step
                if not curve[index-1]<=value<=curve[index+1]:
                    continue
                curve[index]=value
            previous=best_entry
            consider(entry,f'native-integer-{parameter}-{step}')
            audit['native_integer_search']['proposals']+=1
            if best_entry is not previous:
                audit['native_integer_search']['accepted']+=1
                break
    local.gpu.override_gamma=None
    audit.update(validation_after=best_metrics,accepted=best_entry != seed,
                 seconds=time.perf_counter()-started)
    selected_config['entries']=[best_entry]
    selected=core.compiler.unpack(core.compiler.pack(selected_config))
    return selected if audit['accepted'] else None, grid_from(best_entry), audit
