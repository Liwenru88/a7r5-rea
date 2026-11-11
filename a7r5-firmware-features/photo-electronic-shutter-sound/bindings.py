"""把固定声音源码接入本地派生工作区，所有改动都记录前后摘要。"""
import ast
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'bindings/upstream/src'
FILTER_FIRST, FILTER_COUNT = 0x1610, 24
SOUND_FIRST, SOUND_COUNT = 0x1680, 61
VOLUME_FIRST, VOLUME_COUNT = 0x16c0, 10


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace(source, before, after, count=1):
    if source.count(before) != count:
        raise ValueError(f'声音派生前像数量不符 {before!r}')
    return source.replace(before, after)


def verify_sources():
    manifest = json.loads((HERE / 'upstream.json').read_text())
    for name, record in manifest['files'].items():
        if digest((HERE / name).read_bytes()) != record['sha256']:
            raise ValueError('声音固定源码摘要不符 ' + name)
    groups = [set(range(first, first + count)) for first, count in (
        (FILTER_FIRST, FILTER_COUNT), (SOUND_FIRST, SOUND_COUNT), (VOLUME_FIRST, VOLUME_COUNT),
        (0x1700, SOUND_COUNT), (0x1740, VOLUME_COUNT))]
    if any(left & right for i, left in enumerate(groups) for right in groups[i+1:]):
        raise ValueError('声音与滤镜菜单编号重叠')
    return manifest


def verify_native(path):
    """从完整4.00原厂组件核对快门类型描述符、选项和原生读取入口。"""
    import io
    import struct
    from elftools.elf.elffile import ELFFile
    raw = path.read_bytes()
    if digest(raw) != '41bd8f4cda1f44c7038912837737e1ce6a650065f2108061ada30e5c7f9ce7c7':
        raise ValueError('快门类型绑定需要原厂4.00 AP')
    elf = ELFFile(io.BytesIO(raw))

    def read(va, size):
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= va and va+size <= segment['p_vaddr']+segment['p_filesz']:
                at = segment['p_offset']+va-segment['p_vaddr']
                return raw[at:at+size]
        raise ValueError('快门类型核对地址不在加载范围')

    descriptor = read(0x5897cc0, 0xc0)
    if (struct.unpack_from('<I', descriptor)[0] != 0x0200a803
            or struct.unpack_from('<Q', descriptor, 0x78)[0] != 0x1bfadc0
            or struct.unpack_from('<Q', descriptor, 0x58)[0] != 0x3fa3480):
        raise ValueError('快门类型描述符前像不符')
    rows = []
    for va, resource, value in ((0x3fa3480, 0x0200a814, 0), (0x3fa3500, 0x0200a819, 1)):
        row = read(va, 128)
        if struct.unpack_from('<I', row, 8)[0] != resource or struct.unpack_from('<II', row, 0x34) != (value, 0x60a):
            raise ValueError('机械／电子快门选项前像不符')
        rows.append(dict(va=va, resource=resource, value=value, property=0x60a))
    return dict(AP_sha256=digest(raw), getter=0x1bfadc0, getter_sha256=digest(read(0x1bfadc0, 56)),
                rows=rows, unknown_type='disable-custom-playback', electronic_front_curtain='mechanical-profile')


def function(source, name):
    node, = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    return ast.get_source_segment(source, node)


