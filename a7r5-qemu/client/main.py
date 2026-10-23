"""开发与冻结程序共用入口；先分派 worker，再加载 Qt。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))


def main():
    if len(sys.argv) >= 3 and sys.argv[1:3] == ['--worker', 'app']:
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        from probe_app import main as worker_main
        worker_main()
        return 0
    import argparse
    parser = argparse.ArgumentParser(description='A7R5 原厂菜单桌面客户端')
    checks=parser.add_mutually_exclusive_group()
    checks.add_argument('--acceptance-smoke', action='store_true', help='固定应用包验收，不接受自定义客体命令')
    checks.add_argument('--acceptance-functions', action='store_true', help='固定 Qt 功能验收，自动完成本次 RAM 内的测试向导')
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from client.window import Window
    application = QApplication(sys.argv)
    application.setApplicationName('A7R5 Emulator')
    application.setOrganizationName('A7R5 Research')
    application.setStyle('Fusion')
    application.setStyleSheet('QWidget{font-size:14px;} QPushButton{padding:6px;}')
    try:
        window = Window()
    except Exception as error:
        QMessageBox.critical(None, 'A7R5 启动失败', str(error))
        return 1
    if args.acceptance_smoke:
        from client.acceptance import attach
        window.acceptance_timer = attach(application, window)
    elif args.acceptance_functions:
        from client.function_acceptance import attach
        window.acceptance_timer=attach(application,window)
    window.show()
    result = application.exec()
    if (args.acceptance_smoke or args.acceptance_functions) and window.acceptance_timer.report['status'] != 'verified':
        return 1
    return result


if __name__ == '__main__':
    sys.exit(main())
