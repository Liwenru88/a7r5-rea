"""对保存的真实只读响应做回归，不访问网络或设备。"""
from pathlib import Path
import hashlib,json,sys
import pytest
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE),str(HERE.parent)]
import runner
FIXTURE=HERE/'tests/fixtures/live-preflight-20261021-01.txt'

def test_real_mountinfo_accepted():
    raw=FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f46a12dc82e6efe4418388314b64c5442e4b3c8428568b56485f35c0dda3f9a9'
    runner.validate_preflight(raw,json.loads((HERE/'operation.json').read_text()),HERE)

def mount_bytes():return FIXTURE.read_bytes().split(b'===MOUNTS===\n',1)[1].split(b'===READY===\n',1)[0]
def options():return json.loads((HERE/'operation.json').read_text())

@pytest.mark.parametrize('order',['reverse','smaller_upper_id'])
def test_stack_selection_does_not_depend_on_order_or_largest_id(order):
    raw=mount_bytes()
    if order=='reverse':raw=b'\n'.join(reversed(raw.rstrip(b'\n').split(b'\n')))+b'\n'
    else:raw=raw.replace(b'63 56 0:22',b'20 56 0:22')
    evidence=runner.validate_mounts(raw,options())
    assert evidence['var_parent_chain_verified'] and evidence['account_readonly_bind_verified']
    assert evidence['var_private_id']==(20 if order=='smaller_upper_id' else 63)

@pytest.mark.parametrize('case',[
 'missing_lower','missing_upper','third_var','wrong_parent','wrong_source','wrong_type',
 'wrong_lower_device','private_writable_flags','account_writable','account_other_run',
 'account_other_device','extra_child_mount','shared','duplicate_network','duplicate_id','malformed'])
def test_unknown_or_ambiguous_mount_view_refused(case):
    lines=mount_bytes().decode().splitlines()
    lower=next(i for i,row in enumerate(lines) if row.startswith('56 '))
    upper=next(i for i,row in enumerate(lines) if row.startswith('63 '))
    account=next(i for i,row in enumerate(lines) if row.startswith('64 '))
    if case=='missing_lower':del lines[lower]
    elif case=='missing_upper':del lines[upper]
    elif case=='third_var':lines.append('88 63 0:99 / /var rw,nosuid,nodev - tmpfs a7r5-private-ssh rw')
    elif case=='wrong_parent':lines[upper]=lines[upper].replace('63 56','63 39')
    elif case=='wrong_source':lines[upper]=lines[upper].replace('tmpfs a7r5-private-ssh','tmpfs foreign')
    elif case=='wrong_type':lines[upper]=lines[upper].replace(' - tmpfs ',' - ext2 ')
    elif case=='wrong_lower_device':lines[lower]=lines[lower].replace('252:138','252:139')
    elif case=='private_writable_flags':lines[upper]=lines[upper].replace('rw,nosuid,nodev,relatime','rw,relatime')
    elif case=='account_writable':lines[account]=lines[account].replace('/etc/passwd ro,','/etc/passwd rw,')
    elif case=='account_other_run':lines[account]=lines[account].replace('/run/a7r5-ssh-'+options()['service_run'],'/run/foreign')
    elif case=='account_other_device':lines[account]=lines[account].replace('0:22','0:99')
    elif case=='extra_child_mount':lines.append('88 63 0:99 / /var/run rw - tmpfs foreign rw')
    elif case=='shared':lines[upper]=lines[upper].replace(' - tmpfs ',' shared:1 - tmpfs ')
    elif case=='duplicate_network':lines.append('88 39 0:99 / /tmp_network rw - tmpfs none rw')
    elif case=='duplicate_id':lines[upper]=lines[upper].replace('63 56','56 39')
    elif case=='malformed':lines[upper]='63 56 0:22 / /var - tmpfs'
    with pytest.raises(ValueError):runner.validate_mounts(('\n'.join(lines)+'\n').encode(),options())
