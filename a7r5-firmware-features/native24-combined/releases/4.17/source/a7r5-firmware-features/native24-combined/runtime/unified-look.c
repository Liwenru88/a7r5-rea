/* 原生创意外观统一列表；后台协调事务，原有外观保持原厂显示。 */
#include <stdint.h>
typedef uintptr_t W;
extern char n12_anchor[] __attribute__((visibility("hidden")));
extern unsigned r5_filter_selected(void),r5_filter_available_mask(void);
extern uint32_t r5_filter_bank_crc(void);
extern unsigned r5_filter_pending(void),r5_filter_command_state(void),r5_filter_command_sequence(void);
extern int r5_filter_request(unsigned),usleep(unsigned);
extern unsigned r5_filter_recovery_required(void),r5_filter_factory_reset_needed(void);
extern unsigned r5_filter_recovering(void);
extern int r5_tune_seed(unsigned,const int32_t *),r5_tune_value(unsigned,unsigned,int *),r5_tune_default(unsigned,unsigned,int *);
extern int r5_tune_edit(unsigned,unsigned,int),r5_tune_reset(unsigned),r5_tune_overlay(uint8_t *,W);
extern unsigned r5_tune_observe425(const uint8_t *,W,unsigned *),r5_osal_msg_size(const void *);
extern void r5_tune_sent425(unsigned,unsigned,int);
extern unsigned r5_tune_changed(unsigned),r5_tune_pending_changed(unsigned),r5_tune_status(void);
extern void r5_filter_factory_reset_done(void);
extern void r5_native_menu_insert(void *,const void *,const void *);
extern void r5_native_row_insert(void *,const void *,const void *);
extern unsigned r5_native_menu_normalize(void *,unsigned);
extern const char *r5_filter_full_name(unsigned),*n12_stock_text(unsigned);
extern void n12_stock_select(unsigned),n12_stock_preview(void *,unsigned),n12_stock_preview_menu(unsigned);
extern W n12_stock_alias(unsigned),n12_stock_alias_object(void *,unsigned),n12_stock_name(void *,unsigned);
extern W n12_stock_icon(void *,unsigned),n12_stock_icon_alt(void *,unsigned),n12_stock_parent(void *,unsigned);
extern W n12_stock_visible(void *,unsigned),n12_stock_available(void *,unsigned);
extern W n12_stock_inhibited(void *),n12_stock_direct(void *,const void *);
extern void n12_stock_display(void *,void *,void *,const void *),n12_stock_parameter_init(void *);
extern void n12_stock_base_cycle(void *,unsigned);
extern W n12_stock_parameter_value(void *),n12_stock_parameter_disabled(void *),n12_stock_parameter_default(void *);
extern W n12_stock_base_available(void);
extern W n12_stock_refresh(void *);
extern void n12_stock_labels(void *);
extern W n12_stock_dispatch(W,W,W),n12_stock_parameter_dispatch(W,W,W);
W n12_refresh(void *);
extern void n12_stock_reset(void *),n12_stock_parameter_layout(void *);
extern void n12_stock_parameter_labels(void *);
#define FIRST 0x1610u
#define COUNT 24u
#define TEXT 0x02ff4301u
#define TITLE 0x02ff4601u
#define TAB_TEXT 0x02ff4a00u
unsigned char n12_rows[43][128] __attribute__((aligned(8)));
static W pairs[COUNT][2];
static unsigned prepared,initializing,base_value,last_slot,last_menu;
static struct {
    unsigned active,sequence,slot,row,bank;
    unsigned queued,next_slot,next_row;
    unsigned failed,failed_row,failed_sequence,ready_row,processing,leaving;
} flow;
/* 诊断只读，不作为事务完成位。 */
unsigned n12_last_status,n12_last_sequence;
static char titles[COUNT][192];
static unsigned seen_state,seen_sequence,seen_selected,seen_menu,seen_mask,seen_layout,status_only;
static unsigned tune_refresh;
static unsigned last_applied_factory,last_applied_custom;
static uint32_t last_applied_bank;
/* Tab与浏览状态归UI线程；观察器只读原子字段，不保存原生对象指针。 */
static struct {
    _Atomic unsigned active,main,group,browse,scope,forced,revision;
} tabs;
static W A(W n){return (W)n12_anchor-0x8f00400u+n;}
static unsigned r32(W p){return *(const unsigned *)p;}
static W r64(W p){return *(const W *)p;}
static void put(void *p,unsigned off,unsigned n){*(unsigned *)((char *)p+off)=n;}
static void copy(void *d,const void *s,unsigned n){unsigned char *a=d;const unsigned char *b=s;while(n--)*a++=*b++;}
static unsigned mid(void){return r32(((W (*)(void))A(0x28a87e8))());}
static int extra(unsigned n){return n-FIRST<COUNT;}
static int custom(void){return extra(mid());}
static int factory(unsigned menu){return menu-0x84cu<19u;}
static int busy(void){unsigned s=r5_filter_command_state();return s==1 || s==4 || r5_filter_recovering();}
static int parameter_locked(void){return r5_filter_recovery_required() || r5_filter_command_state()==6 || r5_filter_factory_reset_needed() || custom() || (factory(mid()) &&
    (flow.active || flow.queued || busy() || r5_filter_selected()));}
