"""仅解析主机IORegistry；原解析器和历史基线保持不变。"""
import plistlib
import subprocess

from recovery import parse_host_tree, RecoveryPending


def snapshot(location_id, *, timeout=5):
    if type(location_id) is not int or location_id!=0x00100000:
        raise ValueError('只接受本次人工确认的新位置')
    raw=subprocess.run(['/usr/sbin/ioreg','-a','-l','-r','-c','IOUSBHostDevice'],capture_output=True,check=True,timeout=timeout).stdout
    tree=plistlib.loads(raw)
    def visit(node):
        if node.get('IOObjectClass')=='IOUSBHostDevice' and node.get('idVendor')==0x054c:
            if (node.get('USB Product Name'),node.get('locationID'))!=('ILCE-7RM5',location_id):
                raise ValueError('本次型号或位置不符')
            # 复用原解析器的型号/身份/媒体限制，只对内存副本归一化位置；输出还原实测新位置。
            node['locationID']=0x01100000
        for child in node.get('IORegistryEntryChildren',[]):visit(child)
    for node in tree:visit(node)
    try:value=parse_host_tree(tree)
    except RecoveryPending as exc:
        if 'location_id' in exc.snapshot:exc.snapshot['location_id']=location_id
        raise
    value['location_id']=location_id
    return value
