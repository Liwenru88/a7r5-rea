"""完整开发照片收敛阶段；保住先前已合格的色卡、灰阶和P95。"""
from pathlib import Path
from native_joint import choose
from native_runtime import blob,save


def photo_choice(baseline,prior,candidates):
    protected=('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse')
    def allowed(row):
        if any(row['metrics'][k]>prior['metrics'][k]+1e-8 for k in protected):return False
        if prior.get('photos'):
            if not row.get('photos'):return False
            for k in ('rgb_rmse','delta_e00_mean'):
                before=sum(p['metrics'][k] for p in prior['photos'])/len(prior['photos'])
                after=sum(p['metrics'][k] for p in row['photos'])/len(row['photos'])
                if after>before+1e-8:return False
        return True
    eligible=[row for row in candidates if allowed(row)]
    return choose(baseline,[prior]+eligible)


def polish_photos(data,gate,prior,output,*,steps=600,progress=None):
    if not data.photos:raise ValueError('完整照片收敛需要绑定开发照片')
    from native_conditional_grid import fit_grid
    _,audit=fit_grid(data,gate,prior['entry'],output,steps=steps,freeze_gray=True,full_photos=True,progress=progress)
    audit['candidates']=[dict(row,label='full-photo/'+row['label']) for row in audit['candidates']]
    selected=photo_choice(gate.baseline,prior,audit['candidates'])
    audit.update(unrestricted_pick=audit['selected'],selected=selected,prior=prior,
        selection_policy='preserve-prior-RGB-DE-P95-gray-photo-means; complete-development-gate')
    output=Path(output);(output/'selected.BIN').write_bytes(blob(selected['entry']));save(output/'audit.json',audit)
    return selected['entry'],audit
