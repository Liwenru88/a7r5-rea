"""当前全功能客体的真实 Qt 按钮入口。"""
from pathlib import Path
import environment

source = (environment.PARENT / 'qt_research.py').read_text()
namespace = {'__name__': '__main__', '__file__': str(Path(__file__))}
exec(compile(source, str(environment.PARENT / 'qt_research.py'), 'exec'), namespace)
