"""Capture字段合同：固定字节、原表读取、诊断拒绝；仅运行宿主C。"""
import ctypes as c
from pathlib import Path
import struct
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1]/'native'
READ = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint32, c.c_void_p, c.c_size_t)
OFFSETS = [0, *range(4,15), *range(16,23), *range(24,42), *range(48,58)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target = tmp_path_factory.mktemp('capture-fields')/'native.so'
    command = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
        '-I'+str(NATIVE), str(NATIVE/'af_cp_capture_fields406.c'), '-o', str(target)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(target))
    lib.af_cp_capture_fields406_shadow.argtypes = [c.c_void_p]*2
    lib.af_cp_capture_fields406_normalize.argtypes = [c.c_void_p]*2
    lib.af_cp_capture_fields406_matches.argtypes = [c.c_void_p]*2
    lib.af_cp_capture_fields406_formatter.argtypes = [c.c_void_p]*3+[READ,c.c_void_p]
    return lib


def word(buffer, offset, value):
    struct.pack_into('<I', buffer, offset, value)


def ordinary():
    # 来自静态映射的独立字段快照；所有未写字节故意为9D，不能整块清零后比较。
    d = bytearray(58)
    for offset, value in ((0,1),(9,1),(11,1),(12,6),(13,3),(14,2),(40,1),(41,2)):
        d[offset] = value
    word(d,28,9)
    f = bytearray([0x9d]*78)
    for offset in (0,12,20,28,32,40,44,48,52,64,72):
        word(f,offset,0)
    word(f,24,9)
    for offset,value in ((4,0),(5,1),(6,0),(7,1),(8,6),(9,3),(10,2),
        (16,0),(17,0),(18,0),(36,1),(37,2),(56,6),(57,0),(58,21),(59,26),
        (60,0),(61,0),(62,1),(63,2),(68,1),(69,0),(70,1),(76,7),(77,9)):
        f[offset] = value
    return d, bytearray([1,0,0,0,0,0,0,0,0]), f


def port(*, failure=False, globals=None, mutate=None):
    values = {0xdcc4e0:struct.pack('<I',0), 0x18d1c25:b'\0',
        0xdcc514:struct.pack('<I',0),0xdcc518:struct.pack('<I',10),
        0xdcc524:struct.pack('<I',0),0xdcc528:struct.pack('<I',10),
        0xdcc714:struct.pack('<I',0),0xdcc718:struct.pack('<I',10),
        0xdcc72c:struct.pack('<I',0),0xdcc730:struct.pack('<I',10),
        0xdcc7c4:struct.pack('<I',0),0xdcc7c8:struct.pack('<I',10),
        0x107eefc:struct.pack('<I',0),0x107ef00:struct.pack('<I',10)}
    values.update(globals or {})
    calls = []
    def read(_, address, output, size):
        calls.append((address,size))
        if mutate:
            mutate()
        if failure or address not in values or len(values[address]) != size:
            return -7
        c.memmove(output,values[address],size)
        return 0
    return READ(read), calls


def check(api, d, e, f, callback):
    return api.af_cp_capture_fields406_formatter(
        (c.c_uint8*58).from_buffer(d), (c.c_uint8*9).from_buffer(e),
        (c.c_uint8*78).from_buffer(f), callback, None)


