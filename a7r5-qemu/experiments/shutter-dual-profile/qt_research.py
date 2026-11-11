"""复用固定Qt按键测试台，工作进程来自当前声音实验目录。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]/'build/menu417-17-oLYPDW/qt_research.py'
namespace = {'__name__': '__main__', '__file__': str(HERE/'qt_research.py')}
source = SOURCE.read_text()
if source.count("'native410-baseline-menu.png'") != 1:
    raise ValueError('Qt初始快照前像不符')
source = source.replace("'native410-baseline-menu.png'", "'sound-baseline.png'")
if source.count("'SNAPSHOT','STOP'") != 1:
    raise ValueError('Qt测试动作表前像不符')
source = source.replace("'SNAPSHOT','STOP'", "'SNAPSHOT','EXPORT_STORE','STOP'")
exec(compile(source, str(SOURCE), 'exec'), namespace)
