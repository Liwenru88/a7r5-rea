"""在最终全功能组件上重复两组设置、取消和无卡恢复。"""
from pathlib import Path
import environment

source = (environment.PARENT / 'run_validation.py').read_text()
before = "str(HERE/'qt_research.py')"
assert source.count(before) == 1
source = source.replace(before, repr(str(Path(__file__).with_name('qt_research.py').resolve())))
namespace = {'__name__': '__main__', '__file__': str(environment.PARENT / 'run_validation.py')}
exec(compile(source, namespace['__file__'], 'exec'), namespace)
