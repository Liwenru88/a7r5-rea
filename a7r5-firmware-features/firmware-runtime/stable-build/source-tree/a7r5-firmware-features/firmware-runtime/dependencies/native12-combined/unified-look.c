/* 原生创意外观统一列表；只通过既有后台事务应用十二款。 */
#include <stdint.h>
typedef uintptr_t W;
extern char n12_anchor[] __attribute__((visibility("hidden")));
extern unsigned r5_filter_selected(void),r5_filter_available_mask(void);
extern unsigned r5_filter_pending(void),r5_filter_command_state(void),r5_filter_command_sequence(void);
extern int r5_filter_request(unsigned),usleep(unsigned);
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
extern W n12_stock_dispatch(W,W,W);
#define FIRST 0x1610u
#define COUNT 12u
#define TEXT 0x02ff4301u
#define TITLE 0x02ff4601u
unsigned char n12_rows[31][128] __attribute__((aligned(8)));
static W pairs[COUNT][2];
static unsigned prepared,initializing,base_value,last_slot,last_menu;
static struct {
    unsigned active,sequence,slot,row;
    unsigned queued,next_slot,next_row;
    unsigned failed,failed_row,failed_sequence,ready_row,processing,leaving;
} flow;
/* 诊断只读，不作为事务完成位。 */
unsigned n12_last_status,n12_last_sequence;
static char titles[COUNT][192];
static unsigned seen_state,seen_sequence,seen_selected,seen_menu,seen_mask,seen_layout,status_only;
static W A(W n){return (W)n12_anchor-0x8f00400u+n;}
static unsigned r32(W p){return *(const unsigned *)p;}
static W r64(W p){return *(const W *)p;}
static void put(void *p,unsigned off,unsigned n){*(unsigned *)((char *)p+off)=n;}
static void copy(void *d,const void *s,unsigned n){unsigned char *a=d;const unsigned char *b=s;while(n--)*a++=*b++;}
static unsigned mid(void){return r32(((W (*)(void))A(0x28a87e8))());}
static int extra(unsigned n){return n-FIRST<COUNT;}
static int custom(void){return extra(mid());}
static int factory(unsigned menu){return menu-0x84cu<19u;}
static int busy(void){unsigned s=r5_filter_command_state();return s==1 || s==4;}
static int parameter_locked(void){return custom() || (factory(mid()) &&
    (flow.active || flow.queued || busy() || r5_filter_selected()));}