static int restricted(void){return ((unsigned (*)(void))A(0x17ffd84))()==1 || r32(((W (*)(void))A(0x28bfdcc))())!=0;}
static int allowed(unsigned slot){return slot && slot<=COUNT && !restricted() && (r5_filter_available_mask()&(1u<<(slot-1)));}
static unsigned tab_group(unsigned menu){return extra(menu)?1u:0u;}
static int factory_eligible(unsigned menu){
    return factory(menu) && ((unsigned (*)(unsigned))A(0x1bd5a80))(menu) &&
        ((unsigned (*)(unsigned))A(0x1bd5ab0))(menu);
}
static unsigned tab_first(unsigned group){
    if(!group){
        for(unsigned i=0;i<19;i++)if(factory_eligible(0x84c+i))return 0x84c+i;
        return 0;
    }
    for(unsigned i=1;i<=COUNT;i++)if(allowed(i))return FIRST+i-1;return 0;
}
static void tab_dirty(void){tabs.revision++;tune_refresh=1;status_only=0;}
static void tab_open(void){
    if(tabs.active)return;unsigned menu=mid();if(!factory(menu)&&!extra(menu))return;
    tabs.active=1;tabs.main=1;tabs.group=tab_group(menu);tabs.browse=0;tab_dirty();
}
static int tab_suppressed(void){return tabs.active && tabs.browse;}
unsigned n12_tabs_state(unsigned field){
    /* 已退役的焦点及历史行字段读回0，保留其余观察编号。 */
    switch(field){case 0:return tabs.active;case 2:return tabs.group;
    case 3:return tabs.browse;
    case 6:return mid();case 7:return tabs.revision;case 8:return r5_filter_command_sequence();default:return 0;}
}
unsigned n12_group_title(unsigned menu){return tabs.active?TAB_TEXT+tabs.group:((unsigned (*)(unsigned))A(0x1bd54d8))(menu);}
/* 只包住D9的两处投影，不改变全局注册树／Fn可见性。 */
void n12_list_projection(void *model,void *map,const void *params){
    unsigned old=tabs.scope;tabs.scope=tabs.active?1:old;
    ((void (*)(void *,void *,const void *))A(0x1bc36f8))(model,map,params);tabs.scope=old;
}
W n12_tabs_nextrow(int direction,unsigned *out,unsigned *kind,unsigned wrap){
    if(tabs.active && tabs.forced){
        unsigned target=tabs.forced;*out=target;*kind=((unsigned (*)(unsigned))A(0x1bd6384))(target);return 0;
    }
    unsigned old=tabs.scope;tabs.scope=tabs.active?1:old;
    W result=((W (*)(int,unsigned *,unsigned *,unsigned))A(0x1bd7234))(direction,out,kind,wrap);
    tabs.scope=old;return result;
}
static void tab_move(W controller,unsigned target){
    if(!target || target==mid())return;
    unsigned old=tabs.scope;tabs.scope=1;tabs.forced=target;
    /* 原UI属性绑定／通知和关联行种类由原导航体发布，不直写全局MID。 */
    /* 同步属性订阅者也必须看到组内索引，不能等到下一次刷新才分组。 */
    ((void (*)(void *,int))A(0x2207480))((void *)controller,1);tabs.forced=0;tabs.scope=old;
}
static unsigned factory_applied_mid(void){
    unsigned native=((unsigned (*)(void))A(0x1c05f18))();
    for(unsigned i=0;i<19;i++)if(r32(A(0x3f4a280)+i*128+0x34)==native)return 0x84c+i;
    return 0;
}
static unsigned applied_mid(void){
    unsigned n=r5_filter_selected();if(n && n<=COUNT)return FIRST+n-1;
    unsigned menu=factory_applied_mid();
    return menu?menu:0x84c;
}
static void initialize(void){
    unsigned i;if(prepared)return;
    copy(n12_rows,(void *)A(0x3f4a280),19*128);
    for(i=0;i<COUNT;i++){
        unsigned char *row=n12_rows[19+i];copy(row,(void *)A(0x3f4ab00),128);
        put(row,0,FIRST+i);put(row,4,FIRST+i);put(row,8,TEXT+i);
        put(row,0x18,0x4cf);put(row,0x34,19+i);
        put(row,0x70,0x00550029);put(row,0x74,0x00121086);put(row,0x78,0x4f);put(row,0x7c,0);
        pairs[i][0]=FIRST+i;pairs[i][1]=(W)row;
    }
    prepared=1;
}
void n12_menus(void *m,const void *b,const void *e){r5_native_menu_insert(m,b,e);}
unsigned n12_menu_alias(void *o,unsigned menu){return menu==0x635?0x1f2:r5_native_menu_normalize(o,menu);}
void n12_register(void *m,const void *b,const void *e){initialize();r5_native_row_insert(m,b,e);r5_native_row_insert(m,pairs,pairs+COUNT);}
unsigned n12_current(void){
    unsigned menu=mid(),n=r5_filter_selected();
    /* 仅当前D9的待处理行保留焦点；父菜单仍显示真正已应用的编号。 */
    unsigned forced=tabs.scope?tabs.forced:0;
    if(forced)menu=forced;
    if(forced || (flow.queued && flow.next_row==menu) || (flow.active && flow.row==menu && busy()) ||
       (tabs.scope && ((flow.active && !flow.slot && flow.row==menu) || flow.ready_row==menu))){
        if(extra(menu))return 19+menu-FIRST;
        if(factory(menu))return r32(A(0x3f4a280)+(menu-0x84c)*128+0x34);
    }
    return n && n<=COUNT?18+n:((unsigned (*)(void))A(0x1c05f18))();
}
static void failed(unsigned row,unsigned sequence){
    flow.failed=1;flow.failed_row=row;flow.failed_sequence=sequence;n12_last_status=3;
}
static void cancel(void){
    /* 只退休UI意图，不写后台状态，不取消已接收的CP/E4/文件事务。 */
    flow.queued=0;flow.active=0;flow.ready_row=0;flow.failed=0;last_menu=0;n12_last_status=0;
}
static void settle(void){
    unsigned s;if(!flow.active)return;
    s=r5_filter_command_state();
    if(flow.sequence!=r5_filter_command_sequence()){
        failed(flow.row,flow.sequence);flow.active=0;return;
    }
    if(busy())return;
    flow.active=0;
    if(s==2 && r5_filter_selected()==flow.slot){
        n12_last_status=2;
        if(flow.slot && flow.bank==r5_filter_bank_crc()){
            last_applied_custom=flow.slot;last_applied_bank=flow.bank;
        }
        if(!flow.slot && factory(flow.row) && mid()==flow.row && !flow.queued)flow.ready_row=flow.row;
    }else failed(flow.row,flow.sequence);
}
static void pump(unsigned live){
    unsigned row,slot,rc;
    uint32_t bank;
    if(flow.processing)return;
    flow.processing=1;
    if(!live){cancel();goto done;}
    settle();
    if(flow.queued && flow.next_row!=mid())flow.queued=0;
    if(flow.ready_row && flow.ready_row!=mid())flow.ready_row=0;
    if(!flow.queued)goto done;
    if(flow.active || busy()){n12_last_status=4;goto done;}
    row=flow.next_row;slot=flow.next_slot;
    if((slot && !allowed(slot)) || (!slot && (!factory(row) || restricted()))){
        flow.queued=0;failed(row,r5_filter_command_sequence());goto done;
    }
    if(!r5_filter_pending() && r5_filter_command_state()==2 && r5_filter_selected()==slot && !r5_tune_changed(slot)){
        flow.queued=0;n12_last_status=2;if(!slot)flow.ready_row=row;goto done;
    }
    bank=slot?r5_filter_bank_crc():0;
    rc=(unsigned)r5_filter_request(slot);
    if(rc){
        /* 原提交器也可能在检查后被其他合法请求占用；忙态保留最后目标。 */
        if(busy()){n12_last_status=4;goto done;}
        flow.queued=0;failed(row,r5_filter_command_sequence());goto done;
    }
    flow.queued=0;flow.active=1;flow.sequence=r5_filter_command_sequence();
    flow.slot=slot;flow.row=row;flow.bank=bank;n12_last_sequence=flow.sequence;n12_last_status=1;
    /* 兼容同步完成的边界，但绝不在UI线程循环等候。 */
    settle();
done:flow.processing=0;
}
static int apply(unsigned slot){
    unsigned row=mid();if(flow.leaving)return 0;
    if(last_menu!=row || last_slot!=slot)flow.failed=0;
    last_menu=row;last_slot=slot;
    settle();
    if(flow.failed && flow.failed_row==row && flow.failed_sequence==r5_filter_command_sequence())return 0;
    if(slot && !allowed(slot)){failed(row,r5_filter_command_sequence());return 0;}
    flow.ready_row=0;
    if(flow.active && flow.slot==slot && flow.row==row && !r5_tune_pending_changed(slot)){
        flow.queued=0;n12_last_status=1;return 0;
    }
    flow.queued=1;flow.next_slot=slot;flow.next_row=row;pump(1);
    return !flow.active && !flow.queued && n12_last_status==2 && r5_filter_selected()==slot;
}
static int select_custom(unsigned selector){
    /* 未知扩展值也拒绝透传，避免原有限数组越界。 */
    if(selector<19)return 0;
    if(selector<43 && mid()==FIRST+selector-19)(void)apply(selector-18);
    return 1;
}
static int release_native(void){
    if(flow.leaving)return 0;
    if(!factory(mid()))return !flow.active && !flow.queued && !busy() && !r5_filter_recovery_required() && r5_filter_command_state()!=6 && !r5_filter_factory_reset_needed() && !r5_filter_selected() && !r5_filter_pending();
    if(!flow.active && !flow.queued && !busy() && !r5_filter_recovery_required() && r5_filter_command_state()!=6 && !r5_filter_selected() && !r5_filter_pending()){
        r5_filter_factory_reset_done();
        if(last_menu!=mid())flow.failed=0;last_menu=mid();last_slot=0;flow.ready_row=0;return 1;
    }
    if(!apply(0))return 0;flow.ready_row=0;return 1;
}
void n12_select(unsigned selector){if(tab_suppressed())return;if(!select_custom(selector) && release_native())n12_stock_select(selector);}
void n12_preview(void *context,unsigned selector){if(tab_suppressed())return;if(!select_custom(selector) && release_native())n12_stock_preview(context,selector);}
void n12_preview_menu(unsigned menu){
    if(tab_suppressed())return;
    if(extra(menu)){if(menu==mid())(void)apply(menu-FIRST+1);return;}
    if(release_native())n12_stock_preview_menu(menu);
}
W n12_alias(unsigned menu){if(extra(menu))return menu;return n12_stock_alias(menu==0x635?0x1f2:menu);}
W n12_alias_object(void *o,unsigned menu){if(extra(menu))return menu;return n12_stock_alias_object(o,menu==0x635?0x1f2:menu);}
W n12_name(void *o,unsigned menu){return extra(menu)?TEXT+menu-FIRST:n12_stock_name(o,menu);}
static unsigned phase(unsigned slot){
    unsigned state=r5_filter_command_state();
    unsigned row=FIRST+slot-1;
    /* 后台失败及恢复保护优先于UI排队提示；保留队列和E4保护，
     * 但不能把已经失败的事务无限显示为仍在正常切换。 */
    if(state>=5 && ((flow.queued && flow.next_row==row) || (flow.active && flow.row==row)))return 3;
    if(state==4 && !flow.active)return 1;
    if(flow.queued && flow.next_row==row)return 4;
    if(flow.active && flow.row==row){
        if(flow.sequence!=r5_filter_command_sequence())return 3;
        if(busy())return 1;
        if(state!=2 || r5_filter_selected()!=slot)return 3;
    }
    if(flow.failed && flow.failed_row==row && flow.failed_sequence==r5_filter_command_sequence())return 3;
    return r5_filter_selected()==slot?0:2;
}
unsigned n12_title_name(unsigned menu){return extra(menu)?TITLE+menu-FIRST+32*phase(menu-FIRST+1):((unsigned (*)(unsigned))A(0x1bd5508))(menu);}
const char *n12_text(unsigned resource){
    if(resource==TAB_TEXT)return "[原厂外观]  自定义滤镜";
    if(resource==TAB_TEXT+1)return "原厂外观  [自定义滤镜]";
    if(resource==TAB_TEXT+4)return "未导入自定义滤镜";
    unsigned code=resource-TITLE,n=code&31,i=0,j=0;const char *prefix,*full;char *out;
    if(code>=160 || n>=COUNT)return n12_stock_text(resource);
    full=r5_filter_full_name(n+1);if(!full)return "";
    prefix=(code>>5)==1?"[切换中] ":(code>>5)==3?"[切换未完成] ":(code>>5)==2?"[未应用] ":(code>>5)==4?"[等待切换] ":"";
    out=titles[n];while(prefix[j] && i<191)out[i++]=prefix[j++];j=0;
    while(full[j] && i<191)out[i++]=full[j++];out[i]=0;return out;
}
W n12_icon(void *o,unsigned menu){return extra(menu)?0x02001ea4u+2*(menu-FIRST):n12_stock_icon(o,menu);}
W n12_icon_alt(void *o,unsigned menu){return extra(menu)?0x02001ea5u+2*(menu-FIRST):n12_stock_icon_alt(o,menu);}
W n12_parent(void *o,unsigned menu){return extra(menu)?0x1e6:n12_stock_parent(o,menu);}
W n12_visible(void *o,unsigned menu){
    if(tabs.scope && (factory(menu)||extra(menu)) && tab_group(menu)!=tabs.group)return 0;
    return extra(menu)?(allowed(menu-FIRST+1)?n12_stock_visible(o,0x85d):0):n12_stock_visible(o,menu);
}
W n12_available(void *o,unsigned menu){
    if(tabs.scope && (factory(menu)||extra(menu)) && tab_group(menu)!=tabs.group)return 0;
    return extra(menu)?(allowed(menu-FIRST+1)?n12_stock_available(o,0x85d):0):n12_stock_available(o,menu);
}

