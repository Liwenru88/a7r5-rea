"""完整照片收敛不能牺牲已经取得的色卡、灰阶与P95收益。"""
from native_joint_photo import photo_choice


def row(label,rgb,de,score):
    return dict(label=label,metrics=dict(rgb_rmse=rgb,delta_e00_mean=de,delta_e00_p95=6.,gray_rmse=2.),
        score=score,failures=[],fully_evaluated=True)


def test_photo_score_cannot_trade_away_previously_qualified_color_gain():
    baseline=row('baseline',5.,3.,3.);prior=row('prior',4.,2.,2.5)
    worse=row('worse-color',4.1,1.8,1.)
    assert photo_choice(baseline,prior,[worse])['label']=='prior'
    better=row('improved',3.9,1.9,2.)
    assert photo_choice(baseline,prior,[worse,better])['label']=='improved'


def test_final_photo_stage_keeps_previous_photo_means_as_well():
    baseline=row('baseline',5.,3.,3.);prior=row('prior',4.,2.,2.5)
    prior['photos']=[dict(metrics=dict(rgb_rmse=6.,delta_e00_mean=2.))]
    candidate=row('better-chart-worse-photo',3.9,1.9,2.)
    candidate['photos']=[dict(metrics=dict(rgb_rmse=6.1,delta_e00_mean=2.1))]
    assert photo_choice(baseline,prior,[candidate])['label']=='prior'