static int restricted(void){return ((unsigned (*)(void))A(0x17ffd84))()==1 || r32(((W (*)(void))A(0x28bfdcc))())!=0;}
static int allowed(unsigned slot){return slot && slot<=COUNT && !restricted() && (r5_filter_available_mask()&(1u<<(slot-1)));}
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
    if((flow.queued && flow.next_row==menu) || (flow.active && flow.row==menu && busy())){
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
    if(s==1 || s==4)return;
    flow.active=0;
    if(s==2 && r5_filter_selected()==flow.slot){
        n12_last_status=2;
        if(!flow.slot && factory(flow.row) && mid()==flow.row && !flow.queued)flow.ready_row=flow.row;
    }else failed(flow.row,flow.sequence);
}
static void pump(unsigned live){
    unsigned row,slot,rc;
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
    if(!r5_filter_pending() && r5_filter_command_state()==2 && r5_filter_selected()==slot){
        flow.queued=0;n12_last_status=2;if(!slot)flow.ready_row=row;goto done;
    }
    rc=(unsigned)r5_filter_request(slot);
    if(rc){
        /* 原提交器也可能在检查后被其他合法请求占用；忙态保留最后目标。 */
        if(busy()){n12_last_status=4;goto done;}
        flow.queued=0;failed(row,r5_filter_command_sequence());goto done;
    }
    flow.queued=0;flow.active=1;flow.sequence=r5_filter_command_sequence();
    flow.slot=slot;flow.row=row;n12_last_sequence=flow.sequence;n12_last_status=1;
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
    if(flow.active && flow.slot==slot && flow.row==row){
        flow.queued=0;n12_last_status=1;return 0;
    }
    flow.queued=1;flow.next_slot=slot;flow.next_row=row;pump(1);
    return !flow.active && !flow.queued && n12_last_status==2 && r5_filter_selected()==slot;
}
static int select_custom(unsigned selector){
    /* 未知扩展值也拒绝透传，避免原有限数组越界。 */
    if(selector<19)return 0;
    if(selector<31 && mid()==FIRST+selector-19)(void)apply(selector-18);
    return 1;
}
static int release_native(void){
    if(flow.leaving)return 0;
    if(!factory(mid()))return !flow.active && !flow.queued && !busy() && !r5_filter_selected() && !r5_filter_pending();
    if(!flow.active && !flow.queued && !busy() && !r5_filter_selected() && !r5_filter_pending()){
        if(last_menu!=mid())flow.failed=0;last_menu=mid();last_slot=0;flow.ready_row=0;return 1;
    }
    if(!apply(0))return 0;flow.ready_row=0;return 1;
}
void n12_select(unsigned selector){if(!select_custom(selector) && release_native())n12_stock_select(selector);}
void n12_preview(void *context,unsigned selector){if(!select_custom(selector) && release_native())n12_stock_preview(context,selector);}
void n12_preview_menu(unsigned menu){
    if(extra(menu)){if(menu==mid())(void)apply(menu-FIRST+1);return;}
    if(release_native())n12_stock_preview_menu(menu);
}
W n12_alias(unsigned menu){if(extra(menu))return menu;return n12_stock_alias(menu==0x635?0x1f2:menu);}
W n12_alias_object(void *o,unsigned menu){if(extra(menu))return menu;return n12_stock_alias_object(o,menu==0x635?0x1f2:menu);}
W n12_name(void *o,unsigned menu){return extra(menu)?TEXT+menu-FIRST:n12_stock_name(o,menu);}
static unsigned phase(unsigned slot){
    unsigned state=r5_filter_command_state();
    unsigned row=FIRST+slot-1;
    if(flow.queued && flow.next_row==row)return 4;
    if(flow.active && flow.row==row){
        if(flow.sequence!=r5_filter_command_sequence())return 3;
        if(state==1 || state==4)return 1;
        if(state!=2 || r5_filter_selected()!=slot)return 3;
    }
    if(flow.failed && flow.failed_row==row && flow.failed_sequence==r5_filter_command_sequence())return 3;
    return r5_filter_selected()==slot?0:2;
}
unsigned n12_title_name(unsigned menu){return extra(menu)?TITLE+menu-FIRST+16*phase(menu-FIRST+1):((unsigned (*)(unsigned))A(0x1bd5508))(menu);}
const char *n12_text(unsigned resource){
    unsigned code=resource-TITLE,n=code&15,i=0,j=0;const char *prefix,*full;char *out;
    if(code>=80 || n>=COUNT)return n12_stock_text(resource);
    full=r5_filter_full_name(n+1);if(!full)return "";
    prefix=(code>>4)==1?"[应用中] ":(code>>4)==3?"[应用失败] ":(code>>4)==2?"[未应用] ":(code>>4)==4?"[等待应用] ":"";
    out=titles[n];while(prefix[j] && i<191)out[i++]=prefix[j++];j=0;
    while(full[j] && i<191)out[i++]=full[j++];out[i]=0;return out;
}
W n12_icon(void *o,unsigned menu){return extra(menu)?0x02001ea4u+2*(menu-FIRST):n12_stock_icon(o,menu);}
W n12_icon_alt(void *o,unsigned menu){return extra(menu)?0x02001ea5u+2*(menu-FIRST):n12_stock_icon_alt(o,menu);}
W n12_parent(void *o,unsigned menu){return extra(menu)?0x1e6:n12_stock_parent(o,menu);}
W n12_visible(void *o,unsigned menu){return extra(menu)?(allowed(menu-FIRST+1)?n12_stock_visible(o,0x85d):0):n12_stock_visible(o,menu);}
W n12_available(void *o,unsigned menu){return extra(menu)?(allowed(menu-FIRST+1)?n12_stock_available(o,0x85d):0):n12_stock_available(o,menu);}

