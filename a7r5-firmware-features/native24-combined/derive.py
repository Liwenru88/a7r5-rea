"""从冻结源逐项派生24槽运行时；原厂基底和现有十二槽源均不编辑。"""
import importlib.util
import json
from pathlib import Path
import re
import shutil
from stability import replace_exact, overlay, unified

HERE = Path(__file__).resolve().parent
FEATURE = HERE / 'dependencies/native12-combined'
FORMAT = HERE / 'dependencies/native24-format'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def derive(work):
    source = FEATURE / 'upstream/firmware/r5/src'
    checker = load(FEATURE / 'build.py', 'native24_source_checker')
    checker.check_upstream(FEATURE / 'upstream')
    prototype = load(FORMAT / 'prepare.py', 'native24_codec_source')
    frozen = FORMAT / 'verification/2026-11-03-01/source/prepare.py'
    if prototype.sha(frozen) != prototype.sha(FORMAT / 'prepare.py'):
        raise ValueError('008编解码原型源已漂移')
    shutil.copytree(source, work)
    changes = []
    match_contract = json.loads((HERE / 'derive-matches.json').read_text())
    expected_matches = {(row['path'], row['before']): row['count'] for row in match_contract}

    def write(name, transform):
        path = work / name
        before = path.read_text()
        after = transform(before)
        if before == after:
            raise ValueError('派生未发生变化：' + name)
        path.write_text(after)
        import hashlib
        changes.append({'path': name, 'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
                        'base_sha256': checker.sha(source / name), 'after_sha256': checker.sha(path)})

    def substitutions(name, pairs):
        def change(text):
            for before, after in pairs:
                text = replace_exact(text, before, after, expected_matches[(name, before)])
            return text
        write(name, change)

    substitutions('import/sd_native_look.h', [('#define R5_LOOK_SLOTS 12u', '#define R5_LOOK_SLOTS 24u')])
    write('import/r5_stage410_codec.c', prototype.codec24)
    write('import/r5_filter_selection423.c', prototype.selection24)
    substitutions('import/r5_filter_names423.c', [('[16][12]', '[16][24]'), ('4095u', '0xffffffu'),
                                              ('i<12;', 'i<24;'), ('number>12', 'number>24')])
    substitutions('import/r5_filter_runtime423.c', [('4095u', '0xffffffu'), ('n>12', 'n>24'), ('n<=12', 'n<=24')])
    # 选择包独立版本与magic；机内旧选择文件的格式兼容不依赖线协议。
    substitutions('import/r5_filter_selection423.h', [('0x53463552u', '0x54463552u')])
    substitutions('import/r5_filter_selection423.c', [('p[1]=1;', 'p[1]=2;'), ('p[1]!=1', 'p[1]!=2')])
    substitutions('import/r5_custom_filter423.h', [('48796u', '77500u'), ('50896u', '79600u'),
        ('301840u', '486352u'), ('522152u', '947000u'), ('0x53463552u', '0x54463552u'),
        (':28768u', ':57472u'), ('+13u*', '+25u*'), ('<=51780u', '<=80200u'), ('+11u*', '+23u*')])
    substitutions('import/r5_grid422.h', [('52352u', '81344u'), ('SLOTS 12u', 'SLOTS 24u'),
                                       ('207880u', '392392u'), ('301840u', '486352u')])
    for name in ('import/r5_stage413_transfer_core.c', 'cp/cp_transfer.c'):
        substitutions(name, [('4095u', '0xffffffu'), ('<=12', '<=24'),
            ('return 13;', 'return 25;'), ('==13', '==25'), ("p[7]=='X'", "p[7]=='5'"),
            ("p[7]='X'", "p[7]='5'"), ('p[1]=3;', 'p[1]=4;'), ('p[1]!=3', 'p[1]!=4')])
    substitutions('cp/cp_transfer.c', [('>12', '>24')])
    substitutions('import/r5_stage413_transfer.c', [('4095u', '0xffffffu'), ('3000u', '6000u'), ('poll<40', 'poll<80'),
                                                  ('poll==39', 'poll==79'), ('s->sends>=14', 's->sends>=28')])
    substitutions('import/r5_stage413_probe.c', [('4095u', '0xffffffu'), ("p[7]=='2'", "p[7]=='3'"),
        ("p[7]='2'", "p[7]='3'"), ('p[1]=1;', 'p[1]=2;'), ('p[1]!=1', 'p[1]!=2'),
        ('0x420', '0x524'), ('28768u', '57472u')])
    substitutions('cp/r5_stage413_probe.h', [('VERSION 1u', 'VERSION 2u'), ('0x32503552u', '0x33503552u'),
                                           ('0x420u', '0x524u'), ('28768u', '57472u')])
    substitutions('cp/cp_stage413_probe.c', [('28768u', '57472u'), ('52252u', '81244u'),
        ('52348u', '81340u'), ('4095u', '0xffffffu'), ('i<12;', 'i<24;'), ('p[1]==3', 'p[1]==4'),
        ('put(reply,12,0x420)', 'put(reply,12,0x524)')])
    substitutions('cp/custom_filter423.c', [('selected>12', 'selected>24'), ('28768u', '57472u'),
                                           ('p[1]!=1', 'p[1]!=2')])
    substitutions('cp/native_color.c', [('selected>12', 'selected>24'), ('n<=12;', 'n<=24;'),
        ('n<12;n++)if(b->expected_mask', 'n<24;n++)if(b->expected_mask'), ('52252u', '81244u')])
    substitutions('import/r5_grid420_log.c', [('selected<=12', 'selected<=24'), ('0x420', '0x524')])
    substitutions('import/build_ap_module.py', [('memory<=196608', 'memory<=327680'),
        ("'-fno-stack-protector'", "'-fno-stack-protector','-fstack-usage'")])
    # 仅Gamma编译单元禁止内联，实测省32字节；保留原getter和映射。
    substitutions('cp/build_cp.py', [("'-Oz','-fno-jump-tables'", "'-Oz',*(['-fno-inline'] if src.name=='native_gamma.c' else []),'-fno-jump-tables'"), ('522152', '947000'),
        ('52352', '81344'), ('52360', '81352'), ('155520', '311040'), ('207880', '392392'),
        ('207888', '392400'), ('301840', '486352'), ('28768', '57472'), ('[0,12]', '[0,24]'),
        ('view_offset\':50896', 'view_offset\':79600'), ('\'views\':13', '\'views\':25'),
        ('48796', '77500'), ('8354432', '15152000')])
    # 私有旧入口不注册，但其兼容回调仍保持有界，避免残留旧编号解释错误。
    substitutions('menu_research/r5_filter_menu423.h', [('ROW_COUNT 13u', 'ROW_COUNT 25u')])
    substitutions('menu_research/r5_filter_page425.c', [('list[13]', 'list[25]'), ('i<=12', 'i<=24'),
        ('selected>12', 'selected>24'), ('g.focus>12', 'g.focus>24'), ('i<13;', 'i<25;'), ('n==12', 'n==24'),
        ('if(!owned(c))return', 'if(event==0x20f0001u && owned(c))return 1;\n if(!owned(c))return')])
    # 字体函数直接链接，源绑定的私有字符串回调无需固定旧函数地址。
    font = replace_exact((FEATURE / 'menu-font.c').read_text(), 'font_dlsym', 'r5_stage411_dlsym', 9)
    font = replace_exact(font, 'original_string', 'name_char', 2)
    (work / 'import/r5_font425.c').write_text(font)
    substitutions('menu_research/r5_filter_menu423.c', [('extern void name_char(void *,const char *);',
        'extern void name_char(void *,const char *);\nextern void native12_menu_font(void *,const char *);'),
        ('if(s)name_char(sprite,s);', 'if(s)native12_menu_font(sprite,s);')])
    overlay(work, changes)
    return changes


def unified_source():
    archive = FEATURE / 'verification/2026-11-03-unified-rapid/source/firmware/unified-look.c'
    current = FEATURE / 'unified-look.c'
    if current.read_bytes() != archive.read_bytes():
        raise ValueError('统一入口源已漂移')
    text = current.read_text()
    pairs = [('#define COUNT 12u', '#define COUNT 24u'), ('n12_rows[31]', 'n12_rows[43]'),
             ('selector<31', 'selector<43'), ('+16*phase', '+32*phase'), ('n=code&15', 'n=code&31'),
             ('code>=80', 'code>=160'), ('code>>4', 'code>>5'), ('<=31)', '<=43)')]
    for before, after in pairs:
        count = next(row['count'] for row in json.loads((HERE / 'derive-matches.json').read_text())
                     if row['path']=='unified-look.c' and row['before']==before)
        text = replace_exact(text, before, after, count)
    return unified(text)
