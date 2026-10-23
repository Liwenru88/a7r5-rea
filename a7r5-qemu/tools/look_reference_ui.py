"""独立 Qt 参考窗口；不伪装相机菜单，不运行设备或默认模拟器。"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QImage,QPixmap,QColorSpace
from PySide6.QtWidgets import (QApplication,QCheckBox,QComboBox,QHBoxLayout,QLabel,
    QFileDialog,QMainWindow,QPlainTextEdit,QPushButton,QSpinBox,QVBoxLayout,QWidget)

from look_reference import fixture
from look_live import LiveEngine,LOOKS,read_image,BOUNDARY
from look_materials import regular


class ReferenceWindow(QMainWindow):
    def __init__(self, parameters):
        super().__init__();self.setWindowTitle('A7R5 创意外观 · 软件参考预览')
        path=Path(parameters)
        if path.is_file():path=Path(json.loads(regular(path,2_000_000))['materials'])
        self.data=LiveEngine(path);self.input=fixture();self.input_path=None
        self.input_audit={'source':'deterministic virtual sRGB chart'}
        self.executor=ThreadPoolExecutor(max_workers=1)
        self.future=None;self.serial=0;self.displayed_serial=-1;self.pending=deque()
        self.history=[];self.closing=False
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        inline='cp-matrix-source.bin' in self.data.files
        warning=QLabel(BOUNDARY+'\n每次切换均执行 AP／CP、CC1系数读取和应用；Gamma横轴由原厂指令生成。\nCC1像素模型及矩阵线性RGB／HSV分区仍是参考；BW已接入零增益去色，SE仅单色基底，棕褐染色待验证。'+
            ('\nFL2／FL3：CP内嵌矩阵离线候选，默认设置未修复；完整启动、实机加载和成片效果未验证。' if inline else ''))
        warning.setStyleSheet('color:#b65b00;font-weight:bold');layout.addWidget(warning)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.open_image=QPushButton('选择参考图片…');self.open_image.clicked.connect(self.choose_image);controls.addWidget(self.open_image)
        self.reset_image=QPushButton('虚拟测试图');self.reset_image.clicked.connect(self.use_fixture);controls.addWidget(self.reset_image)
        self.look=QComboBox();self.look.addItems(self.data.looks);controls.addWidget(self.look)
        self.fixed=QCheckBox('设置矩阵修复对照' if inline else '模拟矩阵修复');self.fixed.setChecked(not inline);controls.addWidget(self.fixed)
        if inline:self.fixed.setToolTip('只改变模拟设置副本；内嵌FL2／FL3应在开关前后保持相同参数。')
        self.endpoint=QComboBox();self.endpoint.addItems(['光源端点 B','光源端点 A1','光源端点 A2']);controls.addWidget(self.endpoint)
        self.slot=QSpinBox();self.slot.setRange(-1,15);self.slot.setValue(-1);self.slot.setSpecialValueText('自动16分区（参考）');self.slot.setPrefix('矩阵子槽 ');controls.addWidget(self.slot)
        self.level=QSpinBox();self.level.setRange(1,8);self.level.setValue(8);self.level.setPrefix('LUT等级 ');controls.addWidget(self.level)
        self.gamma=QCheckBox('应用相对 Gamma（原厂分段横轴）');self.gamma.setChecked(True);controls.addWidget(self.gamma)
        pictures=QHBoxLayout();layout.addLayout(pictures)
        self.source=QLabel();self.source.setAlignment(Qt.AlignCenter);self.target=QLabel();self.target.setAlignment(Qt.AlignCenter)
        for label in (self.source,self.target):label.setMinimumSize(420,300);pictures.addWidget(label)
        self.source.setPixmap(self.pixmap(self.input))
        self.input_label=QLabel('输入：虚拟 ST-like sRGB 色卡');layout.addWidget(self.input_label)
        self.status=QLabel('准备参考预览');layout.addWidget(self.status)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(210);layout.addWidget(self.details)
        self.close_button=QPushButton('关闭参考预览');self.close_button.clicked.connect(self.close);layout.addWidget(self.close_button)
        for control in (self.look,self.endpoint):control.currentIndexChanged.connect(self.request)
        for control in (self.fixed,self.gamma):control.toggled.connect(self.request)
        for control in (self.slot,self.level):control.valueChanged.connect(self.request)
        self.timer=QTimer(self);self.timer.setInterval(30);self.timer.timeout.connect(self.poll);self.timer.start()
        self.resize(1100,720);self.request()

    @staticmethod
    def pixmap(image):
        q=QImage(image.tobytes(),image.width,image.height,image.width*3,QImage.Format_RGB888).copy()
        q.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        return QPixmap.fromImage(q).scaled(480,320,Qt.KeepAspectRatio,Qt.SmoothTransformation)

    def request(self,*_):
        if self.closing:return
        self.serial+=1
        look=self.look.currentText();options=dict(fixed=self.fixed.isChecked(),endpoint=self.endpoint.currentIndex(),
            slot=self.slot.value(),level=self.level.value(),gamma_diagnostic=self.gamma.isChecked())
        self.pending.append((self.serial,look,options,self.input_path))
        self.target.clear();self.details.clear()
        self.status.setText('排队执行本次 AP→CP 参数窗口，不复用上次结果；待处理 '+str(len(self.pending)))
        self.update_controls()

    def update_controls(self):
        # 有界交互：每次已接受的选择都执行；队列满后禁用控件，避免静默合并或跳过。
        enabled=not self.closing and len(self.pending)<4
        for control in (self.look,self.fixed,self.endpoint,self.slot,self.level,self.gamma,self.open_image,self.reset_image):
            control.setEnabled(enabled)

    def choose_image(self):
        name,_=QFileDialog.getOpenFileName(self,'选择已渲染参考图片（不改源文件）','',
            '参考图片 (*.jpg *.JPG *.jpeg *.JPEG *.png *.PNG *.tif *.TIF *.tiff *.TIFF *.webp *.WEBP)')
        if name:self.select_image(name)

    def select_image(self,name):
        self.input_path=str(Path(name).absolute());self.request()

    def use_fixture(self):
        self.input_path=None;self.request()

    def work(self,look,options,path):
        image,audit=read_image(path) if path else (fixture(),{'source':'deterministic virtual sRGB chart'})
        result=self.data.render(image,look,input_audit=audit,**options)
        return image,audit,result

    def poll(self):
        if self.future is not None:
            serial,future=self.future
            if not future.done():return
            self.future=None
            try:source,input_audit,result=future.result()
            except Exception as error:
                self.history.append({'serial':serial,'status':'failed','error':str(error)})
                if serial==self.serial:
                    self.target.clear();self.source.clear();self.details.clear();self.status.setText('参考渲染停止：'+str(error))
                    self.input_label.setText('输入失败：未显示旧图片结果')
            else:
                self.history.append({'serial':serial,'status':'passed','receipt':result[1]['selection_receipt']})
                if serial==self.serial:
                    self.input=source;self.input_audit=input_audit
                    self.source.setPixmap(self.pixmap(source))
                    self.input_label.setText('输入：'+input_audit.get('source_name','虚拟 ST-like sRGB 色卡')+
                        '；'+input_audit.get('color_management','确定性测试图')+'；缩略 '+str(source.size))
                    self.display(serial,result)
        if self.pending:
            serial,look,options,path=self.pending.popleft()
            self.future=(serial,self.executor.submit(self.work,look,options,path))
        self.update_controls()
        if self.closing and self.future is None and not self.pending:
            self.executor.shutdown(wait=True);self.timer.stop();self.close()

    def display(self,serial,result):
        image,audit=result;self.target.setPixmap(self.pixmap(image));self.details.setPlainText(json.dumps(audit,ensure_ascii=False,indent=2))
        suffix='原厂单色控制／参考去色已应用；棕褐染色待验证' if audit['monochrome_flags'][0] else '原厂零增益／BW参考去色已应用' if audit['monochrome_flags'][1] else '原生CC1参数／软件参考像素'
        source=' · CP联合参数' if audit['matrix_source']=='CP-joint' else ' · CP内嵌矩阵' if audit['matrix_source']=='CP-embedded' else ' · 设置矩阵'
        self.status.setText(audit['look']+source+' · '+suffix+' · AP/CP '+str(audit['native_parameter_ms'])+' ms / 渲染 '+str(audit['rendering_ms'])+' ms')
        self.displayed_serial=serial

    def closeEvent(self,event):
        if self.future is not None or self.pending:
            self.closing=True;self.update_controls();self.close_button.setEnabled(False)
            self.status.setText('正在完成已接受的参数窗口并正常退出…');event.ignore();return
        self.timer.stop();self.executor.shutdown(wait=True,cancel_futures=True)
        event.accept()


def launch(parameters):
    app=QApplication.instance() or QApplication(sys.argv[:1]);window=ReferenceWindow(parameters)
    window.show();return app.exec()
