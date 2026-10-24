"""端口和媒体取自当前连接；恢复检查仍约束同一次会话。"""
from copy import deepcopy

import pytest

import host_state


def camera_tree(location=0x01100000):
    return [{'IOObjectClass':'IOUSBHostDevice','idVendor':0x054c,'idProduct':0x0e0a,
             'locationID':location,'USB Product Name':'ILCE-7RM5',
             'IORegistryEntryChildren':[{'IOObjectClass':'IOUSBMassStorageDriver',
                 'IORegistryEntryChildren':[
                     {'BSD Name':'disk9','Whole':True,'Size':126877696000},
                     {'BSD Name':'disk9s1','Whole':False,'Size':126860918784}]}]}]


@pytest.mark.parametrize('location,port',[(0x00100000,(0,[1])),(0x01100000,(1,[1])),
                                       (0x02230000,(2,[2,3]))])
def test_current_connection_accepts_different_ports_and_partition_layouts(monkeypatch,location,port):
    baseline=host_state.parse(camera_tree(location))
    assert baseline['location_id']==location
    assert host_state.physical_port(location)==port
    assert baseline['media']==[[False,126860918784],[True,126877696000]]
    monkeypatch.setattr(host_state.time,'sleep',lambda _:None)
    proof=host_state.observe(baseline,lambda *a,**k:deepcopy(baseline))
    assert proof['recovered'] and len(proof['observations'])==2


@pytest.mark.parametrize('fault',['port','media','multiple-devices','model','unknown-pid'])
def test_recovery_rejects_changed_device_or_media(monkeypatch,fault):
    tree=camera_tree(0x00100000)
    baseline=host_state.parse(tree)
    if fault=='port':tree[0]['locationID']=0x01100000
    if fault=='media':tree[0]['IORegistryEntryChildren'][0]['IORegistryEntryChildren'][1]['Size']+=512
    if fault=='multiple-devices':tree.append(deepcopy(tree[0]))
    if fault=='model':tree[0]['USB Product Name']='ILCE-7CM2'
    if fault=='unknown-pid':tree[0]['idProduct']=0xffff
    monkeypatch.setattr(host_state.time,'sleep',lambda _:None)
    proof=host_state.observe(baseline,lambda *a,**k:host_state.parse(tree))
    assert not proof['recovered'] and proof['reason']=='metadata_rejected'


@pytest.mark.parametrize('location',[None,True,0,0x01000000,0x01010000,0x01100001])
def test_unknown_port_topology_is_rejected(location):
    with pytest.raises(ValueError):host_state.parse(camera_tree(location))
