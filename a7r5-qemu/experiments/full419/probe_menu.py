"""复用已声明的声音服务边界，生产 AP／CP 保持最终 DAT 原字节。"""
from pathlib import Path
import environment
from serial_store import decode_serial_hex, validate_exports

source = (environment.PARENT / 'probe_menu.py').read_text()
source = source.replace("vm.command('mkdir -p /usr/data/lut &&", "vm.command('mkdir -p /setting /usr/data/lut &&")
source = source.replace("bytes.fromhex(b''.join(encoded.split()).decode('ascii'))", 'decode_serial_hex(encoded)')
source = source.replace("                after = None\n            else:",
                        "                validate_exports(exported)\n                after = None\n            else:")
namespace = {'__name__': '__main__', '__file__': str(environment.PARENT / 'probe_menu.py'),
             'decode_serial_hex': decode_serial_hex, 'validate_exports': validate_exports}
exec(compile(source, namespace['__file__'], 'exec'), namespace)
