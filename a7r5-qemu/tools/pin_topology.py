"""校验原厂只读拓扑收据；描述符顺序为 Node,Module,Instance,Pin。"""
import re


def parse(text):
    tables = {}
    current = None
    rows = []
    for line in text.replace('\r', '').splitlines():
        begin = re.fullmatch(r'PIN_TOPOLOGY_BEGIN kind=(pins|pins-template) address=([0-9a-f]+)', line)
        if begin:
            if current or begin[1] in tables:
                raise ValueError('重复或未结束的拓扑表')
            current = begin[1]
            rows = []
        match = re.fullmatch(r'PIN_ATOM index=(\d+) mode=(\d+) own=([^ ]+) peer=([^ ]+)', line)
        if match:
            if not current or int(match[1]) != len(rows) or int(match[2]) > 2:
                raise ValueError('拓扑序号或模式不符')
            properties = []
            for field in (match[3], match[4]):
                values = tuple(int(value, 0) for value in field.split(','))
                if len(values) != 4 or (values != (0, 0, 0, 0) and not (
                        0x80000000 <= values[0] <= 0x9fffffff and 0 <= values[1] <= 8 and
                        1 <= values[2] <= 3 and 0 <= values[3] < 16)):
                    raise ValueError('端口属性越界')
                properties.append(values)
            rows.append(dict(index=int(match[1]), mode=int(match[2]), own=properties[0], peer=properties[1]))
        if line == 'PIN_TOPOLOGY_DONE count=50 readonly=1':
            if not current or len(rows) != 50:
                raise ValueError('拓扑记录不足50项')
            tables[current] = rows
            current = None
    if current or set(tables) != {'pins', 'pins-template'}:
        raise ValueError('缺少两份完整拓扑收据')
    if tables['pins'][1]['own'] != (0x90050004, 0, 2, 1):
        raise ValueError('拓扑不属于已核对的A7R5布局')
    return tables


def observed_queries(text):
    import struct
    result = []
    for line in text.replace('\r', '').splitlines():
        match = re.search(r'MEDIA_DATAFLOW_TRANSPORT dest=(0x[0-9a-f]+) source=(0x[0-9a-f]+) bytes=48 payload=([0-9a-f]+)', line)
        if not match or int(match[1], 16) >> 28 != 9:
            continue
        raw = bytes.fromhex(match[3])
        if len(raw) != 48 or raw[24:32] != bytes.fromhex('0010000018000200'):
            continue
        module, instance, pin, reserved = struct.unpack_from('<4I', raw, 32)
        if reserved or module > 8 or instance not in (1, 2, 3) or pin >= 16:
            raise ValueError('实际查询属性越界')
        descriptor = (module, instance, pin, int(match[1], 16))
        if descriptor not in result:
            result.append(descriptor)
    return result


def cp_properties(tables, queries=()):
    # 保持首对回归端口的索引稳定；原 AP 已有的 0x8... 服务继续由原厂处理。
    result = [(0, 2, 1, 0x90050004), (0, 1, 1, 0x9284074a)]
    for rows in tables.values():
        for row in rows:
            for node, module, instance, pin in (row['own'], row['peer']):
                descriptor = (module, instance, pin, node)
                if node >> 28 == 9 and descriptor not in result:
                    result.append(descriptor)
    for descriptor in queries:
        if descriptor not in result:
            result.append(descriptor)
    return result
