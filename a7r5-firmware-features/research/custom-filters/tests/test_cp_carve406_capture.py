"""Capture局部补丁白名单；纯元数据拒绝测试，不执行目标指令。"""
import importlib.util
from pathlib import Path

import pytest


HERE=Path(__file__).resolve().parents[1]/'experiments/packaging406/cp_carve406'


def memory_api():
    spec=importlib.util.spec_from_file_location('capture_memory_whitelist',HERE/'memory_plan.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def receipt():
    # 期望来自已批准八个内存窗口，不能由生产helper反向生成测试白名单。
    zero='de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90'
    rows=[dict(name=n,address=a,bytes=s,before_sha256=d) for n,a,s,d in (
        ('format',0xbef524,26,'659d36ca563ba4622daabb36a71dafaf6060cdcbf89bb12e75426198496d272c'),
        ('rsource',0xbef582,6,'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44'),
        ('color',0xbef65a,6,'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44'),
        ('rsource_record',0xbef678,8,'af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc'),
        ('pool',0xbef69c,20,zero),('release',0xbef6ec,20,zero),
        ('factor',0xbef838,400,'d951593a570e83c7c31b32ab893175a5f76a24c0fc61b811d5d1ae6eddd44131'),
        ('checker',0xbef5c0,96,'82025b3afa761c0a9a04fc83d64ecd8b23c965499f692d59ff9be082050836b2'))]
    return dict(capture_lifecycle=True,capture_regions=rows,capture_symbols={'permanent_capture_format':0xbef525})


def test_capture_regions_accept_only_eight_fixed_windows():
    api=memory_api();value=receipt()
    assert api.capture_regions(value,True)==value['capture_regions']
    assert sum(r['bytes'] for r in value['capture_regions'])==582
    legacy=dict(capture_lifecycle=False,capture_regions=[],capture_symbols={})
    assert api.capture_regions(legacy,False)==[]


@pytest.mark.parametrize('mutation', ['shift','extend','reorder','extra','preimage','mode'],
                         ids=['outside-owner','larger-owner','reordered-blob','extra-region','wrong-origin','legacy-injection'])
def test_capture_region_drift_rejected_before_any_artifact_access(mutation):
    api=memory_api();value=receipt();native=True
    if mutation=='shift':value['capture_regions'][0]['address']+=4
    elif mutation=='extend':value['capture_regions'][1]['bytes']+=4
    elif mutation=='reorder':value['capture_regions'].reverse()
    elif mutation=='extra':value['capture_regions'].append(dict(value['capture_regions'][0]))
    elif mutation=='preimage':value['capture_regions'][2]['before_sha256']='00'*32
    else:value['capture_lifecycle']=False;native=False
    with pytest.raises(ValueError,match='Capture'):
        api.capture_regions(value,native)
