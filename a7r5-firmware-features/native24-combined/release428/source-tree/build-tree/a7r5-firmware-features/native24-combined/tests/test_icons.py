"""新增图形的软件解码、实机兼容格式及原资源保持验证。"""
import importlib.util
import inspect

from replay import BUILD


def test_added_icons_use_native_f0_blocks_instead_of_hardware_rejected_raw_blocks():
    """实机两次在F01选中态的0x0f块中止；软件解码成功不能放行此格式。"""
    source = BUILD / 'unified-tools/unified_icons.py'
    spec = importlib.util.spec_from_file_location('native24_icon_profile', source)
    icons = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(icons)
    for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc'):
        raw = (BUILD / name).read_bytes()
        _, _, _, records, _ = icons.layout(raw)
        for index in range(48):
            at, _, _, size, offset = records[icons.COUNT + index]
            start = at + 4 + offset
            stream = raw[start:start + size]
            assert start % 4 == 0, '原厂LDEC输入使用四字节对齐'
            assert stream[0] == 0xf0, f'{name}:F{index//2+1:02d}仍使用实机拒绝的原样块'
            assert stream[-2:] == b'\0\0', '压缩块必须有显式结束标记'


def test_all48_icons_decode_with_fwtool_software_decoder(tmp_path):
    import test_unified_icons as original
    source = BUILD / 'unified-tools/unified_icons.py'
    spec = importlib.util.spec_from_file_location('native24_actual_icons', source)
    icons = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(icons)
    body = inspect.getsource(original.test_twelve_resources_preserve_original_payloads_and_decode_with_sony_decoder)
    body = body.replace('count==7868', 'count==7892').replace('range(24)', 'range(48)').replace('len(hashes)==24', 'len(hashes)==48')
    namespace = dict(original.__dict__, icons=icons)
    exec(compile(body, 'native24-sony-icon-decoder-contract', 'exec'), namespace)
    namespace['test_twelve_resources_preserve_original_payloads_and_decode_with_sony_decoder'](tmp_path)
