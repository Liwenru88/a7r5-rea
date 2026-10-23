"""显式测试模式：通过真实 Qt 控件验收冻结包，不在日常启动中自动确认。"""
import hashlib
import io
import json
import time
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTabWidget,QScrollArea
from PIL import Image
from app_paths import paths
from initial_setup import SETUP_STEPS


def scenario():
    menu='585eb1f50b747a7cb4d01f07be2fba5ef33f837a3f0e07d3a5e62864f4102326'
    groups='f9e95ac18194f3ca29dc82d2b866f30827b1fe5c44b3f5f289fb7ee3f001fe10'
    fn_next='214ad76ee8ea2503c591482db539a1d9a7fa2c0851ab3b74d9cba9e76a65470c'
    rows=[('INITIAL_SETUP','7abe6e64a90e14621b6bda99afafe096d805b03383a76b297381f7284e2b98ee','initial_setup',None)]
    rows += [(key,pixel,'setup_on_camera' if i==0 else 'setup_complete' if i==8 else 'initial_setup',None) for i,(key,_,pixel) in enumerate(SETUP_STEPS)]
    rows += [('MENU',menu,'menu',None),('MENU',None,'shooting_ready',None),
             ('FN','66b5e4a33220590b79dd4efc396845ac8d9613258b407141267499cd6687c59c','fn',None),
             ('RIGHT',None,'fn',None),('DOWN',fn_next,'fn',None),
             ('ENTER','68cfa0d0df763af9af46cc06ea6f2dd6c19caf08d83009d0838b31d912a06156','fn_notice',None),
             ('ENTER',fn_next,'fn',None),('FN',None,'shooting_ready',None),
             ('FN',fn_next,'fn',None),('FN',None,'shooting_ready',None)]
    # 摘要来自独立查看的原厂帧；只排除顶部闪烁区，不生成替代图像。
    layouts=('d5f0d7617cc3e1265a7a6030cb4212c08f415cb27b0d057e52e172c20d534832',
             '9dc1ac3c881799bd36e3b725ba16b3696ec6b2e6225532fc5814ec08167bbd98',
             'aa1709a37342eb06fcf5374260604878a07b7c08740c87013e037a0b3ad93b24',
             '985cdca0d8d0eb9864b09dbcd3ae92760019b40e16a192afd8dcc6c86e32581e',
             '4dc412b277cf994f03eda8d17f72ba3887951ed60f82c7adbf47482f8b8495ce')
    rows += [('DISP',None,'shooting_ready',value) for value in layouts]
    rows += [('PLAYBACK','675aa8d5319f7284958ea7905dd739f7bf66ebc1d9245fe3cc3aaaa365210b5b','playback_empty',None),('PLAYBACK',None,'shooting_ready',None)]*2
    rows += [('MENU',menu if i%2==0 else None,'menu' if i%2==0 else 'shooting_ready',None) for i in range(8)]
    rows += [('MENU',menu,'menu',None)]+[('DOWN',None,'menu',None)]*5+[('LEFT',groups,'menu_group',None)]
    rows += [('MENU',None if i%2==0 else groups,'shooting_ready' if i%2==0 else 'menu_group',None) for i in range(8)]
    rows += [('RIGHT',None,'menu',None)]
    # 拨轮行为的独立参考来自本轮研究原帧；后拨轮返回时保留页焦点。
    initial='585eb1f50b747a7cb4d01f07be2fba5ef33f837a3f0e07d3a5e62864f4102326'
    item_down='0b330058b5d54c85e7fb6b059c4ea220ddf22c2354ae63b4b8b998766ec540a5'
    page_focus='941f84c01457538fa95b54ea8cc9f12916e6d7cf90c18b0e38c27640b8d7443a'
    prefix=[('FRONT_DIAL_RIGHT','9c18bee2488d3465fee2291cb39a586766e224aa5189f89b7825bbfd89d6eb83','menu',None),
            ('FRONT_DIAL_LEFT',initial,'menu',None)]
    for dial in ('REAR_DIAL_L','REAR_DIAL_R'):
        prefix += [(dial+'_RIGHT','68d31228f1b8ee70302981d82cb9cc96ffbd1c6d9a440c6ad429758608d8c425','menu_page',None),
                   (dial+'_LEFT',page_focus,'menu_page',None),
                   ('CONTROL_WHEEL_RIGHT',item_down,'menu',None),('CONTROL_WHEEL_LEFT',initial,'menu',None)]
    prefix += [('CONTROL_WHEEL_RIGHT',item_down,'menu',None),('CONTROL_WHEEL_LEFT',initial,'menu',None)]
    # 拨轮参考帧来自首次设置完成后的状态，不能与未完成向导时的 Main 菜单字段混用。
    rows += [('UP',None,'menu',None)]*5
    rows += prefix
    rows += [('JOYSTICK_DOWN',item_down,'menu',None),('JOYSTICK_UP',initial,'menu',None),
             ('JOYSTICK_LEFT','f75021a0d8129bce471bc51911568ca63fdb278d83506949e6009a9244b5da20','menu_group',None),
             ('JOYSTICK_RIGHT',initial,'menu',None)]
    rows += [('DOWN',None,'menu',None)]*5
    rows += [('JOYSTICK_CENTER','1f1e6f4d09729d71079ce9d7090b58cd8a22b76d3e0531ec4a12a1f3896042ce','menu_option',None),
             ('JOYSTICK_UP','3150062e9670e30cbee9cfabe116bed7d6b7cb2ce2ddbe052571703e5ed6a540','menu_option',None),
             ('JOYSTICK_CENTER','ead51d635757a1de112eae875d489f8f7e2e9577db7b1a70ee7963a59128ed35','menu',None),
             ('ENTER','84d7042cd58ee67c4585e7d69eee7e6ddf027600ee3717e6395a5b5a339ae757','menu_option',None),
             ('JOYSTICK_DOWN','1d7c0955f09d048dee4893c04ac31b0fda7d2562494d3ac85fae883a781ecfd7','menu_option',None),
             ('ENTER','981d29e45035f99a31b74e63c68011e84824dd48ef0288b98d05d7f6234dfa9a','menu',None)]
    # 当前选项的原厂帧与读回结果均来自独立 CLI 研究，避免自设成功像素。
    awb='bfda5210434c850d8a8c8709ad0a9b2512f79cb32fcb3d37416c69c1729896a2'
    daylight='eb5cc88c5c76bdad1cdc991f8837325fa604afa970323b010c399d4c6006bc32'
    wide='e1a690219ae754d95bc27c2d3d80bcec22c5593af16867605e5fab511e63b2b8'
    zone='6eb6c970604039c39edc86b714bd467346e45cb85089c4ad7cad350f657fe11b'
    rows += [('MENU',None,'shooting_ready',None)]
    # 自动模式的限制提示可返回；不将提示本身当作设置成功。
    rows += [('C4',None,'shooting_ready','0d5b3c7fdda1fdbc0b45c25b060042920e360d6864ee2cef9e92b678eae23b8d'),
             # 触摸操作关闭时原厂不绘制 OK 触摸按钮边框；弹层主体逐像素等于独立参考。
             ('C1','11f104fddc522a90402f6b908151d785014174a70fcc0e4e8bc3835d8ddd4bc1','custom_notice',None),
             ('ENTER',None,'shooting_ready',None),
             ('C4',None,'shooting_ready','2bdb26ea9b32cc3de7c269f66912fb780292a33e010e12704c5c6b8420f7fa51'),
             ('C2','d2511a3e8ff0e004f521248a8ae5f987c4f7e7f10c0fe4eabcf7162a5a37c246','custom_notice',None),
             ('ENTER',None,'shooting_ready',None)]
    rows += [('MODE_'+mode,None,'shooting_ready',None) for mode in ('P','A','S','M','AUTO','P')]
    for control,old,new in (('C1',awb,daylight),('C2',wide,zone)):
        rows += [(control,old,'custom_setting',None),('DOWN',new,'custom_setting',None),
                 ('ENTER',None,'shooting_ready',None),(control,new,'custom_setting',None),
                 ('UP',old,'custom_setting',None),('ENTER',None,'shooting_ready',None),
                 (control,old,'custom_setting',None),('MENU',None,'shooting_ready',None)]
    rows += [('C3','d138d57c1591458fb62fcbbcfdd71a59525cfdc85500344ddd032cd516b2a81b','custom_setting',None)]
    rows += [('DOWN',None,'custom_setting',None)]*4
    mf='336650de1ecbc820d0be4a87b7f6e236cedf7259a417ab231f04aa03a06114c2'
    rows += [('ENTER','17adf7e45c83a9120ff664b45362d5a4edb7f03c553297e3fa0cd7dcf4756be8','custom_setting_notice',None),
             ('ENTER',mf,'custom_setting',None),('MENU',None,'shooting_ready',None),
             ('MODE_AUTO',None,'shooting_ready',None)]
    rows += [('MENU',None,'menu',None),('MENU',None,'shooting_ready',None)]*2
    return rows


