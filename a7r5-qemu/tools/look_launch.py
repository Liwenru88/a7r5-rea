"""启动逐次执行的参考窗口；不切换默认 QEMU 清单，不访问设备。"""
import json
from pathlib import Path
from runtime_manifest import LAB
from look_materials import regular


def parameters():
    record=json.loads(regular(LAB/'specs/004-creative-look-reference/session.json',10000))
    key='materials' if record.get('live_parameters') else 'parameters'
    relative=Path(record[key])
    expected='build' if key=='materials' else 'runs'
    if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!=expected:
        raise ValueError('参考会话路径越界')
    return LAB/relative


if __name__=='__main__':
    from look_reference_ui import launch
    launch(parameters())