/* 原生主／调参显示可能读取有限数组，新增项显示独立八项工作值。 */
void n12_display(void *context,void *output,void *changed,const void *snapshot){
    unsigned i;
    if(tabs.active && tabs.main && tabs.group && !tab_first(1))goto empty;
    if(r32((W)snapshot+0x20)<19 && !custom()){n12_stock_display(context,output,changed,snapshot);return;}
    if(custom() && allowed(mid()-FIRST+1)){
        int32_t initial[8];unsigned slot=mid()-FIRST+1;
        /* 只读ST的原始默认字段；0x50是用户工作值，0xa8才是默认值。 */
        for(i=0;i<8;i++)initial[i]=(int32_t)r32((W)snapshot+0xa8+0x1f8*i);
        if(!r5_tune_seed(slot,initial)){
            int values[8];for(i=0;i<8;i++)if(r5_tune_value(slot,i,&values[i]))break;
            if(i==8){
                for(i=0;i<8;i++){put(output,0x34+12*i,i);put(output,0x38+12*i,(unsigned)values[i]);((unsigned char *)output)[0x3c+12*i]=0;}
                put(output,0x94,0);if(!tab_suppressed() && r5_tune_changed(slot))(void)apply(slot);return;
            }
        }
    }
empty:for(i=0;i<8;i++){put(output,0x34+12*i,UINT32_MAX);put(output,0x38+12*i,0);((unsigned char *)output)[0x3c+12*i]=1;}
    put(output,0x94,0);
}
static int tune_option(void *o){
    if(!o || !custom() || !allowed(mid()-FIRST+1) || r5_tune_status())return -1;
    unsigned focus=((unsigned (*)(void *))A(0x1af11f0))((char *)o+0x1a0);
    unsigned option=((unsigned (*)(void *))A(0x220929c))(o);
    return focus>=0xf && focus<=0x1f && option>=1 && option<=8?(int)option-1:-1;
}
static void tune_changed(void){
    tune_refresh=1;flow.failed=0;tabs.browse=0;
    if(custom())(void)apply(mid()-FIRST+1);
}
W n12_inhibited(void *o){
    if(custom()){int value;return !allowed(mid()-FIRST+1) || r5_tune_value(mid()-FIRST+1,0,&value)!=0;}
    return parameter_locked()?1:n12_stock_inhibited(o);
}
W n12_direct(void *o,const void *e){
    if(custom()){
        if(e && r32((W)e+0xc)==0xd){int p=tune_option(o);int value=(int8_t)((const uint8_t *)e)[0x30];
            if(p>=0 && !r5_tune_edit(mid()-FIRST+1,(unsigned)p,value))tune_changed();return 1;}
        return 0;
    }
    return parameter_locked()?1:n12_stock_direct(o,e);
}
void n12_parameter_init(void *o){
    if(initializing)return;
    if(custom()){if(!allowed(mid()-FIRST+1))return;base_value=0;initializing=1;n12_stock_parameter_init(o);initializing=0;
        /* 原厂焦点表中0x16为对比度，0x15为高光。 */
        ((void (*)(void *,unsigned))A(0x1af3cdc))((char *)o+0x1a0,0x16);return;}
    n12_stock_parameter_init(o);
}
int n12_init_index(unsigned selector){return initializing?0:((int (*)(unsigned))A(0x2dc6160))(selector);}
const unsigned *n12_init_bases(void){return initializing?&base_value:((const unsigned *(*)(void))A(0x28c54cc))();}
void n12_base_cycle(void *o,unsigned d){if(!parameter_locked())n12_stock_base_cycle(o,d);}
static W tune_parameter(void *o,int initial){
    int value=0;unsigned option;
    if(!o || r32((W)o+0x3b18)!=mid() || !allowed(mid()-FIRST+1))return 0;
    option=((unsigned (*)(void *))A(0x220b4e0))(o);if(!option || option>8)return 0;
    if(initial)(void)r5_tune_default(mid()-FIRST+1,option-1,&value);else (void)r5_tune_value(mid()-FIRST+1,option-1,&value);
    return (unsigned)value;
}
W n12_parameter_value(void *o){return custom()?tune_parameter(o,0):n12_stock_parameter_value(o);}
W n12_parameter_disabled(void *o){return custom()?(r5_tune_status()!=0 || ((unsigned (*)(void *))A(0x220b4e0))(o)==0):parameter_locked()?1:n12_stock_parameter_disabled(o);}
W n12_parameter_default(void *o){return custom()?tune_parameter(o,1):n12_stock_parameter_default(o);}
W n12_base_available(void){return parameter_locked()?0:n12_stock_base_available();}
static void tune_step(unsigned p,unsigned direction){
    static const int low[8]={-9,-9,-9,0,-9,0,1,0},high[8]={9,9,9,9,9,9,5,9};int value;
    if(direction>1 || !allowed(mid()-FIRST+1) || r5_tune_value(mid()-FIRST+1,p,&value))return;
    int next=value+(direction?-1:1);if(next<low[p] || next>high[p] || r5_tune_edit(mid()-FIRST+1,p,next))return;tune_changed();
}
#define STEP(N) extern void n12_stock_step_##N(void *,unsigned);void n12_step_##N(void *o,unsigned d){if(custom())tune_step(N,d);else if(!parameter_locked())n12_stock_step_##N(o,d);}
STEP(0) STEP(1) STEP(2) STEP(3) STEP(4) STEP(5) STEP(6) STEP(7)