def attach(application,window):
    rows=scenario();data=paths().prepare().data;target=data/'package-controls-expanded.json'
    report={'status':'running','mode':'fixed-Qt-function-acceptance','operations':[],'errors':[]}
    pending=False;stopping=False;clicked=None;start=time.monotonic()
    timer=QTimer(window);timer.setInterval(100);timer.report=report

    def save():target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

    def fail(error):
        nonlocal stopping
        stopping=True;report['errors'].append(str(error) or repr(error));save();window.close()

    def done(_):
        nonlocal pending
        if stopping:return
        try:
            index=len(report['operations']);key,pixel,context,layout=rows[index];state=window.session.status()
            if state['input_context']!=context or (pixel and state['pixel_sha256']!=pixel):
                raise AssertionError((index,key,state['input_context'],state['pixel_sha256']))
            if key.startswith('MODE_') and state.get('shooting_mode')!=key[5:]:
                raise AssertionError(('模式未实际显示',key,state.get('shooting_mode')))
            if layout:
                frame=window.session.frame()
                if not frame or frame[0]['sequence']!=state['sequence']:raise AssertionError('帧发布未完成')
                with Image.open(io.BytesIO(frame[1])) as image:
                    digest=hashlib.sha256(image.convert('RGBA').crop((0,150,640,440)).tobytes()).hexdigest()
                if digest!=layout:raise AssertionError(('DISP 布局不符',index,digest))
            report['operations'].append(dict(index=index,key=key,context=context,pixel_sha256=state['pixel_sha256'],layout_sha256=layout,click_to_display_ms=round((time.perf_counter()-clicked)*1000,3)))
            if key in ('INITIAL_SETUP','FN','DISP','PLAYBACK','C1','C2','C3') or key.startswith('MODE_'):
                window.grab().save(str(data/('expanded-control-%03d-%s.png'%(index,key))))
            pending=False;save()
        except Exception as error:fail(error)

    def tick():
        nonlocal pending,stopping,clicked
        try:
            if time.monotonic()-start>360:raise TimeoutError('冻结包功能验收超时')
            if stopping or not window.session:return
            state=window.session.status()
            if state['state'] in ('failed','stopped'):raise RuntimeError(state)
            if pending or state['state']!='running' or not window.sequence:return
            report.update(run=state['run'],bridge=str(window.session.bridge))
            index=len(report['operations'])
            if index==len(rows):
                stopping=True;QTest.mouseClick(window.quit_button,Qt.MouseButton.LeftButton);return
            key=rows[index][0]
            if index==0 and any(window.controls.buttons[k].isEnabled() for k in ('FN','DISP','PLAYBACK')):
                raise AssertionError('尚未完成首次设置却启用功能键')
            if key=='INITIAL_SETUP':button=window.setup_button
            elif key.startswith('MODE_'):
                window.controls.findChild(QTabWidget).setCurrentIndex(0)
                selector=window.controls.mode_select
                selector.setCurrentIndex(selector.findData(key[5:]))
                button=window.controls.mode_button
            elif key not in window.controls.buttons and key in window.controls.action_buttons:
                window.controls.findChild(QTabWidget).setCurrentIndex(1)
                button=window.controls.action_buttons[key]
                window.controls.findChild(QScrollArea).ensureWidgetVisible(button)
            elif key=='C4':
                window.controls.findChild(QTabWidget).setCurrentIndex(1);button=window.controls.physical_buttons[key]
                window.controls.findChild(QScrollArea).ensureWidgetVisible(button)
            else:
                window.controls.findChild(QTabWidget).setCurrentIndex(0);button=window.controls.buttons[key]
            if not button.isEnabled():raise AssertionError(('按钮禁用',index,key))
            clicked=time.perf_counter();pending=True;QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        except Exception as error:fail(error)

    def exited(receipt):
        report['cleanup']=receipt
        report['status']='verified' if not report['errors'] and len(report['operations'])==len(rows) and receipt=={'method':'qmp-quit','exit_code':0} else 'failed'
        save();QTimer.singleShot(100,application.quit)

    window.operation_done.connect(done);window.exit_ready.connect(exited)
    timer.timeout.connect(tick);timer.start();save();return timer
