"""复用实机通过的指纹与完整报文门槛；帧预算仅扩展为安装所需256。"""
import json
import struct
from transport import HEADER, READ, DEBUG

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")

class InterfaceGuard:
    def interface_checked(self, device, interface):
        raw = dict(pid=int(device.idProduct), bus=device.bus, ports=list(device.port_numbers or ()),
                   number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                   interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                   protocol=int(interface.bInterfaceProtocol),
                   endpoints=[dict(address=int(ep.bEndpointAddress), attributes=int(ep.bmAttributes),
                                   max_packet=int(ep.wMaxPacketSize), interval=int(ep.bInterval)) for ep in interface])
        self.interfaces_seen += 1
        save(self.output / f'interface-{self.interfaces_seen}.json', raw)
        key = f'interface-{self.interfaces_seen}.json'
        if self.interfaces_seen > 2 or raw != self.config['interfaces'].get(key):
            raise ValueError('物理端口、接口指纹或阶段不符，不换端点')
        save(self.output / f'endpoint-selection-{self.interfaces_seen}.json',
             dict(selected_in=129, selected_out=2, descriptors=raw['endpoints'],
                  rule='frozen_first_bulk_each_direction_no_fallback'))

    def guard_packet(self, packet):
        if self.permitted_packet is None or packet != self.permitted_packet or len(packet) < HEADER.size + 7:
            raise PermissionError('报文未经本次操作精确授权')
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size:]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= 256 or any(meta):
            raise PermissionError('非法固定报文')
        selects = {struct.pack('<HH', 0x1001, 15) + b'\0' +
                   (p if p.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + p).encode() + b'\0'
                   for p in self.reads}
        puts = {struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + value for value in self.writes.values()}
        if body not in selects | puts | {READ, DEBUG}:
            raise PermissionError('超出固定路径或完整写入字节')

