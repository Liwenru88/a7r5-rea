"""实体清单与固定输入白名单分开；配置不能创造新键码。"""
import json
from app_paths import paths
from control_actions import TAPS,DIALS,action_for_request

PROVEN = frozenset((*TAPS,*DIALS,'MODE_DIAL','JOYSTICK'))


class InputRegistry:
    def __init__(self, document, manifest):
        if (document.get('schema'), document.get('model'), document.get('firmware')) != (1, 'ILCE-7RM5', '4.00'):
            raise ValueError('未知控制注册表')
        rows = document['controls']
        required = {'id', 'label', 'group', 'interaction', 'mapping_status', 'behavior_status',
                    'enabled_contexts', 'evidence', 'limitations', 'source'}
        if not isinstance(rows, list) or any(set(row) != required or not isinstance(row['id'], str) for row in rows):
            raise ValueError('控制记录结构不符')
        self.controls = {row['id']: row for row in rows}
        if len(self.controls) != len(rows):
            raise ValueError('控制 ID 重复')
        self.fingerprint_matches = document.get('input_fingerprint') == {
            key: manifest['files'][key]['sha256'] for key in ('kernel', 'initrd', 'dtb')}

    @classmethod
    def load(cls):
        root = paths().resources
        return cls(json.loads((root / 'config/controls.json').read_text()),
                   json.loads((root / 'runtime/manifest.json').read_text()))

    def available(self, control, context='menu'):
        row = self.controls.get(control, {})
        interaction='joystick' if control=='JOYSTICK' else 'select' if control=='MODE_DIAL' else 'rotate' if control in DIALS else 'tap'
        return (self.fingerprint_matches and control in PROVEN and row.get('interaction') == interaction and
                row.get('mapping_status') == 'verified' and row.get('behavior_status') == 'pass' and
                context in row.get('enabled_contexts', []) and bool(row.get('evidence')))

    def resolve(self, request, context='menu'):
        if not isinstance(request, dict) or set(request) != {'action', 'control', 'event', 'value'}:
            raise ValueError('结构化输入字段不符')
        control = request['control']
        if request['action'] != 'input' or not isinstance(control, str) or not self.available(control, context):
            raise ValueError('该控制尚未验证或当前上下文不支持')
        return action_for_request(request)
