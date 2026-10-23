"""使用既有 LLVM 工具链汇编，并由 ELF 链接器处理绝对分支重定位。"""
from pathlib import Path
import re
import subprocess
import tempfile

MC = '/opt/homebrew/opt/llvm/bin/llvm-mc'
LLD = '/opt/homebrew/opt/lld/bin/ld.lld'


def assemble(lines, address, arch='thumb'):
    if arch not in ('thumb','aarch64') or address % (2 if arch=='thumb' else 4):
        raise ValueError('架构或入口对齐不符')
    expanded=[]
    for line in lines:
        match=re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*):\s*(.+)',line)
        expanded.extend([match[1]+':',match[2]] if match else [line])
    symbols = {}
    processed = []
    checks = []
    conditions = {'beq':0, 'bne':1, 'bhs':2, 'blo':3, 'bmi':4, 'bpl':5,
                  'bvs':6, 'bvc':7, 'bhi':8, 'bls':9, 'bge':10, 'blt':11, 'bgt':12, 'ble':13}
    for line in expanded:
        match = re.match(r'^(b|beq|bne|bhs|blo|bmi|bpl|bvs|bvc|bhi|bls|bge|blt|bgt|ble|cbz|cbnz)\s+(.+)$', line)
        if arch == 'thumb' and match and '0x' in line:
            mnemonic, operand = match.groups()
            target = int(operand.split(',')[-1].strip(), 16)
            label = '__branch_check_' + str(len(checks))
            checks.append((label, target))
            displacement = f'({target} - ({address} + (. - __block_begin) + 4))'
            if mnemonic in ('cbz', 'cbnz'):
                register = int(operand.split(',')[0].strip().removeprefix('r'))
                if not 0 <= register <= 7:
                    raise ValueError('CBZ/CBNZ 只能使用低寄存器')
                expression = f'{0xb900 if mnemonic == "cbnz" else 0xb100} | (({displacement} >> 6 & 1) << 9) | (({displacement} >> 1 & 31) << 3) | {register}'
            elif mnemonic == 'b':
                expression = f'0xe000 | ({displacement} >> 1 & 2047)'
            else:
                expression = f'{0xd000 | (conditions[mnemonic] << 8)} | ({displacement} >> 1 & 255)'
            processed.extend([label + ':', '.hword ' + expression])
            continue
        # 只有分支的十六进制目标是绝对地址；MOVW 等立即数保留原意。
        if re.match(r'^(?:b(?:\.[a-z]+)?|bl|adr|adrp)\s', line):
            if arch == 'thumb' and '0x' in line:
                label = '__branch_check_' + str(len(checks))
                checks.append((label, int(re.search(r'0x[0-9a-fA-F]+',line).group(),16)))
                processed.append(label + ':')
            def replace(match):
                target = int(match.group(), 16)
                symbol = f'__destination_{target:x}'
                symbols[symbol] = target
                return symbol
            line = re.sub(r'0x[0-9a-fA-F]+', replace, line)
        processed.append(line)
    thumb = arch == 'thumb'
    header = ['.syntax unified', '.arch armv7-a', '.thumb', '.text', '.global _start', '.thumb_func', '_start:', '__block_begin:'] if thumb else ['.text', '.global _start', '_start:']
    triple = 'thumbv7-none-eabi' if thumb else 'aarch64-linux-gnu'
    with tempfile.TemporaryDirectory(prefix='a7r5-asm-') as directory:
        directory = Path(directory)
        source, obj, executable = directory/'source.s', directory/'code.o', directory/'code.elf'
        linker_script = directory/'layout.ld'
        linker_script.write_text(f'SECTIONS {{ .text {address:#x} : SUBALIGN({2 if thumb else 4}) {{ *(.text) }} /DISCARD/ : {{ *(.ARM.attributes) *(.comment) }} }}\n')
        source.write_text('\n'.join(header + processed) + '\n')
        commands = [[MC, '-triple=' + triple, '-filetype=obj', str(source), '-o', str(obj)],
            [LLD, '-m', 'armelf' if thumb else 'aarch64elf', '-T', str(linker_script),
             '--entry=_start', '--build-id=none',
             *['--defsym=' + name + '=' + hex(target) for name, target in symbols.items()],
             str(obj), '-o', str(executable)]]
        for command in commands:
            run = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if run.returncode:
                raise ValueError('本机 LLVM 汇编/链接失败：' + run.stderr[-2500:])
        from elftools.elf.elffile import ELFFile
        with executable.open('rb') as f:
            elf = ELFFile(f)
            text = elf.get_section_by_name('.text')
            if text['sh_addr'] != address:
                raise ValueError('链接器改变了请求的入口地址')
            raw = text.data()
        if not raw or len(raw) > 4096:
            raise ValueError('汇编输出长度异常')
        if checks:
            from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
            decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            with obj.open('rb') as f:
                symbols_by_name = {s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols()}
            for name, target in checks:
                offset = symbols_by_name[name]
                instruction = next(decoder.disasm(raw[offset:offset+4], address+offset), None)
                if instruction is None or int(instruction.op_str.split('#')[-1], 0) != target:
                    raise ValueError('分支范围或独立解码不符：' + name)
        return raw
