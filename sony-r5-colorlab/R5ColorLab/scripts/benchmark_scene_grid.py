"""固定原生配方，用配对场景比较等时预算的整数网格精修。"""
import argparse
import hashlib
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))

import baseline
import chart_target
import core
from benchmark_calibrated_fit import native_rgb, write_bin
from benchmark_joint import save
from calibrated_guard import RampBank, SceneProtection, calibrate, ramp_report
from calibration_photos import raw_samples, target_samples
from edit_parameter_context import ParameterContext, RuntimeColor
from fit_bin_joint import grid_from
from grid_models import default_response
from integer_blocks import grid_entry
from integer_grid import polish_grid
from measured_response import get
from native_scoring import RecipeScorer, adoption_failures, color_metrics
from output_continuity import ProbeBank
from perceptual import to_lab
from photo_preview import FRONTEND_REVISION, SRGB_ICC, quantize


FILTERS = {10: '富士_velvia_100', 11: '柯达_ektar_100'}
ARMS = ('baseline', 'ordinary', 'guarded')
CONTINUITY_STRENGTH = 30


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unique_target(paths):
    matches = list(paths)
    if len(matches) != 1:
        raise ValueError(f'需要唯一配对目标，实际匹配 {matches}')
    return matches[0]


def scene_groups(target, display, skin):
    lab = to_lab(quantize(target))
    lightness, chroma = lab[:, 0], np.linalg.norm(lab[:, 1:], axis=1)
    groups = {
        'whole': np.arange(len(target)),
        'shadows': np.flatnonzero(lightness <= 25),
        'near-neutral': np.flatnonzero((chroma <= 8) & (lightness > 25) & (lightness < 90)),
        'high-chroma': np.flatnonzero(chroma >= 35),
    }
    if skin is not None:
        x0, y0, x1, y1 = skin
        height, width = display.shape
        indices = display[int(y0*height):int(y1*height), int(x0*width):int(x1*width)].ravel()
        if len(indices) < 16:
            raise ValueError('人工肤色区域不足 16 个采样点')
        groups['skin'] = indices
    return {name: rows for name, rows in groups.items() if len(rows) >= 16}


def parse_roi(value):
    try:
        stem, coordinates = value.split(':', 1)
        x0, y0, x1, y1 = map(float, coordinates.split(','))
        if 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1:
            return stem, (x0, y0, x1, y1)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('肤色区域须为 文件名:x0,y0,x1,y1，坐标按正向预览图归一化')


def prepare_photos(root, folders, reference, long_edge, skin_rois):
    photos = sorted((root/'原始照片').glob('*.arw'))
    if not photos or set(skin_rois) - {photo.stem for photo in photos}:
        raise ValueError('原片缺失，或人工肤色区域引用未知原片')
    for photo in photos:
        front, sizes, xs, ys, wb = raw_samples(photo, reference, long_edge)
        rotation = {0: 0, 3: 2, 5: 1, 6: 3}[sizes.flip]
        display = np.rot90(np.arange(len(front)).reshape(len(ys), len(xs)), rotation)
        targets = {}
        for slot, folder in folders.items():
            path = unique_target((folder/'目标照片').glob(photo.stem+'*.tif'))
            target = target_samples(path, sizes, xs, ys)
            groups = scene_groups(target, display, skin_rois.get(photo.stem))
            targets[slot] = (target, groups, {'file': path.name, 'sha256': digest(path)})
        yield dict(name=photo.stem, raw_sha256=digest(photo), white_balance=wb, front=front,
                   targets=targets, display=display, skin_roi=skin_rois.get(photo.stem))
        print(f'已对齐原片和目标 {photo.name}', flush=True)


def make_scenes(photos, slot, model, response, seed):
    scenes = []
    for photo in photos:
        target, groups, identity = photo['targets'][slot]
        base = native_rgb(model, photo['front'])
        pixels = response.predict_cpu(base, seed)
        guard = SceneProtection(pixels, target, groups)
        scenes.append(dict(name=photo['name'], base=base, target=target, guard=guard,
                           identity=identity, display=photo['display']))
    return scenes


def evaluate_scenes(scenes, response, grid):
    rows, rejected = {}, []
    for scene in scenes:
        scores = scene['guard'].score(response.predict_cpu(scene['base'], grid))
        rows[scene['name']] = scores
        rejected.extend(f"{scene['name']}:{reason}" for reason in scene['guard'].failures(scores))
    return rows, rejected


def sampled_guards(scenes):
    result = []
    for scene in scenes:
        for group, indices in scene['guard'].groups.items():
            count = min(len(indices), 512 if group == 'whole' else 128)
            at = indices[np.linspace(0, len(indices) - 1, count, dtype=int)]
            result.append((scene['base'][at], scene['target'][at]))
    return tuple(result)


