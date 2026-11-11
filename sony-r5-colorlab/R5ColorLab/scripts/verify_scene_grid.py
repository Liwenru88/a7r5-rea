"""使用未参与筛选的配对照片复验锁定的艾克塔 100 网格。"""
import argparse
import json
from pathlib import Path
from statistics import mean

from PIL import Image

from benchmark_scene_grid import (
    FILTERS, ROOT, digest, evaluate_scenes, make_scenes, parse_roi, prepare_photos, unique_target,
)
import baseline
import core
from benchmark_joint import save
from edit_parameter_context import ParameterContext, RuntimeColor
from fit_bin_joint import grid_from
from measured_response import get
from photo_preview import FRONTEND_REVISION, SRGB_ICC, quantize


SLOT = 11
METRICS = ('delta_e00_mean', 'rgb_rmse')
REQUIRED_REGIONS = {'skin', 'shadows', 'near-neutral', 'high-chroma'}


def locked_candidate(experiment):
    receipt = experiment/'comparison.json'
    report = json.loads(receipt.read_text())
    case, = (row for row in report['cases'] if row['slot'] == SLOT)
    recorded = case['results']['guarded']
    if recorded['scene_failures'] or recorded['holdout_ramp_failures'] or not recorded['changed_grid_coefficients']:
        raise ValueError('候选未通过上一轮开发场景和独立渐变门槛')
    if report['raw_frontend'] != FRONTEND_REVISION:
        raise ValueError('RAW 前端版本与冻结实验不同')
    for name, sha in report['source_hashes'].items():
        files = [path for directory in ('scripts', 'web') if (path := ROOT/directory/name).is_file()]
        if len(files) != 1 or digest(files[0]) != sha:
            raise ValueError(f'冻结实验的源码身份已变化：{name}')

    entries = []
    for arm, filename in (('baseline', 'original.BIN'), ('guarded', 'guarded.BIN')):
        blob = (experiment/f'{SLOT:02}'/filename).read_bytes()
        if core.sha(blob) != case['results'][arm]['sha256']:
            raise ValueError(f'冻结配方摘要不符：{filename}')
        entry, = core.compiler.unpack(blob)['entries']
        entries.append(entry)
    original, candidate = entries
    if original['number'] != SLOT or any(original[key] != candidate[key] for key in original if key != 'grid_5x9x9'):
        raise ValueError('锁定候选改变了原生参数')
    return report, case, original, candidate


def new_photo_pairs(data, folder, report, case):
    photos = sorted((data/'原始照片').glob('*.arw'))
    if len(photos) < 2:
        raise ValueError('至少需要两组不同的新场景 RAW／目标 TIFF')
    prior_raw = {row['raw_sha256'] for row in report['photo_inputs']}
    prior_targets = {row['sha256'] for row in case['scene_inputs'].values()}
    pairs = {}
    for photo in photos:
        target = unique_target((folder/'目标照片').glob(photo.stem+'*.tif'))
        raw_sha, target_sha = digest(photo), digest(target)
        if raw_sha in prior_raw or target_sha in prior_targets:
            raise ValueError(f'照片或目标图已用于开发，或在本次复验中重复：{photo.name}')
        prior_raw.add(raw_sha)
        prior_targets.add(target_sha)
        pairs[photo.stem] = (raw_sha, target_sha)
    return pairs


def adoption_check(scenes, rows, region_failures):
    coverage = {name for scene in scenes for name in scene['guard'].groups}
    missing = sorted(REQUIRED_REGIONS - coverage)
    improvement = {}
    for key in METRICS:
        original = mean(scene['guard'].baseline['whole'][key] for scene in scenes)
        candidate = mean(rows[scene['name']]['whole'][key] for scene in scenes)
        margin = mean(scene['guard'].limits['whole'][key]-scene['guard'].baseline['whole'][key] for scene in scenes)
        improvement[key] = dict(original=original, candidate=candidate, gain=original-candidate,
                                quantization_margin=margin)
    failures = [*region_failures, *(f'missing-region:{name}' for name in missing)]
    failures.extend(f'no-measurable-gain:{key}' for key, row in improvement.items()
                    if row['gain'] <= row['quantization_margin'] + 1e-10)
    return dict(status='pass' if not failures else 'retain-original', failures=failures,
                coverage=sorted(coverage), mean_scene_metrics=improvement)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path, help='上一轮 comparison.json 所在的 results 目录')
    parser.add_argument('data', type=Path, help='仅包含新场景，目录结构与上轮相同')
    parser.add_argument('output', type=Path)
    parser.add_argument('--skin-roi', type=parse_roi, action='append', default=[])
    args = parser.parse_args()
    try:
        report, case, original, candidate = locked_candidate(args.experiment)
        folder = args.data/'滤镜'/FILTERS[SLOT]
        pairs = new_photo_pairs(args.data, folder, report, case)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    capture, context_id = baseline.resolve(report['dataset'])
    if context_id != report['context'] or digest(capture/'report.json') != report['capture_report_sha256']:
        parser.error('原生成像模型与冻结实验不同')
    context = ParameterContext(RuntimeColor.from_capture(capture, context_id))
    model = context.build(**core.slot_native_parameters(context, original))
    photos = list(prepare_photos(args.data, {SLOT: folder}, context.base,
                                 report['preview_long_edge'], dict(args.skin_roi)))
    if {p['name']: (p['raw_sha256'], p['targets'][SLOT][2]['sha256']) for p in photos} != pairs:
        raise ValueError('新场景的文件在复验准备期间发生变化')
    response = get(report['response'])
    seed, grid = grid_from(original), grid_from(candidate)
    scenes = make_scenes(photos, SLOT, model, response, seed)
    rows, failures = evaluate_scenes(scenes, response, grid)
    result = adoption_check(scenes, rows, failures)
    args.output.mkdir(parents=True, exist_ok=False)
    for scene in scenes:
        display = scene['display']
        pixels = {'original': response.predict_cpu(scene['base'], seed),
                  'candidate': response.predict_cpu(scene['base'], grid), 'target': scene['target']}
        for arm, rgb in pixels.items():
            Image.fromarray(quantize(rgb)[display]).save(args.output/f"{scene['name']}-{arm}.png",
                                                        icc_profile=SRGB_ICC)
    result.update(experiment_sha256=digest(args.experiment/'comparison.json'), response=report['response'],
                  original_sha256=case['results']['baseline']['sha256'],
                  candidate_sha256=case['results']['guarded']['sha256'], photo_pairs=pairs,
                  skin_rois=dict(args.skin_roi), scene_baseline={s['name']:s['guard'].baseline for s in scenes},
                  scene_limits={s['name']:s['guard'].limits for s in scenes}, scene_candidate=rows)
    save(args.output/'verification.json', result)
    print(result['status'], ', '.join(result['failures']), flush=True)


if __name__ == '__main__':
    main()
