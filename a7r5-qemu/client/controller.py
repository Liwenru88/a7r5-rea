"""阻塞的客体操作只在本会话工作线程执行。"""
from PySide6.QtCore import QObject, QThread, Signal, Slot
from emu_session import EmulatorSession


class Worker(QObject):
    ready = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    closed = Signal(object)

    def __init__(self):
        super().__init__()
        self.session = None

    @Slot()
    def start(self):
        try:
            self.session = EmulatorSession()
            self.ready.emit(self.session)
        except Exception as error:
            self.failed.emit(str(error))

    @Slot(object)
    def command(self, request):
        try:
            self.finished.emit(self.session.command(request))
        except Exception as error:
            self.failed.emit(str(error))

    @Slot()
    def close(self):
        try:
            receipt = self.session.close() if self.session else {'method': 'not-started', 'exit_code': None}
            self.closed.emit(receipt)
        except Exception as error:
            self.closed.emit({'error': str(error), 'confirmed': False})


class Controller(QObject):
    request = Signal(object)
    closing = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = QThread(self)
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.request.connect(self.worker.command)
        self.closing.connect(self.worker.close)

    def start(self):
        self.thread.start()

    def stop(self):
        # 取消标记无需等待线程上的按键完成，不发送第二个客体命令。
        if self.worker.session:
            self.worker.session.cancel()
        self.closing.emit()