def search(start, scorer, response_spec, scenes, seconds, *, protected):
    _, rendered = scorer.native(start.entry)
    train, valid, probes = np.split(rendered, (scorer.ntrain, scorer.ntrain+scorer.nvalid))
    extra = sampled_guards(scenes) if protected else ()
    incumbent = start
    trials = []
    began = perf_counter()
    deadline = began + seconds
    proposal_deadline = deadline - min(5, seconds / 3)
    for sweep in range(1, 6):
        grid = grid_from(incumbent.entry)
        proposal, moves = polish_grid(grid, train, scorer.train_target, scorer.gray_train,
            probes, response_spec, scorer.bank, CONTINUITY_STRENGTH, start.metrics, deadline=proposal_deadline,
            validation_data=(valid, scorer.valid_target), step_sizes=(1, 2), protect_color_p95=True,
            color_guards=extra, color_guard_priority=protected)
        if not moves:
            break
        previous = incumbent
        for fraction in (1., .5, .25):
            table = np.rint(grid+fraction*(proposal.astype(int)-grid)).astype(np.int8)
            candidate = scorer.score(grid_entry(start.entry, table), f'{moves} moves / {fraction:g}')
            failures = adoption_failures(candidate.metrics, start.metrics, incumbent.metrics['color_score'])
            photo_failures = []
            if not failures and protected:
                _, photo_failures = evaluate_scenes(scenes, scorer.response, table)
            within_budget = perf_counter() < deadline
            trials.append(dict(sha256=candidate.sha256, sweep=sweep, moves=moves, fraction=fraction,
                               chart_rejections=failures, scene_rejections=photo_failures,
                               within_budget=within_budget))
            if within_budget and not failures and not photo_failures:
                incumbent = candidate
            if not within_budget:
                break
        if incumbent.sha256 == previous.sha256 or perf_counter() >= proposal_deadline:
            break
    return incumbent, dict(seconds=perf_counter()-began, budget=seconds, trials=trials)