void n12_reset(void *t){if(custom()){if(!r5_tune_reset(mid()-FIRST+1))tune_changed();return;}n12_stock_reset(t);}
W n12_base_label(unsigned menu){return ((W (*)(unsigned))A(0x1bd54d8))(custom()?0x1e6:menu);}
W n12_base_icon(void *o,unsigned resource){
    if(custom())resource=((unsigned (*)(unsigned))A(0x1bd5508))(0x84c);
    return ((W (*)(void *,unsigned))A(0x220b838))(o,resource);
}
void n12_parameter_layout(void *o){
    n12_stock_parameter_layout(o);
    if(!custom() || !o || r64((W)o)!=A(0x58ca720))return;
    W records=r64((W)o+0x90);if(!records)return;
    W base=r64(records+0x98);if(r32(records+0x90)==0 && base)*(uint8_t *)(base+0x2c)=0;
}
void n12_parameter_labels(void *o){
    n12_stock_parameter_labels(o);
    if(!o || r64((W)o)!=A(0x58ca720))return;
    /* 查询只返回脏位，原生标题、数值和刻度均绘制完毕后才消费。
     * 心跳的查询早于页面管理器查询，不能把返回1当成绘制完成。 */
    seen_state=r5_filter_command_state();seen_sequence=r5_filter_command_sequence();
    seen_selected=r5_filter_selected();seen_menu=mid();seen_mask=r5_filter_available_mask();
    seen_layout=r32((W)o+8);tune_refresh=0;
}
W n12_tune_send(W queue,void *packet,W length,W mode,W timeout,W completion){
    if(queue==0x90030001u && r5_tune_overlay(packet,length)<0)return (W)-1;
    return ((W (*)(W,void *,W,W,W,W))A(0x355882c))(queue,packet,length,mode,timeout,completion);
}
W n12_tune_transport_send(W queue,void *message){
    unsigned generation=0,mask=0;
    if(queue==0x90030001u && message)
        mask=r5_tune_observe425(message,r5_osal_msg_size(message),&generation);
    /* 只用真正SND_MSG的结果，不读取已移交的消息；原厂返回语义保持。 */
    W result=((W (*)(W,void *))A(0x16dafc0))(queue,message);
    if(mask)r5_tune_sent425(generation,mask,(int)result);
    return result;
}

