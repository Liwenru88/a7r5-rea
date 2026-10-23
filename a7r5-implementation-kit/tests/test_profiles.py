"""标准19项与扩展37项的选源、构建、验收和本机分类契约。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from tools import common, workflows
from system_dump.tasks import inventory2


def test_default_prepare_selects_19_plaintext_and_boot_without_physical_views(tmp_path):
    operation = workflows.prepare_dump(tmp_path / 'standard')
    assert operation['dump_profile'] == 'standard'
    assert operation['image_count'] == 19 and operation['image_bytes'] == 1872691200
    bundle = json.loads((tmp_path / 'standard/bundle/bundle.json').read_bytes())
    assert bundle['dump_views'] == 'plaintext'
    selected = bundle['expected_inventory']['partitions']
    assert len(selected) == 19 and not any(p['device'].startswith('p') for p in selected)
    assert {p['device'] for p in selected if p['view'] == 'boot'} == {'nflashaB0', 'nflashaB1'}


def test_host_inventory_distinguishes_standard_and_extended_from_same_live_parts():
    text = (BASE / 'historical/parts.txt').read_text()
    standard = inventory2(text, views='plaintext')
    extended = inventory2(text, views='both')
    assert len(standard['partitions']) == 19 and standard['total_bytes'] == 1872691200
    assert len(extended['partitions']) == 37 and extended['total_bytes'] == 5691539456
    with pytest.raises(ValueError):
        inventory2(text + '\n9 0 16 secretflash0\n', views='plaintext')


def test_scope_metadata_cannot_switch_profile_before_approval(tmp_path):
    directory=tmp_path/'standard'
    workflows.prepare_dump(directory)
    value=json.loads((directory/'operation.json').read_bytes())
    value['dump_profile']='extended'
    (directory/'operation.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='模式'):
        common.load(directory)
    assert not (directory/'approval.json').exists()


@pytest.mark.parametrize('profile,count', [('standard',19),('extended',37)])
def test_cross_build_and_load_binds_selected_scope_and_rejects_switch(tmp_path, profile, count):
    from mmcb_dump_once import load
    operation = workflows.prepare_dump(tmp_path / profile, profile)
    bundle, _ = load(tmp_path / profile / 'bundle')
    assert operation['image_count'] == count
    assert bundle['dump_views'] == ('plaintext' if profile == 'standard' else 'both')
    assert f'"views":"{bundle["dump_views"]}"' in (tmp_path/profile/'bundle/dump-task.sh').read_text()
    bundle['dump_views'] = 'both' if profile == 'standard' else 'plaintext'
    (tmp_path / profile / 'bundle/bundle.json').write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        load(tmp_path / profile / 'bundle')


@pytest.mark.parametrize('profile,count', [('standard',19),('extended',37)])
def test_same_c_inventory_opens_only_selected_nodes(tmp_path, profile, count):
    from system_dump.bundle import config, SOURCE
    from tools.profiles import inventory
    selected = inventory(profile)
    all_parts = inventory('extended')['partitions']
    nodes = tmp_path / 'nodes'
    nodes.mkdir()
    # 标准模式完全不创建物理节点替身；若C仍尝试打开它们，测试立即失败。
    for item in selected['partitions']:
        (nodes / item['device']).write_bytes(b'x' * 1024)
    parts = tmp_path / 'parts'
    parts.write_text('major minor #blocks name\n' + ''.join(
        f"{p['major']} {p['minor']} 1 {p['device']}\n" for p in all_parts))
    (tmp_path / 'root_config_unused').write_text('ordinary files only')
    header, _, _ = config('1234abcd'*4,'3319ad38-134e-4944-ac8a-05863becf15c',16<<20,'1'*32,
        test_card=tmp_path/'card',views=selected['views'])
    for key, value in [('SOURCE_ROOT',str(nodes)),('PARTS_SOURCE',str(parts)),('SOURCES_PATH',str(tmp_path/'selected.txt'))]:
        header += '\n#undef ' + key + '\n#define ' + key + ' ' + json.dumps(value) + '\n'
    (tmp_path/'config.h').write_text(header)
    harness = tmp_path/'select.c'
    harness.write_text('#define A7R5_HOST_TEST\n#define main original_main\n#include '+json.dumps(str(SOURCE),ensure_ascii=False)+
        '\n#undef main\nint main(void){unsigned long long bytes=0;if(source_inventory(0,&bytes))return 2;printf("%llu\\n",bytes);return 0;}\n')
    binary = tmp_path/'select'
    build = subprocess.run(['/usr/bin/clang','-O1','-I',str(tmp_path),str(harness),'-o',str(binary)],capture_output=True)
    assert build.returncode == 0, build.stderr.decode(errors='replace')
    run = subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
    assert run.returncode == 0, run.stderr
    actual = [line.split()[0] for line in (tmp_path/'selected.txt').read_text().splitlines()]
    assert actual == [p['device'] for p in selected['partitions']]
    assert len(actual) == count and int(run.stdout) == count * 1024


@pytest.mark.parametrize('fault', [None,'changed_after_check'])
def test_classification_links_preserve_sources_and_refuse_changed_original(tmp_path, fault):
    from tools.classify import classify_verified, verify_images
    items = json.loads((BASE/'historical/expected-inventory.json').read_bytes())['partitions']
    source = tmp_path/'originals'
    source.mkdir()
    proof_items=[]
    for i,item in enumerate(items):
        raw=bytes([i+1])*512
        (source/item['image']).write_bytes(raw)
        proof_items.append({'image':item['image'],'bytes':len(raw),'md5':hashlib.md5(raw).hexdigest(),
                            'sha256':hashlib.sha256(raw).hexdigest()})
    proof=tmp_path/'proof.json'
    proof.write_text(json.dumps({'images':proof_items}))
    report=tmp_path/'check.json'
    verify_images(source,proof,report)
    before={p.name:(p.stat().st_ino,common.sha(p)) for p in source.iterdir()}
    if fault:
        (source/items[0]['image']).write_bytes(b'changed')
        with pytest.raises(ValueError,match='变化'):
            classify_verified(source,proof,report,tmp_path/'view')
        assert not (tmp_path/'view').exists()
        return
    result=classify_verified(source,proof,report,tmp_path/'view')
    assert result['standard_count']==19 and result['physical_extra_count']==18
    assert result['image_data_copied_bytes']==0
    assert before=={p.name:(p.stat().st_ino,common.sha(p)) for p in source.iterdir()}
    links=list((tmp_path/'view').rglob('*.bin'))
    assert len(links)==37 and all(p.is_symlink() for p in links)
    manifest=json.loads((tmp_path/'view/classification.json').read_bytes())
    assert [g['count'] for g in manifest['groups'].values()]==[17,2,17,1]
