"""基于真实37项清单的两种导出范围；标准模式与a7c2-re口径一致。"""
import copy
import json

from .common import BASE

VIEWS = {'standard': 'plaintext', 'extended': 'both'}
FIELDS = ('schema', 'model', 'firmware_expected', 'views', 'partitions', 'total_bytes')


def inventory(profile='standard'):
    from system_dump.core import validate_inventory
    if profile not in VIEWS:
        raise ValueError('转存模式只能为standard或extended')
    value = copy.deepcopy(json.loads((BASE / 'historical/expected-inventory.json').read_bytes()))
    value['views'] = VIEWS[profile]
    if profile == 'standard':
        value['partitions'] = [p for p in value['partitions'] if p['view'] in ('plaintext', 'boot')]
    value['total_bytes'] = sum(p['bytes'] for p in value['partitions'])
    value['coverage'] = '标准模式仅含明文与启动区；扩展模式另含物理视图；隐藏区域及一致快照未证明'
    return validate_inventory(value)


def project(value):
    from system_dump.core import validate_inventory
    validate_inventory(value)
    return {key: value[key] for key in FIELDS}
