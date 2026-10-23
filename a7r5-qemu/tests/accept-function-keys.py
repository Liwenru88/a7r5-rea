"""真实 Qt 验收：首次设置、Fn、五种显示布局、空介质回放和正常退出。"""
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QTabWidget,QScrollArea
from PIL import Image
from client.window import Window
from initial_setup import SETUP_STEPS


def main():
    app=QApplication(sys.argv);window=Window();window.show()
    evidence=ROOT/'logs/key-dispatch'
    target=evidence/'qt-function-keys.json'
    reference=ROOT/'runs/native-app-2yezmikt'
    scenario=[('INITIAL_SETUP','7abe6e64a90e14621b6bda99afafe096d805b03383a76b297381f7284e2b98ee','initial_setup',None)]
    for index,(key,screen,pixel) in enumerate(SETUP_STEPS):
        context='setup_on_camera' if index==0 else 'setup_complete' if index==8 else 'initial_setup'
        scenario.append((key,pixel,context,None))
    menu='585eb1f50b747a7cb4d01f07be2fba5ef33f837a3f0e07d3a5e62864f4102326'
    fn='66b5e4a33220590b79dd4efc396845ac8d9613258b407141267499cd6687c59c'
    fn_next='214ad76ee8ea2503c591482db539a1d9a7fa2c0851ab3b74d9cba9e76a65470c'
    scenario += [('MENU',menu,'menu',None),('MENU',None,'shooting_ready',None),
                 ('FN',fn,'fn',None),('RIGHT',None,'fn',None),('DOWN',fn_next,'fn',None),
                 ('ENTER','68cfa0d0df763af9af46cc06ea6f2dd6c19caf08d83009d0838b31d912a06156','fn_notice',None),
                 ('ENTER',fn_next,'fn',None),('FN',None,'shooting_ready',None),
                 ('FN',fn_next,'fn',None),('FN',None,'shooting_ready',None)]
    # 独立查看过的五种布局；只去掉顶部闪烁提示，不用任意哈希变化冒充 DISP 成功。
    scenario += [('DISP',None,'shooting_ready',reference/('research-%04d-UP.png'%i)) for i in range(29,34)]
    scenario += [('PLAYBACK','675aa8d5319f7284958ea7905dd739f7bf66ebc1d9245fe3cc3aaaa365210b5b','playback_empty',None),
                 ('PLAYBACK',None,'shooting_ready',None)]*2
    scenario += [('MENU',menu if i%2==0 else None,'menu' if i%2==0 else 'shooting_ready',None) for i in range(8)]
    # 实际失败路径：离开条目层，MENU 应恢复原厂分类层 0x2d5。
    groups=json.loads((ROOT/'runs/native-app-63lxnv7v/snapshot-08-MENU.json').read_text())['pixel_sha256']
    scenario += [('MENU',menu,'menu',None)]+[('DOWN',None,'menu',None)]*5
    scenario += [('LEFT',groups,'menu_group',None)]
    scenario += [('MENU',None if i%2==0 else groups,'shooting_ready' if i%2==0 else 'menu_group',None) for i in range(8)]
    scenario += [('RIGHT',None,'menu',None)]
    report={'status':'running','operations':[],'errors':[],'boundary':'isolated emulator; original UI; settings in guest RAM'}
    pending=False;stopping=False;clicked=None;start=time.monotonic()

    def save():target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

    def fail(error):
        nonlocal stopping
        report['errors'].append(str(error) or repr(error));report['status']='failed';save()
        stopping=True;window.close()

    def done(_):
        nonlocal pending
        try:
            index=len(report['operations']);key,pixel,context,crop=scenario[index]
            state=window.session.status()
            assert state['input_context']==context,(index,key,state['input_context'],context)
            if pixel:assert state['pixel_sha256']==pixel,(index,key,state['pixel_sha256'],pixel)
            if crop:
                current=next(Path(state['run']).glob('live-%04d-*.png'%(index+1)))
                with Image.open(current) as a,Image.open(crop) as b:
                    assert a.convert('RGBA').crop((0,150,640,440)).tobytes()==b.convert('RGBA').crop((0,150,640,440)).tobytes(),('DISP layout mismatch',index,str(current),str(crop))
            report['operations'].append(dict(index=index,key=key,context=context,pixel_sha256=state['pixel_sha256'],click_to_display_ms=round((time.perf_counter()-clicked)*1000,3),layout_reference=str(crop) if crop else None))
            if key in ('INITIAL_SETUP','FN','DISP','PLAYBACK') or index==9:
                window.grab().save(str(evidence/('qt-key-%02d-%s.png'%(index,key))))
            pending=False;save()
        except Exception as error:
            traceback.print_exc();fail(error)

    def exited(receipt):
        try:
            report['cleanup']=receipt
            assert receipt=={'method':'qmp-quit','exit_code':0}
            assert not report['errors'] and len(report['operations'])==len(scenario)
            spec=importlib.util.spec_from_file_location('cycles',ROOT/'tests/check-menu-cycles.py')
            cycles=importlib.util.module_from_spec(spec);spec.loader.exec_module(cycles)
            rows,_=cycles.saved_frames(Path(report['run']).name,prefix='live-',require_complex=False)
            assert len(rows)==len(scenario)+1
            report['verified_raw_frames']=rows;report['status']='verified'
        except Exception as error:
            traceback.print_exc()
            report['errors'].append(str(error) or repr(error));report['status']='failed'
        save();QTimer.singleShot(100,app.quit)

    def tick():
        nonlocal pending,stopping,clicked
        try:
            if time.monotonic()-start>360:raise TimeoutError('真实按键验收超时')
            if stopping or not window.session:return
            state=window.session.status()
            if state['state'] in ('failed','stopped'):raise RuntimeError(state)
            if pending or state['state']!='running' or not window.sequence:return
            report['run']=state['run'];report['bridge']=str(window.session.bridge)
            index=len(report['operations'])
            if index==len(scenario):
                stopping=True;QTest.mouseClick(window.quit_button,Qt.MouseButton.LeftButton);return
            key=scenario[index][0]
            if index==0:
                assert not any(window.controls.buttons[k].isEnabled() for k in ('FN','DISP','PLAYBACK'))
            if key=='INITIAL_SETUP':button=window.setup_button
            elif key=='C4':
                window.controls.findChild(QTabWidget).setCurrentIndex(1)
                button=window.controls.physical_buttons[key]
                window.controls.findChild(QScrollArea).ensureWidgetVisible(button)
            else:
                window.controls.findChild(QTabWidget).setCurrentIndex(0);button=window.controls.buttons[key]
            assert button.isEnabled(),(index,key,state.get('input_context'))
            clicked=time.perf_counter();pending=True;QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        except Exception as error:
            traceback.print_exc();fail(error)

    window.operation_done.connect(done);window.exit_ready.connect(exited)
    timer=QTimer();timer.setInterval(100);timer.timeout.connect(tick);timer.start();app.exec()
    print(json.dumps({k:v for k,v in report.items() if k!='verified_raw_frames'},ensure_ascii=False,indent=2))
    if report['status']!='verified':raise RuntimeError('Qt 功能按键验收失败')


if __name__=='__main__':main()
