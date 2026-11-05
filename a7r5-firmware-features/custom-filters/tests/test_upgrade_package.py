"""研究升级包的精确范围、逆还原与失败发布；不执行固件或访问真实密钥。"""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).resolve().parents[1]/'experiments/packaging406'
sys.path.insert(0, str(PACKAGE))
spec = importlib.util.spec_from_file_location('filter_upgrade_build', PACKAGE/'build_update.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def archive_pair():
    entries = [dict(name=name, type='0', size=4, prefix='fixed', sha256='old', crc32='old')
               for name in (upgrade.tool.AP_IMAGE, upgrade.tool.CP_IMAGE, upgrade.SUM, '0100_config/device')]
    before = dict(entries=entries, updater_sha256='updater', outer=['same'], iv='same',
                  tail='original-archive-tail', decryption=dict(plaintext_bytes=4096),
                  components={'cpapp-b.bin': dict(sha256='cp'), 'usr/lib/appFw.so': dict(sha256='ap')})
    after = deepcopy(before)
    for row in after['entries'][:3]:
        row.update(sha256='usr' if row['name'] == upgrade.tool.AP_IMAGE else 'fat' if row['name'] == upgrade.tool.CP_IMAGE else 'sum', crc32='new')
    return before, after


@pytest.mark.parametrize('fault', [None, 'unrelated', 'metadata', 'updater', 'missing', 'tail', 'length'])
def test_archive_scope_preserves_unrelated_members_and_layout(fault):
    before, after = archive_pair()
    if fault == 'unrelated':
        after['entries'][3]['sha256'] = 'unapproved'
    elif fault == 'metadata':
        after['entries'][0]['prefix'] = 'changed-tar-header'
    elif fault == 'updater':
        after['updater_sha256'] = 'replaced'
    elif fault == 'missing':
        after['entries'].pop()
    elif fault == 'tail':
        after['tail'] = 'altered-archive-tail'
    elif fault == 'length':
        after['decryption']['plaintext_bytes'] += 1
    if fault is None:
        assert set(upgrade.verify_archive(before, after, 'usr', 'fat')) == upgrade.ALLOWED
    else:
        with pytest.raises(ValueError):
            upgrade.verify_archive(before, after, 'usr', 'fat')


@pytest.mark.parametrize('fault', [None, 'outside', 'overlap'])
def test_cp_reverse_rejects_plan_external_bytes(monkeypatch, fault):
    original, candidate = b'0123456789', bytearray(b'01abcd6789')
    monkeypatch.setattr(upgrade, 'CP_SHA', hashlib.sha256(original).hexdigest())
    if fault == 'outside':
        candidate[8] = 65
    plan = dict(source_sha256=upgrade.CP_SHA, candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                patches=[dict(offset=2, bytes=4, before=b'2345'.hex(), after=b'abcd'.hex())])
    if fault == 'overlap':
        plan['patches'].append(dict(offset=3, bytes=2, before=b'34'.hex(), after=b'bc'.hex()))
    if fault is None:
        upgrade.reverse_cp(original, bytes(candidate), plan)
    else:
        with pytest.raises(ValueError):
            upgrade.reverse_cp(original, bytes(candidate), plan)


def test_usr_components_cannot_smuggle_an_unrelated_path():
    dsos = [dict(target=p) for p in ('/lib/libaf_bootstrap406.so', '/lib/libaf_ui406.so',
                                    '/lib/libaf_requests406.so', '/lib/libaf_repository_media.so')]
    assets = [dict(target=f'/share/app/string_l{chr(97+i//26)}{chr(97+i%26)}_horizontal.uxc') for i in range(68)]
    assets += [dict(target='/share/app/image_00_23_IPSX.uxc'), dict(target='/share/app/image_00_32_IPSX.uxc')]
    manifest = dict(dsos=dsos, resource_replacements=assets, ap=dict(target_sha256='ap'))
    assert len(upgrade.expected_usr(manifest)) == 75
    assets[0]['target'] = '/etc/passwd'
    with pytest.raises(ValueError):
        upgrade.expected_usr(manifest)


@pytest.mark.parametrize('bound', [True, False])
def test_native_packaging_requires_source_binding_not_a_faked_runtime_handshake(bound):
    receipt = dict(native_integration=True, native_consumer_bound=bound,
                   native_consumers_source_bound=bound, native_asset_schema=3,
                   module_symbols={'af_cp_components406_matrix9_target': 1},
                   full_recipe_negotiable=False, installed=False, target_executed=False,
                   hardware_simulation=False, camera_io=False)
    if bound:
        upgrade.check_native_contract(receipt)
    else:
        with pytest.raises(ValueError):
            upgrade.check_native_contract(receipt)


@pytest.mark.parametrize('markers,version,schema,accepted', [
    (False,'4.08',2,True), (True,'4.09',3,True),
    (True,'4.08',3,False), (False,'4.09',2,False),
    (True,'4.09',2,False), (1,'4.09',3,False),
    (True,'4.10',3,True), (False,'4.10',2,False),
    (True,'4.10',2,False), (True,'4.11',3,False),
    (True,'4.12',3,True), (False,'4.12',2,False), (True,'4.12',2,False)])
def test_upgrade_version_matches_explicit_photo_marker_scope(markers,version,schema,accepted):
    from aspect_merge import aspect_contract, aspect_metadata, bootstrap_contract
    rows=[dict(offset=at,before=before.hex(),after=(after if after is not None else b'\x01'*len(before)).hex())
          for at,(before,after) in bootstrap_contract().items()]
    m=dict(schema=f'a7r5-406-unsigned-staging-input/{schema}',
           ap=dict(includes_aspect_changes=markers,patches=rows+aspect_contract(),aspect_merge=aspect_metadata()))
    if accepted:
        assert upgrade.check_usr_scope(m,version) is markers
    else:
        with pytest.raises(ValueError):
            upgrade.check_usr_scope(m,version)


@pytest.mark.parametrize('version,accepted',[('4.10',True),('4.11',False),('4.12',True)])
def test_build_entry_version_gate_agrees_before_reading_any_input(monkeypatch,version,accepted):
    class SourceReached(Exception):
        pass
    def source(_):
        raise SourceReached()
    monkeypatch.setattr(upgrade,'regular',source)
    # 同时覆盖公开build入口，防止仅更新内部scope校验而遗留第二处旧版本表。
    with pytest.raises(SourceReached if accepted else ValueError):
        upgrade.build(None,None,None,None,None,None,version)


@pytest.mark.parametrize('link_failure', [0, 1, 2])
def test_final_publication_requires_dat_and_completion_marker(tmp_path, monkeypatch, link_failure):
    source = tmp_path/'candidate'
    source.write_bytes(b'publication-contract-fixture')
    folder = tmp_path/'release'
    folder.mkdir()
    result = dict(status='RESEARCH_UPGRADE_PACKAGED_AND_INDEPENDENTLY_READ_BACK',
                  sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    if link_failure:
        original_link, calls = upgrade.os.link, []
        def fail(*args):
            calls.append(args)
            if len(calls) == link_failure:
                raise OSError('injected link publication failure')
            return original_link(*args)
        monkeypatch.setattr(upgrade.os, 'link', fail)
        with pytest.raises(OSError):
            upgrade.publish_package(source, folder, result)
        assert (folder/'BODYDATA.DAT').exists() == (link_failure == 2)
        assert not (folder/'verification.json').exists()
        assert not (folder/'COMPLETED.json').exists()
    else:
        upgrade.publish_package(source, folder, result)
        assert (folder/'BODYDATA.DAT').read_bytes() == source.read_bytes()
        assert (folder/'verification.json').is_file() and (folder/'COMPLETED.json').is_file()
        with pytest.raises((ValueError, FileExistsError)):
            upgrade.publish_package(source, folder, result)
