"""合法整数配方的分块联合搜索；浮点梯度仅生成方向，不作为配方接受。"""
import copy
from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np

from native_scoring import COLOR, PROTECTED, RecipeScorer, adoption_failures

POLICY = 'native-integer-blocks/1'
SOURCES = ('integer_blocks.py', 'native_scoring.py', 'integer_grid.py', 'native_rounding.py',
           'joint_fit.py', 'apple_gpu.py', 'gpu_color.py', 'output_continuity.py',
           'adaptive_gpu.py','gpu_tensor.py','fit_anchor_native.py','core.py','patch_sampling.py',
           'measured_response.py','paired_response.py','paired_coordinates.py','perceptual.py')


def fingerprint():
    import core
    root = Path(__file__).resolve().parents[1]
    paths = [f'web/{name}' for name in SOURCES]+[f'scripts/{name}.py' for name in
        ('edit_parameter_context','edit_color_pipeline','edit_native_model','native_gamma','residual_grid')]
    return {name: core.sha((root/name).read_bytes()) for name in paths}


def grid_entry(entry, table):
    result = copy.deepcopy(entry)
    array = np.asarray(table)
    if array.shape != (405, 3) or not np.isfinite(array).all() or np.any(array != np.rint(array)):
        raise ValueError('分块搜索只接受405×3整数网格')
    if np.any(array < -64) or np.any(array > 63):
        raise ValueError('网格越界')
    result['grid_5x9x9'] = dict(coefficients=array.T.reshape(3,5,9,9).astype(int).tolist())
    return result


def matrix_move(code, delta):
    """按有效刻度走动：负值最低一位不参与解码，不能重复搜同一物理系数。"""
    canonical = code & ~1 if code < 0 else code
    # 负半轴相邻有效值的编码跨度为2，正半轴为1；跨零逐格行走。
    for _ in range(abs(int(delta))):
        canonical += (1 if canonical >= 0 else 2) if delta > 0 else (-1 if canonical > 0 else -2)
    return canonical


def native_moves(entry, gradient, mesh, count=12):
    """Gamma局部段、相邻色相与CC1块；Gamma固定端点且允许平台。"""
    ordered = np.argsort(-np.abs(gradient), kind='stable')
    ordered = ordered[gradient[ordered] != 0]
    # 给各原生参数族留出搜索机会，避免一个量纲占满全部预算。
    buckets = [ordered[ordered < 8],ordered[(ordered >= 8)&(ordered < 104)],ordered[ordered >= 104]]
    priorities = [int(row[i]) for i in range(count) for row in buckets if len(row) > i][:count]
    for parameter in priorities:
        direction = -1 if gradient[parameter] > 0 else 1
        if not gradient[parameter]:
            continue
        for sign in (direction, -direction):
            result = copy.deepcopy(entry)
            if parameter < 8:
                index = (3,0,1,2,7,4,5,6)[parameter]
                value = result['cc1_delta'][0][index] + sign*4*mesh
                if not (-1024 if index < 4 else 0) <= value <= 1023:
                    continue
                result['cc1_delta'][0][index] = value
                kind = 'cc1'
            elif parameter < 104:
                component, sector = divmod(int(parameter)-8, 16)
                value = matrix_move(result['block13'][0][sector][component], sign*mesh)
                if not -8192 <= value <= 8191:
                    continue
                for matrix in result['block13']:
                    matrix[sector][component] = value
                kind = 'hue'
            else:
                index = int(parameter)-104+1
                values = np.array(result['gamma_native_129'])
                values[index] += sign*4*mesh
                if np.any(np.diff(values) < 0):
                    continue
                result['gamma_native_129'] = values.tolist()
                kind = 'gamma'
            yield result, f'{kind}-{parameter}-{sign*mesh}'
            # 相邻段一起移动，给局部连续性留下补偿空间。
            block = copy.deepcopy(result)
            if kind == 'hue':
                neighbor = (sector+1) % 16
                value = matrix_move(entry['block13'][0][neighbor][component], sign*mesh)
                if not -8192 <= value <= 8191:
                    continue
                for matrix in block['block13']:
                    matrix[neighbor][component] = value
            elif kind == 'gamma':
                curve = np.array(block['gamma_native_129'])
                for at in (index-1, index+1):
                    if 0 < at < 128:
                        curve[at] += sign*2*mesh
                if np.any(np.diff(curve) < 0):
                    continue
                block['gamma_native_129'] = curve.tolist()
            else:
                continue
            yield block, f'{kind}-segment-{parameter}-{sign*mesh}'


