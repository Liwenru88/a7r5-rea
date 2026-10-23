"""已独立查看的原厂首次设置固定测试路径；不写模型字段。"""
import re

# 测试保留工厂区域与日期，只选择机内设置和稍后设置温度。
SETUP_STEPS = (
    ('ENTER',0x1e0,'f016230512caa1d8e97ac2a6fcb4f156f26b006cd7d13aa99fcc370cd4cbdee0'),
    ('C4',0x1c8,'dbae1809732f895fd333af76a222995ec778f51422c3b20ae2129fbd2bf747ca'),
    ('ENTER',0xd1,'04bdd056a3692c1bde0e32e5e3b36074104d9a946f3d48421819dedf87adf69f'),
    ('ENTER',0x11d,'157a9bd067e3d26c58df5c9263ae94eafc03e413543a217b92305ed57b985e3b'),
    ('ENTER',0x99,'28728a42a718cb7287e3ae09fcf19dbea9a63de90aa420fa42902630664adb50'),
    ('ENTER',0x1de,'e34ee093c4d1119633cf8ac46359a7df8db8c4993bdb4e0f9e771dbc8d05ed31'),
    ('DOWN',0x1de,'20125814c1e67679dc40efe25d63f20368fe0e4060d2791f1719c791e82d3fa1'),
    ('ENTER',0x1f7,'817511a39d223a4299f7a74de8ab0b0fe3649c2f1c4f837ee46bb14e6456065a'),
    ('ENTER',0x355,'34c69899504b36f13e8b22120cf0fd894e61fcd6b046fb8535b79cc491fa3b3f'),
)


def finish_test_setup(vm,previous,step):
    for key,screen,pixel in SETUP_STEPS:
        previous=step(key,after=previous['sequence'])
        if vm.last_native_screen()!=screen or previous['pixel_sha256']!=pixel:
            raise RuntimeError('首次设置页面与已查看的原厂基线不符，停止：'+key)
    receipt=vm.command("grep '^KEY_TRACE_PRIVACY_STATUS ' /tmp/menu-load.log",timeout=30)
    values=re.findall(rb'^KEY_TRACE_PRIVACY_STATUS accepted=([012])\r?$',receipt,re.M)
    if not values or values[-1]!=b'2':
        raise RuntimeError('原厂首次设置未完成，未继续按键')
    previous=step('MENU',after=previous['sequence'])
    if vm.last_native_screen()!=0x2d6:
        raise RuntimeError('首次设置结束后的菜单重入失败')
    return previous
