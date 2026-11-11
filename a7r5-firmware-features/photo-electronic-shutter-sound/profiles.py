"""在声音工作副本中加入机械／电子双配置；固定上游源码保持原样。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent

API = r'''
extern unsigned r5sound_native_shutter_type(void);
static r5sound_profiles profiles;
static uint32_t profile_request,profile_saved,active_profile,profile_error[2];
static int load_profiles(const r5sound_storage *s){
 r5sound_profiles next;int rc=r5sound_profiles_load(s,&run.catalog,&next);
 for(unsigned g=0;g<2;g++){
  memcpy(profiles.group[g].identity,next.group[g].identity,32);
  STORE(&profiles.group[g].step,next.group[g].step);STORE(&profiles.group[g].selected,next.group[g].selected);STORE(&profile_error[g],0);
 }return rc;
}
unsigned r5sound_profile_selected(unsigned g){return g<2?LOAD(&profiles.group[g].selected):0;}
unsigned r5sound_profile_volume(unsigned g){unsigned n=g<2?LOAD(&profiles.group[g].step):5;return n?n:5;}
const char *r5sound_profile_status(unsigned g){
 if(g>=2)return "";
 if(!LOAD(&run.published))return "正在读取机内声音库";
 if(LOAD(&profile_error[g]))return "保存失败：详见R5SOUND.LOG";
 if((LOAD(&profile_request)>>16)==g+1)return "正在保存";
 if(g==LOAD(&active_profile)||LOAD(&run.fault))return r5sound_status();
 return r5sound_profile_selected(g)?"已保存：切换至对应快门后生效":"已关闭";
}
int r5sound_profile_blocked(unsigned g){return g>=2||!LOAD(&run.published)||LOAD(&profile_request)||LOAD(&run.request)||LOAD(&run.resuming)||LOAD(&run.fault);}
static int profile_enqueue(unsigned g,unsigned n){
 if(r5sound_profile_blocked(g))return 1;
 uint32_t z=0,v=((g+1)<<16)|n;
 return __atomic_compare_exchange_n(&profile_request,&z,v,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)?0:1;
}
int r5sound_profile_request(unsigned g,unsigned index){if(index>r5sound_count())return -1;return profile_enqueue(g,index+1);}
int r5sound_profile_volume_request(unsigned g,unsigned step){if(step<1||step>10||!r5sound_profile_selected(g))return -1;return profile_enqueue(g,0x100|step);}
static unsigned native_profile(void){return r5sound_profile_from_native(r5sound_native_shutter_type());}
'''

SERVICE = r'''
 /* 设置菜单只排队；双组存储和模式切换均由这一工作线程串行执行。 */
 if(!LOAD(&run.request)&&!run.changing){
  uint32_t queued=LOAD(&profile_request);
  if(queued){
   unsigned g=(queued>>16)-1,value=queued&0xffff;
   unsigned index=value&0x100?r5sound_profile_selected(g):value-1;
   unsigned step=value&0x100?value&255:r5sound_profile_volume(g);
   if(!profile_saved){
    struct r5_lut_directory d;r5sound_storage s;int rc=directory(&d,&s);
    if(!rc){rc=r5sound_profiles_save(&s,&run.catalog,&profiles,g,index,step);if(r5_lut_directory_release(&d))rc=-1;}
    if(!r5_session_current())rc=-1;
    logit("PROFILE_SAVE",0,rc,&g,1);
    if(rc){STORE(&profile_error[g],1);STORE(&profile_request,0);STORE(&run.status,S_SAVE_ERROR);__atomic_add_fetch(&run.revision,1,__ATOMIC_RELEASE);return 0;}
    STORE(&profile_error[g],0);
    profile_saved=1;
   }
   /* 非当前快门组仅保存，当前音频保持；当前组走同一退休／安装事务。 */
   if(g==native_profile()){
    if(r5ss_configure(&run.scheduler,0,0))return 1;
    STORE(&active_profile,g);STORE(&run.step,step);run.restoring=1;STORE(&run.request,index+1);
   }
   STORE(&profile_request,0);profile_saved=0;__atomic_add_fetch(&run.revision,1,__ATOMIC_RELEASE);
  }
  unsigned target=native_profile();
  if(!LOAD(&run.request)&&target!=active_profile){
   if(r5ss_configure(&run.scheduler,0,0))return 1;
   STORE(&active_profile,target);STORE(&run.step,r5sound_profile_volume(target));
   run.restoring=1;STORE(&run.request,r5sound_profile_selected(target)+1);
   __atomic_add_fetch(&run.revision,1,__ATOMIC_RELEASE);
  }
 }
 /* 在旧模式事务期间发生的新曝光，不得在旧模式中播放。 */
 if(native_profile()!=active_profile&&r5ss_configure(&run.scheduler,0,0))return 1;
'''


def apply(work, write, edit):
    def write_text(name, text):
        write(name, text.encode())

    write('menu_research/r5_sound_menu437.c', (HERE / 'bindings/r5_sound_profiles_menu.c').read_bytes())
    edit('menu_research/r5_sound_menu437.c', [
        ('0x02ff4600u:0x02ff4700u', '0x02ff5600u:0x02ff5700u'),
    ])
    edit('menu_research/r5_sound_menu437.h', [
        ('#define R5SOUND_MENU_ID 0x636u', '#define R5SOUND_MENU_ID 0x636u\n#define R5SOUND_MECHANICAL_MENU_ID 0x638u\n#define R5SOUND_MECHANICAL_VOLUME_MENU_ID 0x639u'),
        ('#define R5SOUND_VOLUME_HELP_RESOURCE 0x02ff465bu', '#define R5SOUND_VOLUME_HELP_RESOURCE 0x02ff4690u'),
    ])
    header = work / 'menu_research/r5_sound_menu437.h'
    source = header.read_text()
    for old, new in (('0x02ff46', '0x02ff56'),):
        if source.count(old) != 6:
            raise ValueError('声音文字资源前像数量不符')
        source = source.replace(old, new)
    write_text('menu_research/r5_sound_menu437.h', source)
    edit('import/r5sound_store.c', [
        ('!memcmp(n,"R5SOUND.NEW",11)', '!memcmp(n,"R5SOUND.NEW",11)||!memcmp(n,"R5SOUND.PRO",11)'),
    ])
    edit('import/r5sound_runtime.c', [
        ('#include "r5sound_runtime.h"', '#include "r5sound_runtime.h"\n#include "r5sound_profiles.h"'),
        ('enum {S_READY,', API+'\nenum {S_READY,'),
        ('uint8_t scratch[R5SOUND_INDEX_BYTES];r5sound_catalog*c=0;',
         'uint8_t *scratch=run.alloc(R5SOUND_INDEX_BYTES);if(!scratch){STORE(&run.status,S_BOOT_ERROR);return;}r5sound_catalog*c=0;'),
        ('scratch,sizeof scratch', 'scratch,R5SOUND_INDEX_BYTES', 2),
        ('if(c)run.free(c);\n if(rc<0)', 'if(c)run.free(c);run.free(scratch);\n if(rc<0)'),
        ('unsigned step=5;int vol=r5sound_volume_load(&s,&step);STORE(&run.step,step);logit("VOLUME_LOAD",0,vol,&step,1);\n int sel=r5sound_selection_load(&s,&run.catalog,&selected);if(sel)logit("SELECTION_LOAD_FAILED",0,sel,0,0);',
         'int loaded=load_profiles(&s);logit("PROFILES_LOAD",0,loaded,0,0);if(loaded<0)STORE(&run.status,S_SAVE_ERROR);\n STORE(&active_profile,native_profile());STORE(&run.step,r5sound_profile_volume(active_profile));\n selected=r5sound_profile_selected(active_profile);'),
        ('if(selected)(void)r5sound_request(selected);', 'if(selected){run.restoring=1;(void)r5sound_request(selected);}'),
        ('struct r5_lut_directory d;r5sound_storage s;unsigned step=5,selected=0;\n if(directory(&d,&s))return -1;\n int vol=r5sound_volume_load(&s,&step);\n int sel=r5sound_selection_load(&s,&run.catalog,&selected);\n int close=r5_lut_directory_release(&d);\n if(vol<0||sel<0||close||!r5_session_current())return -1;\n STORE(&run.step,step);run.restoring=1;\n STORE(&run.request,selected+1);return 0;',
         'struct r5_lut_directory d;r5sound_storage s;if(directory(&d,&s))return -1;\n int loaded=load_profiles(&s);\n int close=r5_lut_directory_release(&d);\n if(loaded<0||close||!r5_session_current())return -1;\n STORE(&active_profile,native_profile());STORE(&run.step,r5sound_profile_volume(active_profile));run.restoring=1;\n STORE(&run.request,r5sound_profile_selected(active_profile)+1);return 0;'),
        ('STORE(&run.request,0);run.changing=run.restoring=run.retry=0;', 'STORE(&run.request,0);STORE(&profile_request,0);profile_saved=0;run.changing=run.restoring=run.retry=0;'),
        ('if(run.fault)return 0;\n if(run.retry)', 'if(run.fault)return 0;\n'+SERVICE+'\n if(run.retry)'),
        ('(void)r5ss_configure(&run.scheduler,run.generation,policy.audible);return 1;',
         '(void)r5ss_configure(&run.scheduler,run.generation,policy.audible&&native_profile()==active_profile);return 1;'),
    ])
    # 快门类型绑定源自4.00的实际选择描述符，禁止按M4地址推断。
    import json
    path = work / 'dependencies/native_bindings.json'
    native = json.loads(path.read_text())
    native['r5sound_native_shutter_type'] = 0x1bfadc0
    write_text('dependencies/native_bindings.json', json.dumps(native, indent=2)+'\n')

    edit('import/build_ap_module.py', [('0<memory<=327680', '0<memory<=393216')])
    # 保持原厂64KiB装载对齐；更大的私有BSS由组合覆盖层向后让出一页。
    edit('sound_menu_parent437.py', [
        ('def patch_sound_group(image,descriptor,volume_descriptor):', 'def patch_sound_group(image,descriptor,volume_descriptor,mechanical,mechanical_volume):'),
        ('a=offset(RECORD,48)', 'a=offset(RECORD,96)'),
        ('bytes(result[a:a+48])!=bytes(48)', 'bytes(result[a:a+96])!=bytes(96)'),
        ('(descriptor,volume_descriptor):', '(descriptor,volume_descriptor,mechanical,mechanical_volume):'),
        ("edit(g+8,struct.pack('<I',10));edit(a,struct.pack('<6Q',0x636,descriptor,0,0x637,volume_descriptor,0))",
         "edit(g+8,struct.pack('<I',12));edit(a,struct.pack('<12Q',0x636,descriptor,0,0x637,volume_descriptor,0,0x638,mechanical,0,0x639,mechanical_volume,0))"),
        ('targets=(RECORD+8,RECORD+24+8)', 'targets=tuple(RECORD+24*i+8 for i in range(4))'),
        ('[(targets[0],1027,descriptor),(targets[1],1027,volume_descriptor)]', '[(target,1027,pointer) for target,pointer in zip(targets,(descriptor,volume_descriptor,mechanical,mechanical_volume))]'),
    ])
    edit('menu_parent423.py', [
        ('patch_sound_group(image, sound_descriptor, volume_descriptor)', "patch_sound_group(image,sound_descriptor,volume_descriptor,module_audit['symbols']['r5sound_mechanical_descriptor'],module_audit['symbols']['r5sound_mechanical_volume_descriptor'])"),
        ("rela['sh_size']+72", "rela['sh_size']+120", 2),
        ('len(old_relas)+3', 'len(old_relas)+5'),
        ('added_relative_entries=3', 'added_relative_entries=5'),
        ('count_before=8,count_after=10', 'count_before=8,count_after=12'),
    ])
    edit('menu_research/r5_filter_menu423.c', [
        ('id==R5SOUND_MENU_ID||id==R5SOUND_VOLUME_MENU_ID||', '(id>=R5SOUND_MENU_ID&&id<=R5SOUND_MECHANICAL_VOLUME_MENU_ID)||'),
        ('id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT||id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT',
         'id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT||id-R5SOUND_VOLUME_ROW_FIRST<R5SOUND_VOLUME_ROW_COUNT||id-0x1700u<61u||id-0x1740u<10u', 3),
        ('return id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT?R5SOUND_MENU_ID:',
         'return id-0x1700u<61u?R5SOUND_MECHANICAL_MENU_ID:id-0x1740u<10u?R5SOUND_MECHANICAL_VOLUME_MENU_ID:id-R5SOUND_ROW_FIRST<R5SOUND_ROW_COUNT?R5SOUND_MENU_ID:'),
    ])
    edit('menu_research/r5_filter_page425.c', [
        ('id==R5SOUND_MENU_ID||id==R5SOUND_VOLUME_MENU_ID', 'id>=R5SOUND_MENU_ID&&id<=R5SOUND_MECHANICAL_VOLUME_MENU_ID'),
    ])
    edit('import/build_ap_image.py', [
        ("delta=(0x5959000//4096)-((wrapper+32)//4096)", "delta=(0x5959000//4096)-((wrapper+48)//4096)"),
        ("code=struct.pack('<8I',0x7100003f|(0x635<<10),0x540000a0,0x7100003f|(0x636<<10),0x54000060,0x7100003f|(0x637<<10),0x54000061,0x2a0103e0,0xd65f03c0)+struct.pack('<I',adrp)+branch(wrapper+36,entry+4)",
         "code=struct.pack('<12I',0x7100003f|(0x635<<10),0x54000120,0x7100003f|(0x636<<10),0x540000e0,0x7100003f|(0x637<<10),0x540000a0,0x7100003f|(0x638<<10),0x54000060,0x7100003f|(0x639<<10),0x54000061,0x2a0103e0,0xd65f03c0)+struct.pack('<I',adrp)+branch(wrapper+52,entry+4)"),
        ('private_MIDs=[0x635,0x636,0x637]', 'private_MIDs=[0x635,0x636,0x637,0x638,0x639]'),
    ])
