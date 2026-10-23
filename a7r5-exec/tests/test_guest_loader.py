"""QEMU夹具从保留源码真实构建；不依赖已删除的历史二进制。"""
import importlib.util
from pathlib import Path
import pytest
from elftools.elf.elffile import ELFFile

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_guest_loader', PROJECT/'a7r5-libjit/guest_loader.py')
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def test_guest_loader_builds_aarch64_with_original_runtime_dependencies(tmp_path):
    binary = loader.build(tmp_path.resolve()/'loader-build')
    with binary.open('rb') as stream:
        elf = ELFFile(stream)
        assert elf['e_machine'] == 'EM_AARCH64'
        assert elf['e_type'] == 'ET_DYN'
        interpreter = next(s.get_interp_name() for s in elf.iter_segments() if s['p_type'] == 'PT_INTERP')
        assert interpreter == '/lib/ld-linux-aarch64.so.1'
        needed = {t.needed for t in elf.get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag == 'DT_NEEDED'}
        assert needed == {'libc.so.6', 'libdl.so.2'}
    assert (binary.parent/'build.json').exists()
    with pytest.raises(FileExistsError):
        loader.build(binary.parent)