static unsigned creative_kind(W manager){
    unsigned i,kind=0;if(!manager)return 0;
    for(i=0;i<15;i++){
        W view=r64(manager+0x338+8*i);
        if(view && r64(view)==A(0x58ca670))kind|=1;
        if(view && r64(view)==A(0x58ca720))kind|=2;
    }
    return kind;
}
static int creative_view(W manager){return creative_kind(manager)!=0;}
static W tab_dispatch(W controller,W message,W event){
    unsigned old=tabs.scope;if(tabs.active && creative_kind(r64(controller+0x180))==1)tabs.scope=1;
    W result=n12_stock_dispatch(controller,message,event);tabs.scope=old;return result;
}
static W idle_refresh(W controller,W event,W result){
    if(event==0x20f0000u && !flow.active && !flow.queued && !flow.ready_row && !tune_refresh &&
       !r5_filter_factory_reset_needed() && seen_state==r5_filter_command_state() &&
       seen_sequence==r5_filter_command_sequence() && seen_selected==r5_filter_selected() &&
       seen_menu==mid() && seen_mask==r5_filter_available_mask())return result;
    return n12_refresh((void *)r64(controller+0x180))?1:result;
}
W n12_parameter_dispatch(W controller,W message,W event){
    /* DA有独立的原生事件入口；按键及其他通知始终委派其自身分派器。 */
    W result=n12_stock_parameter_dispatch(controller,message,event);
    unsigned menu=mid();
    if(controller && r32(controller+0x178)==0xda &&
       (event==0x20f0000u || event==0x20f0001u) && (extra(menu) || factory(menu)) &&
       (creative_kind(r64(controller+0x180))&2))return idle_refresh(controller,event,result);
    return result;
}
static void tab_switch(W controller){
    unsigned previous=tabs.group,was_browsing=tabs.browse;
    /* 自定义以已提交状态为准，原厂读取实际属性，避开切换中的临时基底。 */
    settle();
    if(!busy() && !r5_filter_factory_reset_needed()){
        unsigned state=r5_filter_command_state(),slot=r5_filter_selected();
        if(slot && (state==0 || state==2) && !r5_filter_pending() && allowed(slot)){
            last_applied_custom=slot;last_applied_bank=r5_filter_bank_crc();
        }else if(!slot && !previous && state<4 && !flow.active && !flow.queued && !flow.ready_row){
            unsigned applied=factory_applied_mid();
            if(applied)last_applied_factory=applied;
        }
    }
    tabs.group=!previous;
    unsigned target=0;
    if(tabs.group){
        if(last_applied_bank==r5_filter_bank_crc() && allowed(last_applied_custom))
            target=FIRST+last_applied_custom-1;
    }else if(factory_eligible(last_applied_factory))target=last_applied_factory;
    if(!target)target=tab_first(tabs.group);
    /* 原导航同步发布期间可能调用预览。定位完成后只提交一次。 */
    tabs.browse=1;
    tab_move(controller,target);
    if(target && mid()!=target){
        tabs.group=previous;tabs.browse=was_browsing;
    }else{
        flow.queued=flow.ready_row=0;
        if(target){
            tabs.browse=0;
            n12_preview_menu(target);
        }
    }
    tab_dirty();
}
W n12_dispatch(W controller,W message,W event){
    unsigned menu=mid(),logical=(unsigned)event;W result;
    if(controller && (event==0x20f0000u || event==0x20f0001u) &&
       (r32(controller+0x178)==0xd9 || r32(controller+0x178)==0xda) &&
       (extra(menu) || factory(menu)) && creative_view(r64(controller+0x180))){
        /* 原生心跳与值通知推进最后目标，并以原返回契约请求重绘。
         * 不伪造按键、不保存对象指针、不在文件线程调用UI。 */
        result=tab_dispatch(controller,message,event);
        return idle_refresh(controller,event,result);
    }
    if(!controller || r32(controller+0x178)!=0xd9 ||
       (!extra(menu) && !factory(menu) && !tab_suppressed()) ||
       !creative_view(r64(controller+0x180)))
        return n12_stock_dispatch(controller,message,event);
    if((event&0xff000000u)==0x01000000u || (event&0xff000000u)==0x04000000u)
        logical=((unsigned (*)(unsigned))A(0x1b2932c))((unsigned)event)|((unsigned (*)(unsigned))A(0x1b29374))((unsigned)event);
    if(creative_kind(r64(controller+0x180))==1){
        tab_open();
        if(logical==0x2010006u){tab_switch(controller);return 1;}
        /* 长按或释放由同一次左键动作消费，避免原厂再次派发左键。 */
        if(logical==0x2010007u || logical==0x2010008u)return 1;
        if(logical==0x201000fu && tabs.browse){
            unsigned restore=applied_mid();tabs.group=tab_group(restore);tab_move(controller,restore);
        }else if(tabs.browse && (logical&0xffff0000u)==0x2010000u){
            /* 空组仍可切回或退出，其余列表键没有可操作行。 */
            return 1;
        }
    }
    if(logical==0x201000cu){pump(1);if(flow.active || flow.queued || busy())return 1;}
    if(logical==0x201000fu){
        cancel();flow.leaving=1;result=tab_dispatch(controller,message,event);flow.leaving=0;
        tabs.active=tabs.main=tabs.browse=0;return result;
    }
    return tab_dispatch(controller,message,event);
}

