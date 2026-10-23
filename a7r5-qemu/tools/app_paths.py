"""分离只读程序资源与本用户的运行证据。"""
from dataclasses import dataclass
from pathlib import Path
import os
import sys


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    data: Path

    @property
    def runs(self):
        return self.data / 'runs'

    def prepare(self):
        for path in (self.data, self.runs):
            if path.is_symlink():
                raise ValueError('运行目录不能是符号链接')
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.resolve() != path.absolute():
                raise ValueError('运行目录包含符号链接')
        return self


def paths():
    bundled = getattr(sys, 'frozen', False) or '__compiled__' in globals()
    candidate = Path(sys.executable).resolve().parent.parent / 'Resources' / 'a7r5'
    if bundled or candidate.is_dir():
        resources = candidate
        if sys.platform == 'darwin':
            data = Path.home() / 'Library/Application Support/A7R5 Emulator'
        elif sys.platform == 'win32':
            data = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'A7R5 Emulator'
        else:
            data = Path.home() / '.local/share/a7r5-emulator'
    else:
        resources = Path(__file__).resolve().parent.parent
        data = resources
    return AppPaths(resources, data)


def shared_lock():
    """源码入口与应用包共用同一个用户锁，避免双开不同数据目录的 VM。"""
    directory = Path.home() / 'Library/Application Support/A7R5 Emulator'
    return AppPaths(paths().resources, directory).prepare().data / '.vm.lock'


def open_vm_lock():
    descriptor = os.open(shared_lock(), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    return os.fdopen(descriptor, 'a')


def worker_executable():
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        executable = Path(sys.executable).parent / 'A7R5Emulator'
        if executable.is_symlink() or not executable.is_file():
            raise RuntimeError('应用包缺少受控工作进程入口')
        return str(executable)
    return sys.executable
