"""保留既有 BIN，隔离比较旧 128 点投影与完整 129 点前向。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'), str(ROOT/'scripts')]
import baseline
import core
from calibrated_guard import RampBank, calibrate, phase_rgb, ramp_report
from edit_parameter_context import ParameterContext, RuntimeColor
from fit_bin_joint import grid_from
from grid_models import default_response
from measured_response import get
from native_scoring import color_metrics
from native_gamma import POLICY, tensor_table
from patch_sampling import center_mean
from photo_preview import quantize, SRGB_ICC


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n')


def native(model, inputs):
    return np.concatenate([center_mean(model.color_only(inputs[i:i+8192]))/16383
                           for i in range(0,len(inputs),8192)])


def chart_rows(prediction, target, archive):
    rows={part:color_metrics(prediction[archive['split']==part],target[archive['split']==part])
          for part in ('train','valid','test')}
    gray=(archive['anchor_index']>=4)&(archive['anchor_index']<260)
    if int(gray.sum())!=256 or not np.all(archive['split'][gray]=='train'):
        raise ValueError('冻结灰阶样本不完整')
    rows['gray']=color_metrics(prediction[gray],target[gray])
    return rows


def comparison_image(path, display, target, legacy, complete):
    rows=[quantize(value)[display] for value in (target,legacy,complete)]
    height,width=rows[0].shape[:2]
    image=Image.new('RGB',(3*width,height+36),'white')
    draw=ImageDraw.Draw(image)
    try:
        font=ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',16)
        labels=('目标图','旧128点前向','完整129点前向')
    except OSError:
        font=ImageFont.load_default(size=16)
        labels=('Target','Legacy 128','Complete 129')
    for index,(pixels,label) in enumerate(zip(rows,labels)):
        image.paste(Image.fromarray(pixels),(index*width,36))
        draw.text((index*width+8,8),label,font=font,fill='black')
    image.save(path,icc_profile=SRGB_ICC)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.manifest.read_text())
    frozen=args.manifest.parent
    protected={str(args.bin):digest(args.bin),str(args.manifest):digest(args.manifest)}
    chart_path=frozen/manifest['chart']['file']
    if digest(chart_path)!=manifest['chart']['sha256']:
        raise ValueError('冻结色卡摘要变化')
    protected[str(chart_path)]=digest(chart_path)
    with np.load(chart_path,allow_pickle=False) as archive:
        chart={key:archive[key] for key in archive.files}
    config=core.compiler.unpack(args.bin.read_bytes())
    if core.compiler.pack(config)!=args.bin.read_bytes():
        raise ValueError('原 BIN 往返不一致')
    save(args.output/'preserved-config.json',config)
    factory=RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID))
    context=ParameterContext(factory)
    response=get(default_response())
    report=dict(schema='r5-gamma129-reassessment/1',policy=POLICY,
        recipe_changed=False,new_filter_training=False,camera_connected=False,
        original_bin_sha256=protected[str(args.bin)],format=core.compiler.format_version(config),
        response=default_response(),input_manifest_sha256=digest(args.manifest),
        source_split_sha256=manifest['chart']['split_sha256'],
        scope='同一 BIN、同一响应、同一输入；只比较 Gamma 前向映射，不是新旧训练配方选优。',
        photo_scope='既有六张开发与四张留出照片，沿用冻结曝光对齐；不是首次盲测或机内 JPEG。',filters=[])
    for entry in config['entries']:
        if entry['number'] not in (5,6,14):
            continue
        slot=entry['number'];name=entry['short_name']
        parameters=core.slot_native_parameters(context,entry)
        complete=context.build(**parameters)
        # 旧模型只用于本次对照，不重新暴露给训练或预览入口。
        old=dict(parameters,gamma_y=[2*v for v in entry['gamma_native_129'][:128]])
        legacy=context.build(**old)
        models={'legacy128':legacy,'complete129':complete}
        gpu=tensor_table(entry['gamma_native_129'],contrast=context.contrast,device='mps').cpu().numpy()
        cpu=np.frombuffer(complete.runtime,'<u2',count=65536,offset=0x18f6)
        if not np.array_equal(gpu,cpu):
            raise ValueError('MPS Gamma 整数查表不一致')
        grid=grid_from(entry)
        def predict(model, inputs):
            return response.predict_cpu(native(model,inputs),grid)
        target=chart['target_'+str(slot)]
        result=dict(slot=slot,name=entry['full_name'],gamma_tail=entry['gamma_native_129'][-3:],
                    cpu_mps_all_65536_equal=True,chart={},photos=[],transitions={})
        for key,model in models.items():
            result['chart'][key]=chart_rows(predict(model,chart['input']),target,chart)
        development={key:[] for key in models}
        destination=args.output/name
        destination.mkdir()
        for scene in manifest['scenes']:
            path=frozen/scene['file']
            if digest(path)!=scene['sha256']:
                raise ValueError('冻结照片摘要变化：'+scene['scene'])
            protected[str(path)]=digest(path)
            with np.load(path,allow_pickle=False) as data:
                inputs=data['inputs'];target=data['target_'+str(slot)];display=data['display']
                predictions={key:predict(model,inputs) for key,model in models.items()}
                row=dict(scene=scene['scene'],role=scene['role'],samples=len(target),
                         metrics={key:color_metrics(rgb,target) for key,rgb in predictions.items()})
                if scene['role']=='development':
                    for key,rgb in predictions.items():
                        development[key].append((scene['scene'],rgb,target))
                comparison_image(destination/(scene['scene']+'.png'),display,target,
                                 predictions['legacy128'],predictions['complete129'])
                result['photos'].append(row)
            print('PHOTO_CHECKED',slot,scene['scene'],scene['role'],flush=True)
        result['photo_summary']={role:{key:{metric:float(np.mean([row['metrics'][key][metric]
            for row in result['photos'] if row['role']==role]))
            for metric in ('rgb_rmse','delta_e00_mean','delta_e00_p95')}
            for key in models} for role in ('development','holdout')}
        calibration_bank=RampBank(.17)
        calibration_inputs=calibration_bank.inputs(factory)
        margins={key:calibrate(calibration_bank,predict(model,calibration_inputs),development[key])
                 for key,model in models.items()}
        for phase in (.53,.87):
            bank=RampBank(phase);inputs=bank.inputs(factory)
            jumps={key:bank.jumps(phase_rgb(predict(model,inputs))) for key,model in models.items()}
            scores,failures=ramp_report(jumps['legacy128'],jumps['complete129'],margins['legacy128'])
            result['transitions'][str(phase)]=dict(
                maxima={key:{axis:dict(p95=float(np.percentile(values,95)),maximum=float(values.max()))
                        for axis,values in axes.items()} for key,axes in jumps.items()},
                cross_model_diagnostic=scores,cross_model_diagnostic_failures=failures)
        result['transition_margins']=margins
        report['filters'].append(result)
        save(args.output/'result.json',report)
        print('FILTER_CHECKED',slot,name,flush=True)
    for path,expected in protected.items():
        if digest(Path(path))!=expected:
            raise ValueError('对照数据被修改：'+path)
    report['protected_inputs_unchanged']=True
    report['protected_files']=protected
    report['implementation_sha256']={name:digest(ROOT/name) for name in
        ('scripts/native_gamma.py','scripts/edit_native_model.py','scripts/edit_parameter_context.py',
         'web/core.py','web/fit_anchor_native.py','web/apple_gpu.py','web/packed_training.py')}
    save(args.output/'result.json',report)
    lines=['# 完整129点Gamma离线复评','',
           '同一份现有 BIN，分别按旧前向与完整前向评分。未训练或替换配方，未连接相机。',
           'RGB RMSE 为8位码值；ΔE00 为色差。照片按场景等权平均，P95一列为各场景P95的平均。','',
           '| 滤镜 | 范围 | RGB RMSE 旧→完整 | 平均 ΔE00 旧→完整 | P95 旧→完整 |',
           '|---|---|---:|---:|---:|']
    for row in report['filters']:
        for scope,kind in (('色卡留出','test'),('训练灰阶','gray')):
            a,b=[row['chart'][key][kind] for key in ('legacy128','complete129')]
            lines.append(f"| {row['name']} | {scope} | {a['rgb_rmse']:.4f}→{b['rgb_rmse']:.4f} | {a['delta_e00_mean']:.4f}→{b['delta_e00_mean']:.4f} | {a['delta_e00_p95']:.4f}→{b['delta_e00_p95']:.4f} |")
        a,b=[row['photo_summary']['holdout'][key] for key in ('legacy128','complete129')]
        lines.append(f"| {row['name']} | 四张留出照片 | {a['rgb_rmse']:.4f}→{b['rgb_rmse']:.4f} | {a['delta_e00_mean']:.4f}→{b['delta_e00_mean']:.4f} | {a['delta_e00_p95']:.4f}→{b['delta_e00_p95']:.4f} |")
    lines.extend(['','## 双域过渡','',
        '使用 .17 相位和开发照片分别重算两种模型的容差；.53/.87 相位只复评。跨模型比较用于暴露历史评分偏差，不作为新配方采用结论。',''])
    for row in report['filters']:
        failures=row['transitions']['0.87']['cross_model_diagnostic_failures']
        lines.append(f"- {row['name']}：跨模型诊断超限项：{', '.join(failures) if failures else '无'}。详细双域各轴 P95、最大值和重校准容差见 result.json。")
    lines.extend(['','原有曲线、四组参数和 BIN 字节全部保留；所有输入 SHA256 在复评前后核对一致。',
        '本报告不能证明机内效果。补齐前向可能让离线分数变差，这反映既有配方原先未被完整评价，不能解释为本次重新训练退步。'])
    (args.output/'复评说明.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(filters=len(report['filters']),protected_inputs_unchanged=True,
                         report=str(args.output/'复评说明.md')),ensure_ascii=False))


if __name__=='__main__':
    main()
