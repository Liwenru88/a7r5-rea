"""按版本化新规则复评已有BIN，不重训，不采用或覆盖原配方。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]
import numpy as np
from PIL import Image,ImageDraw
import baseline,core
from calibrated_guard import RampBank,phase_rgb
from edit_parameter_context import ParameterContext,RuntimeColor
from grid_models import default_response
from native_four_experiment import metric_failures,transition_failures
from native_guard_policy import POLICY,build_calibration,TargetToneBank,quality_failures,multiscale_report,transition_review,photo_failures,legality_failures,decision,dense_probe_inputs
from integer_grid import PROBE_AXES
from benchmark_native_four import digest,save,blob,predict,combined_metrics,photo_summary
from perceptual import to_lab


def strips(path,rows,labels,*,width=1020):
    height=28
    image=Image.new('RGB',(width+160,height*len(rows)),'white');draw=ImageDraw.Draw(image)
    for index,(row,label) in enumerate(zip(rows,labels)):
        pixels=np.floor(np.clip(row,0,1)*255+.5).astype('uint8')
        tile=Image.fromarray(pixels[None]).resize((width,height-3),Image.Resampling.NEAREST)
        image.paste(tile,(160,index*height));draw.text((5,index*height+7),label,fill='black')
    image.save(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('bin','manifest','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--candidate',action='append',required=True,help='名称=单槽BIN路径，可重复')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.manifest.read_text());frozen=args.manifest.parent
    protected={str(args.bin):digest(args.bin),str(args.manifest):digest(args.manifest)}
    def load(record):
        path=frozen/record['file']
        if digest(path)!=record['sha256']:raise ValueError('冻结输入摘要变化')
        protected[str(path)]=digest(path)
        with np.load(path,allow_pickle=False) as data:return {key:data[key] for key in data.files}
    chart=load(manifest['chart']);target=chart['target_5']
    config=core.compiler.unpack(args.bin.read_bytes());original=next(x for x in config['entries'] if x['number']==5)
    (args.output/'preserved-full-library.BIN').write_bytes(args.bin.read_bytes())
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True);response=default_response()
    reference=predict(context,original,chart['input'],response)
    gray=(chart['anchor_index']>=4)&(chart['anchor_index']<260);train=chart['split']=='train'
    scenes=[(scene,load(scene)) for scene in manifest['scenes']]
    old_photos={scene['scene']:predict(context,original,data['inputs'],response) for scene,data in scenes}
    development=[(s['scene'],old_photos[s['scene']],d['target_5'],d['display']) for s,d in scenes if s['role']=='development']
    calibration=build_calibration(reference[train],target[train],gray[train],development)
    save(args.output/'calibration.json',calibration)
    # 阈值只由原配方/TRAIN/开发照片推导，先于候选评分冻结。
    tone=TargetToneBank(chart['design_srgb'],target,chart['split'],chart['sample_kind'],reference)
    banks={p:RampBank(p) for p in (.17,.53,.87)}
    base_ramps={p:predict(context,original,b.inputs(context.base),response) for p,b in banks.items()}
    save(args.output/'protocol.json',dict(policy=POLICY,calibration_sha256=digest(args.output/'calibration.json'),
        transition_strides=[1,2,4],phases=list(banks),candidate_selection_performed=False,
        interpretation='历史候选的事后复评；不改变旧实验结论，不是新的独立训练确认'))
    source_paths=[Path(__file__),ROOT/'web/native_guard_policy.py',ROOT/'web/native_feasible_experiment.py',
        ROOT/'scripts/benchmark_native_four.py',ROOT/'web/calibrated_guard.py']
    sources={str(path.relative_to(ROOT)):digest(path) for path in source_paths}
    for path in source_paths:
        snapshot=args.output/'source-snapshot'/path.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True,exist_ok=True);snapshot.write_bytes(path.read_bytes())
    report=dict(policy=POLICY,original_bin_sha256=digest(args.bin),response=response,camera_connected=False,
        recipes_changed=False,training_performed=False,calibration=calibration,candidates=[])
    for argument in args.candidate:
        name,value=argument.split('=',1)
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('候选名称无效')
        path=Path(value);protected[str(path)]=digest(path);data=path.read_bytes()
        hard=legality_failures(data);row=dict(name=name,sha256=digest(path))
        if hard:
            row.update(status='rejected',hard_failures=hard,review_reasons=[]);report['candidates'].append(row);continue
        entry=core.compiler.unpack(data)['entries'][0]
        if entry['number']!=5:raise ValueError('只评估暖金日光第5槽')
        folder=args.output/name;folder.mkdir();(folder/'candidate.BIN').write_bytes(data)
        predicted=predict(context,entry,chart['input'],response)
        qualities={};legacy=[]
        for part in ('train','valid','test'):
            mask=chart['split']==part
            before=combined_metrics(reference[mask],target[mask],reference[gray],target[gray])
            after=combined_metrics(predicted[mask],target[mask],predicted[gray],target[gray])
            failures=quality_failures(after,before,calibration['chart'],require_improvement=part!='train')
            qualities[part]=dict(baseline=before,candidate=after,failures=failures)
            hard += [part+':'+key for key in failures]
            legacy += [part+':'+key for key in metric_failures(after,before)]
        transitions={};legacy_transitions={};dense_evidence=[]
        for phase,bank in banks.items():
            rendered=predict(context,entry,bank.inputs(context.base),response)
            transitions[str(phase)]=multiscale_report(bank,base_ramps[phase],rendered)
            # 仅保存旧规则的零退步部分，旧局部0.5/0.75结果由原实验保留。
            old=bank.jumps(phase_rgb(base_ramps[phase]));new=bank.jumps(phase_rgb(rendered))
            legacy_transitions[str(phase)]=[axis+':'+key for axis in old for key,func in (('p95',lambda a:np.percentile(a,95)),('max',np.max)) if func(new[axis])>func(old[axis])+1e-10]
            for axis in PROBE_AXES:
                original_lines=bank.lines(base_ramps[phase],axis);new_lines=bank.lines(rendered,axis)
                curvature=np.linalg.norm(np.diff(to_lab(new_lines*255)[...,1:],n=2,axis=1),axis=-1)
                worst=int(np.argmax(np.max(curvature,axis=1)))
                strips(folder/f'{phase}-{axis}.png',[original_lines[worst],new_lines[worst]],['Original '+axis,'Candidate '+axis])
                design,inputs=dense_probe_inputs(bank,axis,worst,context.base)
                dense_old=predict(context,original,inputs,response);dense_new=predict(context,entry,inputs,response)
                image_path=folder/f'{phase}-{axis}-dense.png'
                strips(image_path,[dense_old,dense_new],['Original '+axis,'Candidate '+axis],width=len(design))
                np.savez_compressed(folder/f'{phase}-{axis}-dense.npz',design=design,input=inputs,original=dense_old,candidate=dense_new)
                def adjacent(rgb):
                    from perceptual import de2000
                    lab=to_lab(rgb*255);steps=de2000(lab[:-1],lab[1:])
                    return dict(max=float(steps.max()),p95=float(np.percentile(steps,95)))
                dense_evidence.append(dict(axis=axis,phase=phase,line=worst,samples=len(design),
                    source_path_verified=True,image_file=str(image_path.relative_to(args.output)),image_sha256=digest(image_path),
                    original_adjacent_de00=adjacent(dense_old),candidate_adjacent_de00=adjacent(dense_new),
                    interpretation='重新渲染的离线高密度探针，不是已确认的人眼阈值'))
        reviews=transition_review(transitions)
        photos=[]
        for scene,archive in scenes:
            output=predict(context,entry,archive['inputs'],response)
            failures,regions=photo_failures(old_photos[scene['scene']],output,archive['target_5'],archive['display'],calibration['photo'])
            hard += [f"photo:{scene['scene']}:{reason}" for reason in failures]
            photos.append(dict(scene=scene['scene'],role=scene['role'],baseline=regions['whole']['baseline'],
                candidate=regions['whole']['candidate'],regions=regions,failures=failures))
        summary={role:{key:photo_summary(photos,role,key) for key in ('baseline','candidate')} for role in ('development','holdout')}
        for key in ('rgb_rmse','delta_e00_mean'):
            if summary['holdout']['candidate'][key]>=summary['holdout']['baseline'][key]-1e-10:hard.append('holdout_mean:'+key)
        tone_before=tone.report(reference);tone_after=tone.report(predicted)
        target_pixels=target[tone.indices];old_pixels=reference[tone.indices];new_pixels=predicted[tone.indices]
        panels=[];labels=[]
        for index in range(24):
            for pixels,label in ((target_pixels,'target'),(old_pixels,'original'),(new_pixels,'candidate')):
                panels.append(pixels[index]);labels.append(f'{index:02d} {label}')
        strips(folder/'measured-target-tonal-rays.png',panels,labels)
        row.update(status=decision(hard,reviews),hard_failures=hard,review_reasons=reviews,chart=qualities,
            transitions=transitions,legacy_numeric_failures=legacy,legacy_zero_transition_failures=legacy_transitions,
            target_gradient=dict(baseline=tone_before,candidate=tone_after),photos=photos,photo_summary=summary,
            dense_transition_evidence=dense_evidence,
            adopted=False,reason='本次只复评；未修改正式配方，需复核状态不自动采用')
        report['candidates'].append(row)
        print('ASSESSED',name,row['status'],'hard',len(hard),'review',len(reviews),flush=True)
    if any(digest(path)!=sha for path,sha in protected.items()):raise ValueError('输入摘要变化')
    if any(digest(ROOT/path)!=sha for path,sha in sources.items()):raise ValueError('复评时源码变化')
    report.update(protected_inputs=protected,protected_inputs_unchanged=True,source_sha256=sources)
    save(args.output/'result.json',report)
    lines=['# 新保护规则离线复评','','这是对已存在BIN的事后复评，不重训、不改旧结论、不替换原配方。',
        '合法性和颜色质量可硬拒绝；合成过渡的未确认异常进入复核；小幅未校准超限保留诊断。量化容差不是人眼可见阈值。','',
        '| 候选 | 新状态 | 硬拒绝项数 | 待复核项数 |','|---|---|---:|---:|']
    for row in report['candidates']:lines.append(f"| {row['name']} | {row['status']} | {len(row['hard_failures'])} | {len(row['review_reasons'])} |")
    lines+=['','`eligible_offline`只表示本轮数值检查通过；`review_required`不能自动采用；`rejected`存在明确的合法性或颜色质量失败。',
        '每张照片及九个固定区域分别检查，不由照片平均改善掩盖单张退步。没有真实标签的合成原生域渐变不冒充目标图。',
        '多相位、多尺度过渡统计、实测目标渐变、图像条带及详细拒绝原因见result.json与各候选目录。',
        '未连接相机，BIN格式和正式库未改。']
    (args.output/'复评报告.md').write_text('\n'.join(lines)+'\n')
    print('DONE',args.output,flush=True)


if __name__=='__main__':main()