/* 只请求当前 D9 的原生 UI 刷新，不广播成像属性，不保留呈现器指针。 */
W n12_refresh(void *manager){
    W original;unsigned menu,i,live,old;
    /* 原厂ST属性仅由UI所有者设置，不在文件线程伪造原厂选择。 */
    if(manager && r5_filter_factory_reset_needed() && !r5_filter_recovery_required() && !busy() && !r5_filter_pending() && !r5_filter_selected()){
        n12_stock_select(0);
        if(((unsigned (*)(void))A(0x1c05f18))()==0)r5_filter_factory_reset_done();
    }
    live=creative_kind((W)manager);old=tabs.scope;
    if(tabs.active && live==1)tabs.scope=1;
    original=n12_stock_refresh(manager);tabs.scope=old;menu=mid();live=creative_kind((W)manager);
    tabs.main=live==1;
    if(live==1)tab_open();
    if(!live)tabs.active=tabs.browse=0;
    pump(live && (extra(menu) || factory(menu)));
    if(flow.ready_row && flow.ready_row==menu){
        flow.ready_row=0;n12_stock_preview_menu(menu);
    }
    if(!(extra(menu) || factory(menu)) || (!tune_refresh && seen_state==r5_filter_command_state() && seen_sequence==r5_filter_command_sequence() &&
       seen_selected==r5_filter_selected() && seen_menu==menu && seen_mask==r5_filter_available_mask()))return original;
    for(i=0;i<15;i++){
        W view=r64((W)manager+0x338+8*i);
        if(view && r64(view)==A(0x58ca670)){
            status_only=!tune_refresh && !original && seen_menu==menu && seen_mask==r5_filter_available_mask() && seen_layout==r32(view+8);
            return 1;
        }
        if(view && r64(view)==A(0x58ca720)){
            return 1;
        }
    }
    return original;
}
void n12_labels(void *view){
    unsigned char saved[0xd28];W list=0,map;unsigned menu=mid(),layout=r32((W)view+8),mask=r5_filter_available_mask();
    unsigned preserve=status_only && seen_menu==menu && seen_mask==mask && seen_layout==layout;status_only=0;
    /* 事务阶段变化不改变行目录。只保留已校验1c参数块的行数据，几何仍归原体；
     * 原厂脏位、切行、换布局或bank可用位变化均重新执行完整投影。 */
    if(preserve && extra(menu) && !restricted() && r64((W)view)==A(0x58ca670)){
        map=r64((W)view+0x48);
        if(map && r32(map+9*16)==0x1c){
            list=r64(map+9*16+8);
            if(list && r32(list+0xd30)>0 && r32(list+0xd30)<=43)copy(saved,(void *)(list+0x30),sizeof saved);
            else list=0;
        }
    }
    /* 原标签体会把组内索引反查为MID，须与投影使用相同资格上下文。 */
    unsigned old=tabs.scope;if(tabs.active && r64((W)view)==A(0x58ca670))tabs.scope=1;
    n12_stock_labels(view);tabs.scope=old;
    if(r64((W)view)!=A(0x58ca670))return;
    if(tabs.active){
        W records=r64((W)view+0x48);
        W name=records?r64(records+0xb8):0;
        if(name && tabs.group && !tab_first(1))put((void *)name,0x30,TAB_TEXT+4);
    }
    if(list && menu==mid() && layout==r32((W)view+8) && mask==r5_filter_available_mask() &&
       map==r64((W)view+0x48) && r32(map+9*16)==0x1c && list==r64(map+9*16+8)){
        copy((void *)(list+0x30),saved,sizeof saved);*(unsigned char *)(list+0xd56)=1;
    }
    seen_state=r5_filter_command_state();seen_sequence=r5_filter_command_sequence();
    seen_selected=r5_filter_selected();seen_menu=mid();seen_mask=r5_filter_available_mask();seen_layout=r32((W)view+8);
    tune_refresh=0;
}