def violation(metrics, baseline):
    if any(not np.isfinite(metrics[key]) for key in (*COLOR, *PROTECTED)):
        return float('inf')
    # 探索门槛以固定基准为参照；它不会变成导出门槛。
    values = [(metrics[key]-baseline[key])/max(abs(baseline[key]), 100. if key.endswith('_over') else 1.)
              for key in PROTECTED]
    values.extend((metrics[key]-baseline[key])/max(abs(baseline[key]), 1.) for key in COLOR)
    return max(0., max(values))


class CandidatePool:
    """可行档案与有限越界探索池分开；最优可行配方始终单独固定保存。"""
    def __init__(self, baseline, capacity=6, barrier=.05):
        self.baseline = self.best = baseline
        self.feasible, self.exploratory = [baseline], []
        self.capacity, self.barrier = capacity, barrier

    def objectives(self, recipe, exploratory=False):
        keys = ('rgb_rmse','delta_e00_mean','delta_e00_p95','delta_e00_tail_mean')
        vector = [recipe.metrics[key]/max(abs(self.baseline.metrics[key]),1.) for key in keys]
        if exploratory:
            vector.append(violation(recipe.metrics,self.baseline.metrics)*10)
        return np.array(vector)

    def admit(self, recipe):
        if recipe.sha256 == self.baseline.sha256:
            return False
        if any(recipe.sha256 == row.sha256 for row in self.feasible+self.exploratory):
            return False
        failures = adoption_failures(recipe.metrics, self.baseline.metrics)
        feasible = not failures
        if violation(recipe.metrics, self.baseline.metrics) > self.barrier:
            return False
        if feasible and (self.best is self.baseline or self.rank(recipe) < self.rank(self.best)):
            self.best = recipe
        pool = self.feasible if feasible else self.exploratory
        vector = self.objectives(recipe, not feasible)
        def dominates(left,right):
            a,b = self.objectives(left,not feasible),self.objectives(right,not feasible)
            if np.all(a <= b) and np.any(a < b):
                return True
            # 8位指标相同的平台上，才用取整前的精度选择下一步搜索方向。
            if np.array_equal(a,b):
                return (left.metrics['float_rgb_rmse'] < right.metrics['float_rgb_rmse']-1e-10)
            return False
        if any(dominates(row,recipe) for row in pool):
            return False
        pool[:] = [row for row in pool if not dominates(recipe,row)]
        pool.append(recipe)
        # 保留不同颜色折中。容量有限时用四个目标的极端点及总分补齐。
        if len(pool) > self.capacity:
            values = np.stack([self.objectives(row,not feasible) for row in pool])
            keep = list(dict.fromkeys(np.argmin(values,axis=0).tolist()))
            remaining = sorted(range(len(pool)),key=lambda i:(values[i].sum(),pool[i].metrics['float_rgb_rmse']))
            keep += [i for i in remaining if i not in keep]
            pool[:] = [pool[i] for i in keep[:self.capacity]]
        return True

    def rank(self, recipe):
        # 各均值各占同等相对权重，颜色尾部只做次级排序。
        m, b = recipe.metrics, self.baseline.metrics
        return (m['rgb_rmse']/max(b['rgb_rmse'],1e-12) + m['delta_e00_mean']/max(b['delta_e00_mean'],1e-12),
                m['delta_e00_tail_mean'],m['float_rgb_rmse'])