def apply(work, ledger, *, native_ap=None, shared_color=False):
    verify_sources()
    native_proof = verify_native(native_ap or work / 'inputs/ap_baseline.so')

    def write(relative, data):
        target = work / relative
        before = target.read_bytes() if target.exists() else b''
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        ledger.append(dict(path=relative, stage='custom-shutter-sound',
                           before_sha256=digest(before), after_sha256=digest(data)))

    def edit(relative, changes):
        source = (work / relative).read_text()
        for change in changes:
            before, after, *count = change
            source = replace(source, before, after, count[0] if count else 1)
        write(relative, source.encode())

    write('import/r5sound_native400.json', (json.dumps(native_proof, indent=2)+'\n').encode())

    # 可移植核心与机身适配各保留固定上游字节，派生只发生在工作副本。
    for item in sorted((HERE / 'runtime').glob('*')):
        if item.is_file():
            write('import/' + item.name, item.read_bytes())
    for item in sorted((SOURCE / 'import').rglob('*')):
        if item.is_file() and item.name != 'build_ap_image.py':
            write('import/' + str(item.relative_to(SOURCE / 'import')), item.read_bytes())
    for item in sorted((SOURCE / 'cp').iterdir()):
        write('cp/' + item.name, item.read_bytes())
    for item in sorted((SOURCE / 'lib').iterdir()):
        write('lib/' + item.name, item.read_bytes())
    for name in ('menu_parent423.py', 'sound_menu_parent437.py'):
        write(name, (SOURCE / name).read_bytes())
    for name in ('r5_sound_menu437.c', 'r5_sound_menu437.h'):
        write('menu_research/' + name, (SOURCE / 'menu_research' / name).read_bytes())

    edit('menu_research/r5_sound_menu437.h', [
        ('R5SOUND_ROW_FIRST 0x1610u', f'R5SOUND_ROW_FIRST {SOUND_FIRST:#x}u'),
        ('R5SOUND_VOLUME_ROW_FIRST 0x1650u', f'R5SOUND_VOLUME_ROW_FIRST {VOLUME_FIRST:#x}u'),
    ])
    edit('import/r5_shutter_ap.c', [('static uint32_t exposure_serial;\n', '')])
    native = json.loads((work / 'dependencies/native_bindings.json').read_text())
    sound_native = json.loads((SOURCE / 'dependencies/native_bindings.json').read_text())
    for key, address in sound_native.items():
        if key in native and native[key] != address:
            raise ValueError('原生声音绑定冲突 ' + key)
        native[key] = address
    write('dependencies/native_bindings.json', (json.dumps(native, indent=2) + '\n').encode())

    edit('import/r5_stage413_thread.c', [
        ('#include "r5_native_lut_directory.h"', '#include "r5_native_lut_directory.h"\n#include "r5sound_runtime.h"'),
        ('(void)r5_scan_gate_initial(&r5_stage411_state.scan,a,b);',
         '(void)r5_scan_gate_initial(&r5_stage411_state.scan,a,b);r5sound_initial(a,b);'),
        ('(void)r5_scan_gate_completed(&r5_stage411_state.scan,slot);',
         '(void)r5_scan_gate_completed(&r5_stage411_state.scan,slot);r5sound_completed(slot);'),
        ('STORE(&r5_stage411_state.media[slot],value);',
         'STORE(&r5_stage411_state.media[slot],value);r5sound_media(slot,status,drive);'),
        ('STORE(&s->terminal,1);STORE(&s->exited,1);STORE(&s->child_phase,4);\n    return 0;',
         'STORE(&s->terminal,1);STORE(&s->exited,1);STORE(&s->child_phase,4);\n'
         '    return (void *)(uintptr_t)(clock&&sleep);'),
    ])
    edit('import/r5_stage413_probe.c', [
        (' extern int r5_filter_inbound(const uint8_t *,uint32_t);\n',
         ' extern int r5_filter_inbound(const uint8_t *,uint32_t);\n'
         ' extern int r5ss_snapshot_inbound(const uint8_t *,uint32_t);\n'
         ' extern void r5sound_inbound(const uint8_t *,uint32_t);\n'
         ' if(r5ss_snapshot_inbound(p,source))return 1;\n r5sound_inbound(p,source);\n'),
    ])
    edit('import/r5_runtime_session.c', [
        ('#include "r5_filter_runtime423.h"', '#include "r5_filter_runtime423.h"\n#include "r5sound_runtime.h"'),
        ('\n old=LOAD(&gate);', '\n r5sound_power(m);old=LOAD(&gate);'),
        ('const struct time pause={0,100000000};', 'struct time pause={0,100000000};'),
        (' if(!sleep)return 0;\n for(;;)', ' int ready=0;\n if(!sleep)return 0;\n for(;;)'),
        ('{r5_stage411_child(s);r5_session_finish();}', '{ready=r5_stage411_child(s)!=0;if(ready)r5sound_boot();r5_session_finish();}'),
        ('  r5_filter_service();\n', '  r5_filter_service();pause.ns=ready&&r5sound_service()?10000000:100000000;\n'),
    ])
    write('import/r5_sound_yield425.c', b'''#include "r5sound_runtime.h"
#include "r5_runtime_session.h"
#include "r5_filter_runtime423.h"
extern void *r5_stage411_dlsym(void *,const char *);
int r5sound_worker_yield(void){
 struct time{long long sec,ns;};const struct time pause={0,1000000};
 int (*sleep)(const void *,void *)=(void *)r5_stage411_dlsym(0,"nanosleep");
 if(!r5_session_current())return 0;
 r5_filter_service();if(sleep)(void)sleep(&pause,0);
 return r5_session_current();
}
''')

    edit('menu_research/r5_filter_menu423.c', [
        ('#include "r5_filter_menu423.h"', '#include "r5_filter_menu423.h"\n#include "r5_sound_menu437.h"'),
        ('r5_native_menu_insert(m,&menu_pair,&menu_pair+1);', 'r5_native_menu_insert(m,&menu_pair,&menu_pair+1);r5sound_menu_register_extra(m);'),
        ('r5_native_row_insert(m,row_pairs,row_pairs+R5_FILTER_ROW_COUNT);',
         'r5_native_row_insert(m,row_pairs,row_pairs+R5_FILTER_ROW_COUNT);r5sound_rows_register_extra(m);'),
        ('return id==R5_FILTER_MENU_ID?id:', 'return id==R5SOUND_MENU_ID||id==R5SOUND_VOLUME_MENU_ID||id==R5_FILTER_MENU_ID?id:'),
        ('return id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?id:',
         'return id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT||id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT||id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?id:'),
        ('return id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?row_available(id):r5_native_row_available(self,id);',
         'return id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT||id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT?r5sound_menu_row_available(id):id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?row_available(id):r5_native_row_available(self,id);'),
        ('return id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?row_available(id):r5_native_row_available_direct(self,id);',
         'return id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT||id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT?r5sound_menu_row_available(id):id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?row_available(id):r5_native_row_available_direct(self,id);'),
        ('return id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?R5_FILTER_MENU_ID:',
         'return id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT?R5SOUND_MENU_ID:id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT?R5SOUND_VOLUME_MENU_ID:id-R5_FILTER_ROW_FIRST<R5_FILTER_ROW_COUNT?R5_FILTER_MENU_ID:'),
        (' unsigned n;\n const char *page=', ' unsigned n;\n const char *sound=r5sound_menu_text(id);if(sound)return sound;\n const char *page='),
    ])

    # 本地精简页面只委派原厂界面，补入声音主菜单的异步完成刷新。
    page = (SOURCE / 'menu_research/r5_filter_page425.c').read_text()
    start = page.index('static uintptr_t sound_parent_presenter(')
    end = page.index('uint64_t r5_filter_controller425(', start)
    support = '''\n#include "r5_sound_menu437.h"
typedef uint64_t (*F0)(void);
typedef uint64_t (*F2)(uint64_t,uint64_t);
typedef uint64_t (*F3)(uint64_t,uint64_t,uint64_t);
static uint32_t r32(uintptr_t p){return *(const uint32_t *)p;}
static uintptr_t r64(uintptr_t p){return *(const uintptr_t *)p;}
static unsigned mid(void){return r32(((F0)A(0x28a8720))());}
'''
    write('menu_research/r5_filter_page425.c',
          ((work / 'menu_research/r5_filter_page425.c').read_text() + support + page[start:end]).encode())
    extra_path = work / 'menu_research/native_extra425.json'
    extra = json.loads(extra_path.read_text())
    for address, before, symbol in [('0x58da0c0', '0x1998208', 'r5sound_menu_event2d6_443'),
                                     ('0x58da128', '0x1998890', 'r5sound_menu_event425')]:
        if any(row['va'] == address for row in extra['relocation_addend_remaps']):
            raise ValueError('声音 GUI 入口已占用 ' + address)
        extra['relocation_addend_remaps'].append(dict(va=address, before_addend=before, symbol=symbol))
    write('menu_research/native_extra425.json', (json.dumps(extra, indent=2) + '\n').encode())

    edit('import/build_ap_module.py', [
        ('RX,RW=0x8e90000,0x8eb0000', 'RX,RW=0x8e90000,0x8eb0000\nRX_CAPACITY=RW-RX'),
        (" sources+=[HERE.parent/'menu_research/r5_filter_menu_icon434.S']",
         " sources+=[HERE.parent/'menu_research/r5_filter_menu_icon434.S']\n"
         " sources+=sorted(HERE.glob('r5sound_*.c'))+sorted(HERE.glob('r5_shutter_*.c'))\n"
         " sources+=[HERE.parent/'menu_research/r5_sound_menu437.c']"),
        ("'-I',str(HERE)]", "'-I',str(HERE),'-I',str(HERE/'include'),'-DR5SS_NATIVE_SHA256','-DR5SS_SHARED_MEMSET']"),
        ("  if Path(name).suffix!='.S':", "  if name.startswith(('r5sound_','r5_shutter_')):command+=['-fno-jump-tables']\n  if Path(name).suffix!='.S':"),
        ("'r5_native_creative_sequence_request':0x24b0780}",
         "'r5_native_creative_sequence_request':0x24b0780,'r5sound_sha256_init':0x16d9a50,"
         "'r5sound_sha256_update':0x16d97f0,'r5sound_sha256_final':0x16d9970}"),
        ('and len(code)<65536', 'and len(code)+22464+128<RX_CAPACITY'),
    ])
    # 扩展私有身份处理到声音两个父菜单，沿用原厂选择页。
    original_image = (work / 'import/build_ap_image.py').read_text()
    incoming_image = (SOURCE / 'import/build_ap_image.py').read_text()
    original_image = replace(original_image, function(original_image, 'patch_secondary_identity'),
                             function(incoming_image, 'patch_secondary_identity'))
    original_image = replace(original_image, 'patch_menu_parent(image,rxfile,code,audit)',
                             'patch_menu_parent(image,rxfile,code,audit,rx_capacity=module.RX_CAPACITY)')
    write('import/build_ap_image.py', original_image.encode())

    # 声音新版接收和保护代码采用同一套24槽布局常量。
    cp = (work / 'cp/build_cp.py').read_text()
    for before, after in [('522152', '947000'), ('52352', '81344'), ('52360', '81352'), ('155520', '311040'),
                          ('207880', '392392'), ('207888', '392400'), ('301840', '486352'), ('28768', '57472'),
                          ('[0,12]', '[0,24]'), ("view_offset':50896", "view_offset':79600"),
                          ("'views':13", "'views':25"), ('48796', '77500'), ('8354432', '15152000')]:
        if before not in cp:
            raise ValueError('24槽声音 CP 派生缺少字段 ' + before)
        cp = cp.replace(before, after)
    source_sha = digest((work / 'inputs/cp_baseline.bin').read_bytes())
    if source_sha not in ('3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8',
                           '8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32'):
        raise ValueError('声音 CP 基底身份不符')
    cp = replace(cp, "SHA='8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32'",
                 f"SHA='{source_sha}'")
    cp = replace(cp, "'-Oz','-fno-jump-tables'",
                 "'-Oz',*(['-fno-inline'] if src.name in ('native_gamma.c','cp_transfer.c') else []),'-fno-jump-tables'")
    cp = replace(cp, "link_audit['dropped_bytes']==144", "link_audit['dropped_bytes']==128")
    cp = replace(cp, "'dropped_bytes':144", "'dropped_bytes':128")
    write('cp/build_cp.py', cp.encode())
    edit('cp/cp_transfer.c', [
        ('''static uint32_t message_crc(const uint8_t *p,size_t n) {
    uint32_t c=~0u;size_t i;
    for(i=0;i<n;i++)c=crcbyte(c,(i>=28&&i<32)?0:p[i]);
    return ~c;
}''', '''extern uint32_t r5_diag_crc(const uint8_t *,size_t);
static uint32_t message_crc(const uint8_t *p,size_t n) {
    return r5_diag_crc(p,n);
}'''),
    ])
    import importlib.util
    spec = importlib.util.spec_from_file_location('shutter_sound_profiles', HERE / 'profiles.py')
    profiles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profiles)
    profiles.apply(work, write, edit)
    if shared_color:
        spec = importlib.util.spec_from_file_location('shutter_full_layout', HERE / 'full.py')
        full = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(full)
        full.prepare(work, edit)