def previews(path, scenes, response, tables):
    width, height, gap = 218, 145, 8
    canvas = Image.new('RGB', (4*width+2*gap, len(scenes)*(height+28)+40), '#181b21')
    draw = ImageDraw.Draw(canvas)
    for j, label in enumerate((*ARMS, 'target TIFF')):
        draw.text((gap+j*width, 12), label, fill='white')
    for i, scene in enumerate(scenes):
        top = 39+i*(height+28)
        draw.text((gap, top), scene['name'], fill='white')
        for j, rgb in enumerate([response.predict_cpu(scene['base'], table) for table in tables] + [scene['target']]):
            preview = Image.fromarray(quantize(rgb)[scene['display']])
            preview.thumbnail((width-gap, height), Image.Resampling.LANCZOS)
            canvas.paste(preview, (gap+j*width+(width-preview.width)//2, top+17))
    canvas.save(path, icc_profile=SRGB_ICC)


def run_filter(folder, target_folder, entry, version, photos, context, arrays, response_spec, seconds):
    chart = unique_target(path for path in target_folder.iterdir() if path.suffix.lower() in ('.tif', '.tiff'))
    targets, chart_audit = chart_target.decode(chart.read_bytes(), baseline.V45_ID)
    inputs, split = arrays['input'], arrays['split']
    train = np.flatnonzero(split == 'train')
    gray = (split == 'train') & (arrays['anchor_index'] >= 4) & (arrays['anchor_index'] < 260)
    validation = split == 'valid'
    scorer_args = (core.compiler.config([entry], version), context, inputs, targets, train, gray,
                   validation, response_spec, ProbeBank(), CONTINUITY_STRENGTH, .35)
    response = get(response_spec)
    scorer = RecipeScorer(*scorer_args)
    start = scorer.score(entry, 'baseline')
    model, _ = scorer.native(start.entry)
    seed = grid_from(start.entry)
    scenes = make_scenes(photos, entry['number'], model, response, seed)
    # 两组分别建立评分器，防止共享已试候选的缓存影响等时比较。
    choices = {'baseline': (start, None)}
    for arm in ('ordinary', 'guarded'):
        scorer = RecipeScorer(*scorer_args)
        start = scorer.score(entry, 'baseline')
        choices[arm] = search(start, scorer, response_spec, scenes, seconds, protected=arm == 'guarded')
        selected, search_audit = choices[arm]
        print(f"{entry['number']} {arm}: {len(search_audit['trials'])} 个候选, "
              f"{search_audit['seconds']:.1f} 秒, {selected.label}", flush=True)

    folder.mkdir()
    calibration, holdout_ramp = RampBank(.17), RampBank(.87)
    calibration_base, holdout_base = [native_rgb(model, bank.inputs(context.base))
                                       for bank in (calibration, holdout_ramp)]
    margins = calibrate(calibration, response.predict_cpu(calibration_base, seed),
        [(s['name'], response.predict_cpu(s['base'], seed), s['target']) for s in scenes])
    start_ramp = holdout_ramp.jumps(response.predict_cpu(holdout_base, seed))
    test_base = native_rgb(model, inputs[split == 'test'])
    final_scorer = RecipeScorer(*scorer_args)
    results, tables = {}, []
    for arm, (choice, audit) in choices.items():
        name = 'original.BIN' if arm == 'baseline' else f'{arm}.BIN'
        decoded, sha = write_bin(folder/name, choice.entry, version)
        final, = decoded['entries']
        if sha != choice.sha256 or any(final[k] != entry[k] for k in entry if k != 'grid_5x9x9'):
            raise ValueError('BIN 回读发生配方或非网格参数漂移')
        exact = final_scorer.score(final, 'readback')
        if exact.metrics != choice.metrics:
            raise ValueError('独立回读评分与搜索时评分不一致')
        table = grid_from(final)
        tables.append(table)
        scene_scores, failures = evaluate_scenes(scenes, response, table)
        ramp, ramp_failures = ramp_report(start_ramp, holdout_ramp.jumps(response.predict_cpu(holdout_base, table)), margins)
        results[arm] = dict(file=name, sha256=sha, search=audit,
                            changed_grid_coefficients=int(np.count_nonzero(seed != table)),
                            chart_validation=exact.metrics, scene_metrics=scene_scores,
                            scene_failures=failures, holdout_ramp=ramp, holdout_ramp_failures=ramp_failures,
                            chart_holdout=color_metrics(response.predict_cpu(test_base, table), targets[split == 'test']))
    previews(folder/'scenes.png', scenes, response, tables)
    result = dict(slot=entry['number'], name=entry['full_name'], chart_sha256=chart_audit['source_sha256'],
                  chart_samples=dict(train=len(train), validation=int(validation.sum()), holdout=int((split == 'test').sum())),
                  scene_inputs={s['name']:s['identity'] for s in scenes},
                  scene_limits={s['name']:s['guard'].limits for s in scenes}, results=results)
    save(folder/'comparison.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_bin', type=Path)
    parser.add_argument('data', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--long-edge', type=int, default=384)
    parser.add_argument('--skin-roi', type=parse_roi, action='append', default=[])
    args = parser.parse_args()
    if not np.isfinite(args.seconds) or args.seconds <= 0 or not 128 <= args.long_edge <= 1024:
        parser.error('预算须为正数，采样长边须为 128～1024')
    source = args.source_bin.read_bytes()
    config = core.compiler.unpack(source)
    entries = {entry['number']: entry for entry in config['entries']}
    if any(slot not in entries or label not in entries[slot]['full_name']
           for slot, label in ((10, '维尔维亚 100'), (11, '艾克塔 100'))):
        parser.error('需要第 10 槽维尔维亚 100、第 11 槽艾克塔 100 的冻结配方库')
    args.output.mkdir(parents=True, exist_ok=False)
    capture, context_id = baseline.resolve(baseline.V45_ID)
    context = ParameterContext(RuntimeColor.from_capture(capture, context_id))
    arrays, _ = core.measured_inputs(baseline.V45_ID)
    response_spec = default_response()
    folders = {slot: args.data/'滤镜'/name for slot, name in FILTERS.items()}
    photos = list(prepare_photos(args.data, folders, context.base, args.long_edge, dict(args.skin_roi)))
    report = dict(source_sha256=core.sha(source), response=response_spec,
                  capture_report_sha256=digest(capture/'report.json'), context=context_id,
                  source_hashes={path.name:digest(path) for path in (Path(__file__),
                      Path(__file__).with_name('calibration_photos.py'), ROOT/'web/calibrated_guard.py',
                      ROOT/'web/integer_grid.py', ROOT/'web/native_scoring.py')},
                  dataset=baseline.V45_ID, raw_frontend=FRONTEND_REVISION, preview_long_edge=args.long_edge,
                  search_budget=args.seconds, photo_usage='development protection only; no blind scenes provided',
                  photo_inputs=[{k:p[k] for k in ('name', 'raw_sha256', 'white_balance', 'skin_roi')} for p in photos],
                  cases=[])
    for slot, target_folder in folders.items():
        result = run_filter(args.output/f'{slot:02}', target_folder, entries[slot],
                            core.compiler.format_version(config), photos, context, arrays, response_spec, args.seconds)
        report['cases'].append(result)
        save(args.output/'comparison.json', report)


if __name__ == '__main__':
    main()