@dataclass
class Mesh:
    size: int = 2
    stagnant: int = 0

    def update(self, improved):
        self.stagnant = 0 if improved else self.stagnant+1
        if improved:
            self.size = min(4, self.size*2)
        elif self.size > 1:
            self.size //= 2


class Directions:
    """MPS整批训练方向；用整数参考输出对齐梯度近似，验证集不参与反传。"""
    def __init__(self, scorer, response, strength, perceptual, baseline, *, device='mps'):
        from adaptive_gpu import FitGuard
        from fit_anchor_native import SmoothNative
        from gpu_tensor import TensorTools
        from native_rounding import RoundedGPU
        from output_continuity import TensorPenalty

        self.scorer, self.perceptual, self.response = scorer, perceptual, response
        self.baseline_metrics = baseline.metrics
        self.tools = TensorTools(device)
        self.torch = self.tools.torch
        self.indices = np.r_[np.arange(scorer.ntrain),
                             np.arange(scorer.ntrain+scorer.nvalid,len(scorer.inputs))]
        from edit_parameter_context import ParameterContext
        context=ParameterContext(scorer.context.base,native_gamma=True)
        smooth = SmoothNative(context,scorer.inputs[self.indices])
        flat = np.array_equal(smooth.x,np.broadcast_to(smooth.x[:,4:5],smooth.x.shape))
        self.gpu = RoundedGPU(smooth,device=device,compact_flat=flat)
        self.target = self.tools.tensor(scorer.train_target)
        self.target_lab = self.tools.lab(self.target)
        self.gray = self.tools.tensor(np.flatnonzero(scorer.gray_train),True)
        _, base = scorer.native(baseline.entry)
        from fit_bin_joint import grid_from
        rgb = scorer.response.predict_cpu(base[self.indices],grid_from(baseline.entry))
        self.guard = FitGuard(self.tools,scorer.bank,rgb[scorer.ntrain:],
                             rgb[:scorer.ntrain][scorer.gray_train],scorer.train_target[scorer.gray_train])
        self.continuity = TensorPenalty(scorer.bank,self.tools,strength)
        self.continuity_limit = self.continuity.loss(self.tools.tensor(rgb[scorer.ntrain:])).detach()

    def gradient(self, recipe):
        from edit_parameter_context import ParameterContext
        from fit_anchor_native import vector_for
        from fit_bin_joint import grid_from
        from gpu_color import paired_tensor
        from joint_fit import delta_e_squared

        model, base = self.scorer.native(recipe.entry)
        tools, t = self.tools,self.torch
        vector = tools.tensor(vector_for(ParameterContext(model))).requires_grad_(True)
        gamma = tools.tensor(np.array(recipe.entry['gamma_native_129'])/8).requires_grad_(True)
        table = tools.tensor(grid_from(recipe.entry)).requires_grad_(True)
        self.gpu.override_gamma = gamma
        approximate = self.gpu.render(vector)/16383
        native = approximate + (tools.tensor(base[self.indices])-approximate).detach()
        predicted = paired_tensor(tools,native,table,self.response)
        color = predicted[:self.scorer.ntrain]
        delta = delta_e_squared(tools,tools.lab(color),self.target_lab)
        loss = (color-self.target).square().mean() + self.perceptual*.0001*delta.mean()
        loss = loss + self.perceptual*.00001*t.topk(delta,max(1,len(color)//20)).values.mean()
        probes = predicted[self.scorer.ntrain:]
        # CPU整数指标仍在边界内时，不能因float32的微差激活大尺度惩罚梯度。
        if any(recipe.metrics[key] > self.baseline_metrics[key]+1e-10 for key in PROTECTED):
            loss = loss + 30*self.guard.loss(color[self.gray],probes)
        if recipe.metrics['continuity_cost'] > self.baseline_metrics['continuity_cost']+1e-8:
            loss = loss + 30*(self.continuity.loss(probes)-self.continuity_limit).clamp(min=0)
        vg, gg, gridg = t.autograd.grad(loss,(vector,gamma,table))
        nativeg = np.r_[vg[:8].detach().cpu().numpy()*np.r_[np.full(4,1/256),np.full(4,1/64)],
            vg[8:104].detach().cpu().numpy()/1024,gg[1:-1].detach().cpu().numpy()/8]
        gradient = gridg.detach().cpu().numpy().astype(float)
        self.gpu.override_gamma = None
        if not np.isfinite(nativeg).all() or not np.isfinite(gradient).all():
            raise ValueError('分块方向产生非有限梯度')
        return nativeg,gradient,float(loss.detach().cpu())


def grid_moves(entry, gradient, mesh):
    from fit_bin_joint import grid_from
    table = grid_from(entry).astype(int)
    ranked = np.argsort(-np.abs(gradient).ravel(),kind='stable')
    for count in (1,4,12,48,192):
        active = ranked[:count]
        update = np.zeros(1215,int)
        update[active] = -np.sign(gradient.ravel()[active]).astype(int)*mesh
        yield grid_entry(entry,np.clip(table+update.reshape(405,3),-64,63)),f'grid-top-{count}'
    # 相邻节点与通道成块，避免单点改动在局部过渡上被立即阻断。
    seen = set()
    for parameter in ranked[:8]:
        node, channel = divmod(int(parameter),3)
        if node in seen:
            continue
        seen.add(node)
        for axis,stride in enumerate((81,9,1)):
            position = np.unravel_index(node,(5,9,9))
            neighbor = node+stride if position[axis] < (4,8,8)[axis] else node-stride
            result = table.copy()
            for at in (node,neighbor):
                result[at] -= np.sign(gradient[at]).astype(int)*mesh
            yield grid_entry(entry,np.clip(result,-64,63)),f'grid-neighbors-{node}-{axis}'


def refine(config, grid, context, inputs, target, train, weights, eligible, gray, validation,
           response, bank, probe_base, bin_base, strength, perceptual, smoothing, progress=None,
           *, seconds=180, max_rounds=24, extra_starts=()):
    import core
    from fit_bin_joint import grid_from, projected
    from gpu_runtime import available
    from integer_grid import polish_grid,repair_grid

    if not available():
        raise RuntimeError('整数分块联合求解需要可用的Metal/MPS')
    if not np.isfinite(seconds) or seconds <= 0 or type(max_rounds) is not int or max_rounds < 1:
        raise ValueError('整数求解预算必须有效')
    selected = core.compiler.unpack(core.compiler.pack(config))
    seed, = selected['entries']
    if any(any(row) for row in seed['cc1_delta'][1:]) or any(m != seed['block13'][0] for m in seed['block13'][1:]):
        raise ValueError('整数联合求解要求共享照明端点')
    if not np.array_equal(grid_from(seed),grid):
        raise ValueError('初始参数与网格不一致')
    started = time.perf_counter()
    deadline = started+seconds
    scorer = RecipeScorer(selected,context,inputs,target,train,gray,validation,response,bank,strength,perceptual)
    baseline = scorer.score(seed,'baseline')
    pool = CandidatePool(baseline)
    directions = Directions(scorer,response,strength,perceptual,baseline)
    audit = dict(policy=POLICY,sources=fingerprint(),backend='Apple Metal/MPS',
        native_integer_backend='CPU reference',full_batch=True,training_samples=len(train),
        validation_before=baseline.metrics,test_used_for_selection=False,validation_used_for_gradient=False,
        time_budget_seconds=seconds,candidates=[],rounds=[],starts=[],accepted=False)
    meshes, processed = {}, {}

    def consider(entry,label):
        recipe = scorer.score(entry,label)
        admitted = pool.admit(recipe)
        rejected = adoption_failures(recipe.metrics,baseline.metrics)
        audit['candidates'].append(dict(label=label,bin_sha256=recipe.sha256,metrics=recipe.metrics,
            training=recipe.training,rejected_by=rejected,violation=violation(recipe.metrics,baseline.metrics),
            pool_admitted=admitted))
        return recipe

    starts = [baseline]
    # 小幅扰动与原厂配方是真正不同的合法整数起点，共享同一整批数据和时间预算。
    ng, gg, _ = directions.gradient(baseline)
    perturb = next(native_moves(seed,ng,1,count=1),None)
    if perturb:
        starts.append(consider(perturb[0],'start-bounded-native'))
    factory = projected(seed,dict(cc1=context.cc1,matrix_payload=context.payload,gamma_y=context.gamma_y))
    starts.append(consider(factory,'start-factory'))
    for entry in extra_starts:
        entry = scorer.canonical(entry)[0]
        if entry['number'] != seed['number'] or entry['full_name'] != seed['full_name']:
            raise ValueError('额外起点必须属于同一槽位与目标')
        starts.append(consider(entry,'start-external-frozen'))
    for item in starts:
        audit['starts'].append(dict(label=item.label,sha256=item.sha256,
            violation=violation(item.metrics,baseline.metrics)))
    schedule = starts.copy()
    stop_reason = 'round_limit'
    best_loss = float('inf')
    for round_index in range(max_rounds):
        if time.perf_counter() >= deadline:
            stop_reason = 'time_budget'
            break
        available_parents = schedule + [pool.best] + sorted(pool.feasible,key=pool.rank) + pool.exploratory
        unique = {item.sha256:item for item in available_parents}
        active = [item for item in unique.values() if meshes.get(item.sha256,Mesh()).stagnant < 3]
        if not active:
            stop_reason = 'mesh_stagnation'
            break
        # 每个起点至少有机会；其后在最优可行配方和档案之间轮转。
        if schedule:
            parent = schedule.pop(0)
        else:
            parent = min(active,key=lambda row:(processed.get(row.sha256,0),pool.rank(row)))
        mesh = meshes.setdefault(parent.sha256,Mesh())
        used_mesh = mesh.size
        before = pool.best.sha256
        nativeg,gridg,loss = directions.gradient(parent)
        best_loss = min(best_loss,loss)
        if progress:
            progress(stage='纯整数分块联合求解',state='running',sweep=round_index+1,
                total_sweeps=max_rounds,gpu_backend='Apple Metal/MPS',
                loss_sample=('integer-block training direction',round_index+1,loss,best_loss))
        grid_trials = list(grid_moves(parent.entry,gridg,mesh.size))[:17]
        native_trials = list(native_moves(parent.entry,nativeg,mesh.size,count=8))[:24]
        # Gamma/相邻色相和网格必须可以原子提交；不要求中间步骤独自改善。
        joint_trials = []
        for native,label in native_trials[::3][:6]:
            for grid_candidate,grid_label in grid_trials[1:4:2]:
                joint_trials.append((grid_entry(native,grid_from(grid_candidate)),f'joint-{label}-{grid_label}'))
        # 全部原生块的同向小步作为一个候选，避免必须先单字段获准。
        positive = native_trials[::4][:3]
        if len(positive) > 1:
            merged = copy.deepcopy(parent.entry)
            for candidate,_ in positive:
                for key in ('gamma_native_129','cc1_delta','block13'):
                    original = np.array(parent.entry[key])
                    delta = np.array(candidate[key])-original
                    merged[key] = (np.array(merged[key])+delta).tolist()
            if np.all(np.diff(merged['gamma_native_129']) >= 0):
                joint_trials.append((merged,'joint-native-blocks'))
                joint_trials.append((grid_entry(merged,grid_from(grid_trials[2][0])),'joint-all-fields'))
        trial_count = 0
        for candidate,label in grid_trials+joint_trials+native_trials:
            if time.perf_counter() >= deadline:
                break
            consider(candidate,f'round-{round_index+1}-{label}')
            trial_count += 1
        # 在几个最好的探索原生点上重算网格方向，寻找原生改动的补偿，而不是只叠加旧梯度。
        if time.perf_counter() < deadline and pool.exploratory:
            candidates = sorted(pool.exploratory,key=lambda row:(processed.get('repair-'+row.sha256,0),
                                sum(pool.objectives(row,True))))
            candidate = candidates[0]
            processed['repair-'+candidate.sha256] = processed.get('repair-'+candidate.sha256,0)+1
            _,compensation,_ = directions.gradient(candidate)
            for compensated,label in list(grid_moves(candidate.entry,compensation,1))[:5]:
                if time.perf_counter() >= deadline:
                    break
                consider(compensated,f'compensate-{round_index+1}-{label}')
                trial_count += 1
            if (time.perf_counter() < deadline and all(candidate.metrics[key] < baseline.metrics[key]
                                                     for key in COLOR)):
                _,base = scorer.native(candidate.entry)
                gray_base = base[:scorer.ntrain][scorer.gray_positions]
                probes = base[scorer.ntrain+scorer.nvalid:]
                table,moves = repair_grid(grid_from(candidate.entry),gray_base,
                    scorer.train_target[scorer.gray_positions],probes,response,bank,strength,baseline.metrics,
                    deadline=min(deadline,time.perf_counter()+2))
                if moves:
                    consider(grid_entry(candidate.entry,table),f'repair-{round_index+1}')
        if round_index % 3 == 0 and time.perf_counter() < deadline:
            incumbent = pool.best
            _,base = scorer.native(incumbent.entry)
            train_base,valid_base,probes = np.split(base,(scorer.ntrain,scorer.ntrain+scorer.nvalid))
            table,moves = polish_grid(grid_from(incumbent.entry),train_base,scorer.train_target,
                scorer.gray_train,probes,response,bank,strength,baseline.metrics,
                deadline=min(deadline,time.perf_counter()+6),step_sizes=(1,2),
                validation_data=(valid_base,scorer.valid_target),protect_color_p95=True)
            if moves:
                consider(grid_entry(incumbent.entry,table),f'polish-{round_index+1}')
        improved = pool.best.sha256 != before
        mesh.update(improved)
        if improved:
            meshes.setdefault(pool.best.sha256,Mesh(size=mesh.size))
        processed[parent.sha256] = processed.get(parent.sha256,0)+1
        audit['rounds'].append(dict(round=round_index+1,parent=parent.sha256,mesh_used=used_mesh,mesh_next=mesh.size,
            trials=trial_count,improved=improved,feasible=len(pool.feasible),exploratory=len(pool.exploratory),
            metrics=pool.best.metrics,seconds=time.perf_counter()-started))
        if progress:
            progress(state='round_done',integer_round=dict(sweep=round_index+1,
                proposed_moves=trial_count,applied_moves=int(improved),metrics=pool.best.metrics,
                gray_passed=True,saturation_passed=True,rejected_candidates=sum(
                    bool(row['rejected_by']) for row in audit['candidates'][-trial_count:]) if trial_count else 0))
    # 再建独立评分器，绕过搜索缓存，验证最终打包回读的真实输出。
    final_scorer = RecipeScorer(selected,context,inputs,target,train,gray,validation,response,bank,strength,perceptual)
    final = final_scorer.score(pool.best.entry,'independent-final-bin')
    rejected = adoption_failures(final.metrics,baseline.metrics)
    accepted = final.sha256 != baseline.sha256 and not rejected
    winner = final if accepted else baseline
    audit.update(accepted=accepted,validation_after=winner.metrics,training_after=winner.training,
        independent_final_recheck=True,final_rejected_by=rejected,stop_reason=stop_reason,
        counters=scorer.counts,seconds=time.perf_counter()-started,
        feasible_pool=[row.sha256 for row in pool.feasible],
        exploratory_pool=[row.sha256 for row in pool.exploratory],
        export_from_exploratory=False)
    selected['entries'] = [winner.entry]
    return selected if accepted else None,grid_from(winner.entry),audit