/* 原生主／调参显示都可能读取有限数组，新增项只能显示只读名字。 */
void n12_display(void *context,void *output,void *changed,const void *snapshot){
    unsigned i;if(r32((W)snapshot+0x20)<19 && !parameter_locked()){n12_stock_display(context,output,changed,snapshot);return;}
    for(i=0;i<8;i++){put(output,0x34+12*i,UINT32_MAX);put(output,0x38+12*i,0);((unsigned char *)output)[0x3c+12*i]=1;}
    put(output,0x94,0);
}
W n12_inhibited(void *o){return parameter_locked()?1:n12_stock_inhibited(o);}
W n12_direct(void *o,const void *e){return parameter_locked()?1:n12_stock_direct(o,e);}
void n12_parameter_init(void *o){
    if(initializing)return;
    if(parameter_locked()){if(custom() && !allowed(mid()-FIRST+1))return;base_value=0;initializing=1;n12_stock_parameter_init(o);initializing=0;return;}
    n12_stock_parameter_init(o);
}
int n12_init_index(unsigned selector){return initializing?0:((int (*)(unsigned))A(0x2dc6160))(selector);}
const unsigned *n12_init_bases(void){return initializing?&base_value:((const unsigned *(*)(void))A(0x28c54cc))();}
void n12_base_cycle(void *o,unsigned d){if(!parameter_locked())n12_stock_base_cycle(o,d);}
W n12_parameter_value(void *o){return parameter_locked()?0:n12_stock_parameter_value(o);}
W n12_parameter_disabled(void *o){return parameter_locked()?1:n12_stock_parameter_disabled(o);}
W n12_parameter_default(void *o){return parameter_locked()?0:n12_stock_parameter_default(o);}
W n12_base_available(void){return parameter_locked()?0:n12_stock_base_available();}
#define STEP(N) extern void n12_stock_step_##N(void *,unsigned);void n12_step_##N(void *o,unsigned d){if(!parameter_locked())n12_stock_step_##N(o,d);}
STEP(0) STEP(1) STEP(2) STEP(3) STEP(4) STEP(5) STEP(6) STEP(7)

static int creative_view(W manager){
    unsigned i;if(!manager)return 0;
    for(i=0;i<15;i++){
        W view=r64(manager+0x338+8*i);
        if(view && r64(view)==A(0x58ca670))return 1;
    }
    return 0;
}
W n12_dispatch(W controller,W message,W event){
    unsigned menu=mid(),logical=(unsigned)event;W result;
    if(!controller || r32(controller+0x178)!=0xd9 || (!extra(menu) && !factory(menu)) ||
       !creative_view(r64(controller+0x180)))
        return n12_stock_dispatch(controller,message,event);
    if((event&0xff000000u)==0x01000000u || (event&0xff000000u)==0x04000000u)
        logical=((unsigned (*)(unsigned))A(0x1b2932c))((unsigned)event)|((unsigned (*)(unsigned))A(0x1b29374))((unsigned)event);
    if(logical==0x201000cu){pump(1);if(flow.active || flow.queued || busy())return 1;}
    if(logical==0x201000fu){
        cancel();flow.leaving=1;result=n12_stock_dispatch(controller,message,event);flow.leaving=0;return result;
    }
    return n12_stock_dispatch(controller,message,event);
}

/* 只请求当前 D9 的原生 UI 刷新，不广播成像属性，不保留呈现器指针。 */
W n12_refresh(void *manager){
    W original=n12_stock_refresh(manager);unsigned menu=mid(),i,live=creative_view((W)manager);
    pump(live && (extra(menu) || factory(menu)));
    if(flow.ready_row && flow.ready_row==menu){
        flow.ready_row=0;n12_stock_preview_menu(menu);
    }
    if(!extra(menu) || (seen_state==r5_filter_command_state() && seen_sequence==r5_filter_command_sequence() &&
       seen_selected==r5_filter_selected() && seen_menu==menu && seen_mask==r5_filter_available_mask()))return original;
    for(i=0;i<15;i++){
        W view=r64((W)manager+0x338+8*i);
        if(view && r64(view)==A(0x58ca670)){
            status_only=!original && seen_menu==menu && seen_mask==r5_filter_available_mask() && seen_layout==r32(view+8);
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
            if(list && r32(list+0xd30)>0 && r32(list+0xd30)<=31)copy(saved,(void *)(list+0x30),sizeof saved);
            else list=0;
        }
    }
    n12_stock_labels(view);
    if(r64((W)view)!=A(0x58ca670))return;
    if(list && menu==mid() && layout==r32((W)view+8) && mask==r5_filter_available_mask() &&
       map==r64((W)view+0x48) && r32(map+9*16)==0x1c && list==r64(map+9*16+8)){
        copy((void *)(list+0x30),saved,sizeof saved);*(unsigned char *)(list+0xd56)=1;
    }
    seen_state=r5_filter_command_state();seen_sequence=r5_filter_command_sequence();
    seen_selected=r5_filter_selected();seen_menu=mid();seen_mask=r5_filter_available_mask();seen_layout=r32((W)view+8);
}
