"""故障夹具必须识别唯一的固定16MiB tmpfs，不接受其他路径/来源/容量。"""
import importlib.util
from pathlib import Path
import pytest
P=Path(__file__).with_name('guest')/'ram_mount.py'
spec=importlib.util.spec_from_file_location('ui406_ram_mount_guard',P);guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
GOOD=b'tmpfs /tmp/a7r5-custom-filters-lab tmpfs rw,relatime,size=16384k,mode=700 0 0\r\n'

def test_private_tmpfs_mode_and_capacity_guard():
    assert guard.private_tmpfs(GOOD,'rw')['capacity']==16*1024*1024
    assert guard.private_tmpfs(GOOD.replace(b' rw,',b' ro,'),'ro')['mode']=='ro'
    for bad in (b'',GOOD+GOOD,GOOD.replace(b'size=',b'bad='),GOOD.replace(b'size=16384k',b'size=8m'),GOOD.replace(b'tmpfs ',b'/dev/x ',1),GOOD.replace(b'lab ',b'else '),GOOD.replace(b' rw,',b' rw,ro,')):
        with pytest.raises(ValueError):guard.private_tmpfs(bad,'rw')