def test_shadow_normalization_boolean_padding_and_diagnostic_witness(api):
    shadow = bytearray((i*13+17)&255 for i in range(84))
    expected = bytearray(58)
    # 显式构造原逆格式化写集，独立断言规范顺序为目标偏移递增。
    for offset in [0,*range(4,15),*range(16,23),*range(24,42)]:
        expected[offset] = shadow[offset]
    for offset in (*range(8,12),20):
        expected[offset] = int(shadow[offset] != 0)
    expected[48:52] = shadow[44:48]
    expected[52:56] = shadow[48:52]
    expected[56],expected[57] = shadow[56],shadow[68]
    a,b = (c.c_uint8*47)(),(c.c_uint8*47)()
    s,d = (c.c_uint8*84).from_buffer(shadow),(c.c_uint8*58).from_buffer(expected)
    assert api.af_cp_capture_fields406_shadow(s,a) == 0
    assert api.af_cp_capture_fields406_normalize(d,b) == 0
    assert bytes(a) == bytes(b) == bytes(expected[i] for i in OFFSETS)
    assert api.af_cp_capture_fields406_matches(s,d) == 0
    for offset in (1,2,3,15,23,*range(42,48)):
        expected[offset] = 0xc7
    assert api.af_cp_capture_fields406_matches(s,d) == 0
    expected[56] ^= 1
    assert api.af_cp_capture_fields406_matches(s,d) != 0
    ambiguous = bytearray(84)
    word(ambiguous,44,1);word(ambiguous,48,3)
    d2 = bytearray(58);word(d2,48,1);word(d2,52,3)
    assert api.af_cp_capture_fields406_matches((c.c_uint8*84).from_buffer(ambiguous),
        (c.c_uint8*58).from_buffer(d2)) != 0
    before = bytes(shadow)
    assert api.af_cp_capture_fields406_shadow(s,s) == -1 and bytes(shadow) == before


def test_normal_formatter_full_written_fields_and_original_independent_state(api):
    d,e,f = ordinary();read,calls = port()
    assert check(api,d,e,f,read) == 0
    # 依据原typed写集逐字节核对；未写字段不借默认值填充。
    written = sorted(set([*range(0,11),*range(12,16),16,17,18,*range(20,38),
        *range(40,60),60,61,62,63,*range(64,71),*range(72,76)]))
    for offset in written:
        bad = bytearray(f);bad[offset] ^= 1
        assert check(api,d,e,bad,read) != 0,hex(offset)
    # 核心4C/4D是原独立域，不从D推导，也不要求为零。
    f[76],f[77] = 255,1
    assert check(api,d,e,f,read) == 0


def test_all_original_parameter_adjustments_and_e_overrides_keep_order(api):
    d,e,f = ordinary();read,calls = port()
    d[21] = 4;f[17] = 4;f[60] = f[61] = 4;f[58] = f[59] = 18;f[68] = 0;f[69] = 1
    assert check(api,d,e,f,read) == 0
    # E02的route覆盖、E03的列覆盖、E01回到F34，必须保持这个原顺序。
    e[1]=e[2]=e[3]=1;word(e,4,2);e[8]=3
    f[56]=3;f[57]=0;word(f,48,0)
    assert check(api,d,e,f,read) == 0
    e[0]=0;f[58]=f[59]=18;f[61]=0
    # 原AA856E没有随F3D清零而改F45，不擅自修正原不一致状态。
    assert f[69] == 1 and check(api,d,e,f,read) == 0
    f[69]=0
    assert check(api,d,e,f,read) != 0


def test_unknown_domains_bounds_and_read_errors_never_default_to_success(api):
    d,e,f = ordinary();read,calls = port(failure=True)
    assert check(api,d,e,f,read) == -7
    for change in ('profile','marker','supplement','mode','debug'):
        d,e,f = ordinary()
        values = {}
        if change == 'profile':word(d,4,0xffffffff)
        elif change == 'marker':word(d,16,249)
        elif change == 'supplement':e[2]=1;word(e,4,0xffffffff)
        elif change == 'mode':values[0xdcc4e0]=struct.pack('<I',2)
        else:values[0x18d1c25]=b'\2'
        read,calls = port(globals=values)
        assert check(api,d,e,f,read) != 0
        assert all(address < 0x20000000 for address,size in calls)


def test_formatter_changes_during_global_reads_are_rejected(api):
    d,e,f = ordinary()
    changed = [False]
    def mutate():
        if not changed[0]:
            f[76] ^= 1
            changed[0] = True
    read,calls = port(mutate=mutate)
    assert check(api,d,e,f,read) != 0
