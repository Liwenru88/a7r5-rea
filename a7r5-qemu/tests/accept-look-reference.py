"""真实 Qt 平台上的参考窗口、键盘/复选框切换与正常关闭验收。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

LAB=Path(__file__).resolve().parents[1];sys.path.insert(0,str(LAB/'tools'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from look_reference_ui import ReferenceWindow
from look_live import CAMERA_LOOKS,LiveEngine
from PIL import Image,ImageCms


def wait(app,window):
    deadline=time.monotonic()+40
    while window.displayed_serial!=window.serial:
        app.processEvents();time.sleep(.01)
        if time.monotonic()>deadline:raise RuntimeError('参考窗口未完成本次渲染：'+window.status.text())


def main():
    p=argparse.ArgumentParser();p.add_argument('--parameters',required=True,type=Path)
    p.add_argument('--reference-materials',type=Path)
    p.add_argument('--camera-jpeg',type=Path);a=p.parse_args()
    out=Path(tempfile.mkdtemp(prefix='look-qt-accept-',dir=LAB/'runs'))
    app=QApplication([]);w=ReferenceWindow(a.parameters);results=[]
    record={'platform':app.platformName(),'scope':'Qt reference window only; not native camera menu',
            'camera_io':False,'ISP_pixels_verified':False}
    try:
        w.show();w.raise_();w.activateWindow();wait(app,w)
        for i,look in enumerate(w.data.looks):
            if i:
                w.look.setFocus();QTest.keyClick(w.look,Qt.Key_Down)
            wait(app,w);assert w.look.currentText()==look,(i,look,w.look.currentText(),w.look.isEnabled())
            audit=json.loads(w.details.toPlainText());assert audit['look']==look
            assert audit['cc1_native_application_verified'] is True
            if look in ('BW','SE'):
                assert audit['cc1_applied_coefficients']==[0]*8
                assert all(r==g==b for r,g,b in w.input.get_flattened_data()) is False
                native_ref=Image.open(Path(audit['selection_receipt']).parent/'reference.png')
                assert all(r==g==b for r,g,b in native_ref.get_flattened_data())
            image=w.target.pixmap().toImage();payload=bytes(image.bits())
            results.append({'look':look,'key':'Down' if i else 'initial','display_sha256':hashlib.sha256(payload).hexdigest()})
            results[-1].update(request=audit['request'],AP_run=audit['AP_run'],CP_run=audit['CP_run'],
                native_ms=audit['native_parameter_ms'],render_ms=audit['rendering_ms'],
                reference_pixels_sha256=audit['output_pixels_sha256'],matrix_source=audit['matrix_source'])
        assert len({r['display_sha256'] for r in results[12:]})==6
        assert len({r['request'] for r in results})==18
        reference=LiveEngine(a.reference_materials) if a.reference_materials else None
        if reference:
            reference_rows=[]
            for row in results:
                if row['look'] not in CAMERA_LOOKS:continue
                _,old=reference.render(w.input,row['look'],fixed=True)
                assert old['output_pixels_sha256']==row['reference_pixels_sha256']
                reference_rows.append({'look':row['look'],'receipt':old['selection_receipt']})
            record['unchanged_original_looks_equal_settings_path']=reference_rows
        w.look.setCurrentText('FL2');wait(app,w)
        assert w.grab().save(str(out/'matrix-diagnostic-window.png'))
        inline='cp-matrix-source.bin' in w.data.files
        initial_fixed=w.fixed.isChecked()
        toggle_image=w.target.pixmap().toImage();before_toggle=bytes(toggle_image.bits())
        QTest.mouseClick(w.fixed,Qt.LeftButton);wait(app,w)
        assert json.loads(w.details.toPlainText())['matrix_fixed_in_fixture'] is not initial_fixed
        if inline:
            assert initial_fixed is False
            assert json.loads(w.details.toPlainText())['matrix_source']=='CP-embedded'
            toggle_image=w.target.pixmap().toImage()
            assert bytes(toggle_image.bits())==before_toggle
            record['embedded_matrix_unchanged_when_settings_fixed']=True
        QTest.mouseClick(w.fixed,Qt.LeftButton);wait(app,w)
        QTest.mouseClick(w.gamma,Qt.LeftButton);wait(app,w)
        assert json.loads(w.details.toPlainText())['Gamma_curve_applied'] is False
        QTest.mouseClick(w.gamma,Qt.LeftButton);wait(app,w)
        assert json.loads(w.details.toPlainText())['Gamma_curve_applied'] is True
        w.endpoint.setCurrentIndex(1);w.slot.setValue(15);w.level.setValue(1);wait(app,w)
        audit=json.loads(w.details.toPlainText())
        assert (audit['light_endpoint'],audit['matrix_slot'],audit['level'])==(1,15,1)
        # 返回默认 ST，截图始终包含非原厂像素的边界提示。
        w.look.setCurrentText('ST');w.endpoint.setCurrentIndex(0);w.slot.setValue(-1);w.level.setValue(8);wait(app,w)
        second_ST=json.loads(w.details.toPlainText())
        assert second_ST['request']!=results[0]['request'] and second_ST['CP_run']!=results[0]['CP_run']
        photo=out/'reference.jpg';exif=Image.Exif();exif[274]=6
        Image.new('RGB',(960,640),(123,65,40)).save(photo,exif=exif,
            icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        before=hashlib.sha256(photo.read_bytes()).hexdigest()
        with patch('look_reference_ui.QFileDialog.getOpenFileName',return_value=(str(photo),'参考图片')):
            QTest.mouseClick(w.open_image,Qt.LeftButton)
        wait(app,w);audit=json.loads(w.details.toPlainText())
        assert tuple(audit['input']['preview_dimensions'])==(171,256)
        assert before==hashlib.sha256(photo.read_bytes()).hexdigest()
        assert w.grab().save(str(out/'photo-selected.png'))
        if a.camera_jpeg:
            photo=a.camera_jpeg;before=hashlib.sha256(photo.read_bytes()).hexdigest()
            with patch('look_reference_ui.QFileDialog.getOpenFileName',return_value=(str(photo),'参考图片')):
                QTest.mouseClick(w.open_image,Qt.LeftButton)
            wait(app,w);audit=json.loads(w.details.toPlainText())
            assert audit['input']['source_sha256']==before
            assert audit['input']['container_format']=='MPO' and audit['input']['selected_frame']==0
            assert tuple(audit['input']['original_dimensions'])==(9504,6336)
            assert tuple(audit['input']['preview_dimensions'])==(384,256)
            assert w.grab().save(str(out/'camera-jpeg-ST.png'))
            photo_parity=[]
            if reference:
                _,old=reference.render(w.input,'ST',fixed=True)
                assert old['output_pixels_sha256']==audit['output_pixels_sha256']
                photo_parity.append({'look':'ST','receipt':old['selection_receipt']})
            photo_looks=('FL2','FL3','BW','SE')+(('Astia','Classic Neg.') if 'Astia' in w.data.names else ())
            for look in photo_looks:
                w.look.setCurrentText(look);wait(app,w)
                assert w.grab().save(str(out/('camera-jpeg-'+look+'.png')))
                if reference and look in CAMERA_LOOKS:
                    _,old=reference.render(w.input,look,fixed=True)
                    current=json.loads(w.details.toPlainText())
                    assert old['output_pixels_sha256']==current['output_pixels_sha256']
                    photo_parity.append({'look':look,'receipt':old['selection_receipt']})
            assert before==hashlib.sha256(photo.read_bytes()).hexdigest()
            record['camera_JPEG_verified']={'source_sha256':before,'source_modified':False,
                'primary_frame_selected':True,'native_parameter_and_preview_looks':['ST',*photo_looks]}
            if reference:record['camera_JPEG_equal_settings_path']=photo_parity
        # 错误输入必须清除上一次显示，不能伪装成新图或继续拿缓存渲染。
        bad=out/'corrupt.png';bad.write_bytes(b'invalid');w.select_image(bad)
        deadline=time.monotonic()+5
        while not w.history or w.history[-1]['serial']!=w.serial:
            app.processEvents();time.sleep(.01)
            assert time.monotonic()<deadline
        assert w.history[-1]['status']=='failed' and w.target.pixmap().isNull()
        QTest.mouseClick(w.reset_image,Qt.LeftButton);wait(app,w)
        assert w.grab().save(str(out/'window.png'))
        # 已接受的快速切换逐个执行；关闭请求等待这批自己的工作正常完成。
        w.look.setCurrentText('ST');wait(app,w)
        start=len(w.history)
        w.look.setCurrentText('FL2');w.look.setCurrentText('FL3');w.look.setCurrentText('ST')
        app.processEvents();w.close()
        deadline=time.monotonic()+40
        while w.isVisible():
            app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
        assert len(w.history)==start+3 and all(r['status']=='passed' for r in w.history[start:])
        assert w.executor._shutdown
        record.update(status='passed',actions=results,checkboxes_verified=True,
            parameter_controls_verified=True,photo_picker_verified=True,corrupt_photo_clears_display=True,
            input_file_sha256_unchanged=True,accepted_switches_all_executed=True,
            repeat_ST_has_new_native_runs=True,history=w.history,
            normal_close=True,render_thread_shutdown=True)
    except Exception as error:
        record.update(status='failed',error=repr(error),actions=results,history=w.history,
            actual_look=w.look.currentText(),current_serial=w.serial,displayed_serial=w.displayed_serial);raise
    finally:
        if w.isVisible():w.close()
        (out/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        print(out,flush=True)


if __name__=='__main__':main()
