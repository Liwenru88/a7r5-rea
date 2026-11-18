"""整数轮次日志使用最终已接受配方，拦截原因不重复计算候选数。"""
from native_joint_integer import integer_event


def test_integer_event_reports_accepted_metrics_and_rejections():
    best=dict(metrics=dict(rgb_rmse=3.,delta_e00_mean=1.,gray_rmse=2.),failures=[],fully_evaluated=True)
    checked=[dict(failures=['gray_rmse','dense:phase:max']),best]
    record=dict(sweep=0,group='grid',improving_training_neighbors=12,accepted=1)
    event=integer_event(best,record,checked)
    assert event['metrics']==best['metrics']
    assert event['proposed_moves']==12 and event['applied_moves']==1
    assert event['rejected_candidates']==1
    assert event['gray_rejections']==1 and event['saturation_rejections']==1
    assert event['gray_passed'] and event['saturation_passed']
