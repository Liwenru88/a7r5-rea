"""直接显示本次客体帧的 Qt 窗口；没有 HTTP 或网页绘制层。"""
import json
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QMainWindow, QWidget, QLabel, QHBoxLayout, QVBoxLayout,
                               QPushButton, QSizePolicy)
from client.controller import Controller
from client.control_panel import ControlPanel
from platform_backend import capability
from control_actions import request_for_action


class Window(QMainWindow):
    operation_done = Signal(object)
    frame_ready = Signal(object)
    exit_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('A7R5 原厂菜单 · 原生模拟器')
        self.resize(1080, 740)
        self.session = None
        self.busy = False
        self.closing = False
        self.allow_close = False
        self.sequence = 0
        self.pixmap = QPixmap()
        self.receipt = None
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        heading = QLabel('Sony α7R V · 4.00')
        heading.setStyleSheet('font-size:24px;font-weight:600;padding:8px')
        outer.addWidget(heading)
        outer.addWidget(QLabel('原厂应用实时快照 · 640 × 480 · 设置仅保存在本次客体 RAM'))
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        self.screen = QLabel('正在启动原厂系统…')
        self.screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screen.setMinimumSize(480, 360)
        self.screen.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.screen.setStyleSheet('background:#000;color:#c8d0dc;border:1px solid #454a52')
        body.addWidget(self.screen, 1)
        side = QVBoxLayout()
        body.addLayout(side)
        self.controls = ControlPanel()
        side.addWidget(self.controls)
        self.setup_button=QPushButton('首次设置（启用功能键）…')
        self.setup_button.setStyleSheet('font-weight:600;padding:8px')
        self.setup_button.setEnabled(False)
        self.setup_button.setToolTip('从初始菜单打开原厂说明；由你确认并选择在相机上设置。只影响本次模拟器 RAM。')
        self.setup_button.clicked.connect(self.start_initial_setup)
        side.addWidget(self.setup_button)
        side.addStretch()
        self.quit_button = QPushButton('退出本次模拟器')
        self.quit_button.setMinimumHeight(42)
        self.quit_button.clicked.connect(self.close)
        side.addWidget(self.quit_button)
        self.logs_button = QPushButton('打开本次日志')
        self.logs_button.setEnabled(False)
        self.logs_button.clicked.connect(self.open_logs)
        side.addWidget(self.logs_button)
        self.state_label = QLabel('启动中：等待原厂应用与绘图初始化…')
        self.state_label.setWordWrap(True)
        outer.addWidget(self.state_label)
        limits = QLabel('Fn、DISP、C1/C2/C3 与空介质回放需先完成原厂首次设置。拨轮仅开放已验证的菜单操作；拍摄、录像及照片回放尚未实现。')
        limits.setWordWrap(True)
        outer.addWidget(limits)
        self.controls.set_available(False)
        self.controls.activated.connect(self.send_key)
        self.shortcuts = []
        for key, sequence in (('UP', 'Up'), ('DOWN', 'Down'), ('LEFT', 'Left'),
                              ('RIGHT', 'Right'), ('ENTER', 'Return'), ('MENU', 'Escape')):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda key=key: self.send_key(key))
            self.shortcuts.append(shortcut)
        self.controller = Controller(self)
        worker = self.controller.worker
        worker.ready.connect(self.started)
        worker.finished.connect(self.finished)
        worker.failed.connect(self.failed)
        worker.closed.connect(self.closed)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)
        support = capability()
        if support['supported']:
            self.controller.start()
            self.timer.start()
        else:
            self.failed(support['reason'])

    def started(self, session):
        self.session = session
        self.logs_button.setEnabled(True)
        if self.closing:
            session.cancel()

    def poll(self):
        if not self.session or self.closing:
            return
        try:
            state = self.session.status()
            ready = state['state'] == 'running' and not self.busy
            self.controls.set_available(ready, state.get('input_context', 'unknown'),state.get('shooting_mode'))
            self.setup_button.setEnabled(ready and state.get('initial_setup_available',False))
            self.setup_button.setText('首次设置已完成（仅本次）' if state.get('privacy_accepted') else '首次设置（启用功能键）…')
            if state['state'] == 'failed':
                self.failed(state.get('error', '本次运行失败，请查看日志'))
                return
            if ready:
                hints={'initial_setup':'原厂首次设置：确认说明，保留测试区域与日期即可；设置只在本次 RAM。',
                       'setup_on_camera':'请按 C4“在相机上设置”，无需连接手机。',
                       'setup_complete':'首次设置已完成。按 MENU 返回菜单，再按 MENU 到拍摄信息页。'}
                hints.update(shooting_ready='可使用 Fn、DISP、C1/C2/C3、回放及虚拟模式拨盘；黑色背景没有传感器取景。',
                             fn='原厂 Fn 面板 · 方向键选择，确认打开，Fn 或 MENU 返回。',
                             playback_empty='原厂空介质回放提示 · 再按回放返回；照片浏览尚未实现。',
                             custom_notice='原厂设置限制提示 · 按确认返回；当前模式或设备状态不支持该设置。',
                             custom_setting='原厂设置面板 · 上下选择，确认应用，MENU 取消；镜头相关选项可能被原厂拒绝。',
                             custom_setting_notice='原厂镜头限制提示 · 按确认返回选择页，再按 MENU 取消。',
                             menu_page='原厂菜单页选择焦点 · 控制轮恢复条目选择；后拨轮可继续切页。')
                hint=hints.get(state.get('input_context'),'菜单可操作 · 每次输入后校验真实帧 · 空闲时暂停客体')
                if not state.get('privacy_accepted') and state.get('input_context') in ('menu','menu_group','menu_page'):
                    hint='功能键需先完成首次设置。请回到初始 My Menu 的 Add Item，再点“首次设置（启用功能键）…”。'
                self.state_label.setText(hint)
            frame = self.session.frame()
            if frame and frame[0]['sequence'] != self.sequence:
                state, png = frame
                picture = QPixmap()
                if not picture.loadFromData(png, 'PNG'):
                    raise ValueError('帧 PNG 无法解码')
                self.pixmap = picture
                self.sequence = state['sequence']
                self.render()
                self.frame_ready.emit(state)
        except Exception as error:
            self.failed(str(error))

    def render(self):
        if not self.pixmap.isNull():
            self.screen.setPixmap(self.pixmap.scaled(self.screen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render()

    def send_key(self, key):
        if self.closing or self.busy or not self.session or self.session.status()['state'] != 'running':
            return
        self.busy = True
        self.controls.set_available(False)
        self.setup_button.setEnabled(False)
        self.state_label.setText('正在处理按键并校验画面…')
        self.controller.request.emit(request_for_action(key))

    def start_initial_setup(self):
        if self.closing or self.busy or not self.session or not self.session.status().get('initial_setup_available'):
            return
        self.busy=True
        self.controls.set_available(False)
        self.setup_button.setEnabled(False)
        self.controller.request.emit({'action':'initial_setup','key':None})

    def finished(self, result):
        self.busy = False
        self.poll()
        self.operation_done.emit(result)

    def failed(self, message):
        self.busy = False
        self.controls.set_available(False)
        self.setup_button.setEnabled(False)
        self.state_label.setText('已停止：' + message)
        self.timer.stop()
        if self.session:
            self.session.cancel()

    def open_logs(self):
        if self.session:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.bridge)))

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        self.controls.set_available(False)
        self.setup_button.setEnabled(False)
        self.quit_button.setEnabled(False)
        self.state_label.setText('正在退出：等待本次工作进程和 QMP 退出回执…')
        if not self.controller.thread.isRunning():
            self.closed({'method': 'not-started', 'exit_code': None})
        else:
            self.controller.stop()

    def closed(self, receipt):
        self.receipt = receipt
        self.controller.thread.quit()
        self.controller.thread.wait(2000)
        self.exit_ready.emit(receipt)
        if receipt.get('error'):
            self.state_label.setText('退出未确认：' + receipt['error'] + '。请查看日志；关闭窗口不会重试。')
            self.allow_close = True
            self.quit_button.setEnabled(True)
            self.quit_button.setText('关闭窗口（保留未确认记录）')
            return
        self.allow_close = True
        self.close()
