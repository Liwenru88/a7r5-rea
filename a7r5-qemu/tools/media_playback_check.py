"""独立介质候选的回放门槛与返回验证；无卡画面不能算照片回放。"""
from menu_bridge import atomic_json, capture
from menu_live import key_command
from input_batch import wait_research_receipt

NO_CARD_PIXEL='675aa8d5319f7284958ea7905dd739f7bf66ebc1d9245fe3cc3aaaa365210b5b'


def run(vm,batch):
    report={'status':'requires-inspection','photo_playback_verified':False,'photo_switch_verified':False,'steps':[]}
    target=vm.out/'media-playback-check.json'
    previous=batch['steps'][-1]['frame']
    if vm.last_native_screen()!=0x45f or previous['pixel_sha256']!=NO_CARD_PIXEL:
        atomic_json(target,report)
        return report
    report['original_no_card_confirmed']=True
    shooting=batch['steps'][-2]['frame']['pixel_sha256']

    def step(key,expected):
        nonlocal previous
        before=vm.last_native_screen()
        offset=vm.console.stat().st_size
        data=vm.command(key_command(key),timeout=30)
        vm.wait_native_screen(expected)
        receipt=wait_research_receipt(vm,key,before,offset)
        _,frame=capture(vm,f'media-return-{len(report["steps"]):02d}-{key}',after=previous['sequence'])
        report['steps'].append({'key':key,'screen':vm.last_native_screen(),'receipt':receipt,'frame':frame})
        previous=frame
        return frame

    try:
        returned=step('PLAYBACK',0)
        if returned['pixel_sha256']!=shooting:raise RuntimeError('无卡回放返回未恢复原拍摄信息画面')
        menu=None
        for _ in range(2):
            frame=step('MENU',0x2d6)
            if menu is not None and frame['pixel_sha256']!=menu:raise RuntimeError('两次菜单重入画面不一致')
            menu=frame['pixel_sha256']
            if step('MENU',0)['pixel_sha256']!=shooting:raise RuntimeError('菜单关闭未恢复原拍摄信息画面')
        report.update(status='no-card-only',no_card_return_verified=True,menu_roundtrips=2)
        vm.set_native_paused(True)
        return report
    except Exception as error:
        report.update(status='failed',error=str(error))
        raise
    finally:
        atomic_json(target,report)
