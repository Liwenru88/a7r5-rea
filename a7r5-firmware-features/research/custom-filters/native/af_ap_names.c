#include "af_ap_names.h"
#include "af_text.h"
#include "af_ap_manage.h"
#include "af_ap_targets.h"
#include "af_ap_browser.h"
#include "af_ap_cards.h"

static uintptr_t ap_base, obj_base;
static const AfLabels *labels;
static uint32_t bound, enabled, resident_required;

static uint32_t slot_for_menu(uint32_t menu) {
    if (menu>=0x858u && menu<=0x85du) return menu-0x858u+1u;
    if (menu>=0x15d9u && menu<=0x15e6u) return menu-0x15d9u+7u;
    return 0;
}
static uint32_t menu_for_slot(uint32_t slot) {
    return slot<=6u ? 0x858u+slot-1u : 0x15d9u+slot-7u;
}
static uint32_t native_title(uint32_t menu) {
    uint32_t (*get)(uint32_t)=(uint32_t (*)(uint32_t))(ap_base+0x1bd5508u);
    return get(menu);
}
static int label(uint32_t slot, const char **name) {
    size_t bytes;
    return af_labels_read(labels,slot,name,&bytes)==AF_OK &&
           af_text_name_valid(*name,bytes) && (*name)[bytes]=='\0';
}
static int private_menu(uint32_t menu) {
    return af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) ||
           af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu);
}
static const char *compact_text(uint32_t resource) {
    if ((resource&0xffff0000u)!=AF_AP_NAMES_COMPACT_FIRST) return 0;
    uint32_t menu=AF_MANAGE_MENU_ROOT+(resource&0xffffu);
    const uint32_t *(*get)(void)=(const uint32_t *(*)(void))(ap_base+0x28b0464u);
    const uint32_t *language=get();
    uint32_t chinese=language && *language==25u;
    static const char *const action[2][4]={
        {"Save","Copy","Load","New"},{"保存","另存","导入","新建"}};
    /* 原字符重载同步深拷贝；UI单拥有者串行调用，不保留此临时序号。 */
    static char number[4];
    if (menu==AF_MANAGE_MENU_ROOT) return af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST);
    if (menu>=AF_MANAGE_MENU_SAVE && menu<=AF_MANAGE_MENU_CREATE)
        return action[chinese][menu-AF_MANAGE_MENU_SAVE];
    if (menu==AF_MANAGE_MENU_CLEAR) return chinese?"清空":"Clear";
    if (menu==AF_MANAGE_MENU_RENAME) return chinese?"改名":"Name";
    if (menu==AF_MANAGE_MENU_EXPORT) return chinese?"导出":"Exp.";
    const char *command=af_ap_targets_command_text(menu);
    if(command)return command;
    if (menu>=AF_TARGETS_SLOT_FIRST && menu<AF_TARGETS_SLOT_FIRST+AF_USERS) {
        uint32_t slot=menu-AF_TARGETS_SLOT_FIRST+1u;
        number[0]='C';number[1]=(char)('0'+slot/10u);
        number[2]=(char)('0'+slot%10u);number[3]=0;return number;
    }
    if (menu>=AF_BROWSER_MENU_FILE_FIRST && menu<AF_BROWSER_MENU_FILE_FIRST+AF_MEDIA_MAX) {
        uint32_t index=menu-AF_BROWSER_MENU_FILE_FIRST+1u;
        number[0]=(char)('0'+index/10u);number[1]=(char)('0'+index%10u);
        number[2]=0;return number;
    }
    if (menu==AF_TARGETS_ROOT) return chinese?"槽位":"Slot";
    if (menu==AF_BROWSER_MENU_ROOT) return chinese?"文件":"Files";
    if (menu==AF_BROWSER_MENU_PREVIOUS) return chinese?"上页":"Prev";
    if (menu==AF_BROWSER_MENU_NEXT) return chinese?"下页":"Next";
    if (menu==AF_BROWSER_MENU_CANCEL || menu==AF_TARGETS_CANCEL) return chinese?"取消":"Back";
    if (af_ap_cards_is_id(menu))return af_ap_cards_text(af_ap_cards_compact(menu));
    /* 任何未分配的私有标记都不能落入原UXC索引。 */
    return "?";
}
int af_ap_names_bind(const AfApNamesBinding *binding) {
    if (bound) return AF_BUSY;
    if (!binding || binding->version!=AF_AP_NAMES_BIND_VERSION ||
        binding->bytes!=sizeof(*binding) || !binding->labels ||
        ((uintptr_t)binding->labels%_Alignof(AfLabels)) ||
        !binding->ap_base || !binding->obj_base || (binding->ap_base&4095u) || (binding->obj_base&4095u) ||
        binding->ap_base>UINTPTR_MAX-0x8e84000u || binding->obj_base>UINTPTR_MAX-0x300000u)
        return AF_INVALID;
    /* 此处只校验入口；完整镜像摘要和加载权限由外层同源装载器保护。 */
    if (*(const uint32_t *)(binding->ap_base+0x2208e8cu)!=0x97e7319fu ||
        *(const uint32_t *)(binding->ap_base+0x220c8a0u)!=0x97e7231au ||
        *(const uint32_t *)(binding->ap_base+0x1885b38u)!=0x97f9566eu ||
        *(const uint32_t *)(binding->ap_base+0x28b0464u)!=0xf002b260u ||
        *(const uint32_t *)(binding->obj_base+0x16d2a4u)!=0xa9bd7bfdu ||
        *(const uint32_t *)(binding->obj_base+0x16d498u)!=0xa9bd7bfdu ||
        *(const uint32_t *)(binding->obj_base+0x16bc64u)!=0xf84d0c01u)
        return AF_STALE;
    ap_base=binding->ap_base;obj_base=binding->obj_base;
    labels=binding->labels;enabled=0;bound=1;
    return AF_OK;
}
int af_ap_names_enable(uint32_t value) {
    if (!bound || value>1) return AF_INVALID;
    enabled=value;
    if (value) resident_required=1;
    return AF_OK;
}
int af_ap_names_detach_allowed(void) { return resident_required ? AF_BUSY : AF_OK; }
uint32_t af_ap_names_title(uint32_t menu) {
    if (!bound) __builtin_trap();
    if(enabled && af_ap_manage_menu_is_id(menu))return af_ap_manage_menu_name(menu);
    if(enabled && af_ap_targets_is_id(menu))return af_ap_targets_name(menu);
    if(enabled && af_ap_browser_is_id(menu))return af_ap_browser_name(menu);
    if(enabled && af_ap_cards_is_id(menu))return af_ap_cards_name(menu);
    uint32_t slot=slot_for_menu(menu);
    const char *name;
    if (enabled && slot && label(slot,&name)) return AF_AP_NAMES_TOKEN_FIRST+slot-1u;
    return native_title(menu);
}
uint32_t af_ap_names_compact(uint32_t menu) {
    if (!bound) __builtin_trap();
    if(af_ap_cards_is_id(menu))return af_ap_cards_compact(menu);
    if (private_menu(menu)) return AF_AP_NAMES_COMPACT_FIRST+menu-AF_MANAGE_MENU_ROOT;
    return native_title(menu);
}
void af_ap_names_sprite(void *sprite, uint32_t resource) {
    if (!bound) __builtin_trap();
    void (*stock)(void *,uint32_t)=(void (*)(void *,uint32_t))(obj_base+0x16d498u);
    const uint32_t *(*language)(void)=(void *) (ap_base+0x28b0464u);
    const char *management=resource==AF_AP_NAMES_FILTER_TITLE?(*language()==25?"滤镜名称":"Filter Name"):compact_text(resource);
    if(!management)management=af_ap_manage_menu_text(resource);
    if(!management && af_ap_targets_is_token(resource))management=af_ap_targets_text(resource);
    if(!management && af_ap_browser_is_token(resource))management=af_ap_browser_text(resource);
    if(!management && af_ap_cards_is_token(resource))management=af_ap_cards_text(resource);
    if(management) {
        /* 即使后续禁用，既有管理标记也必须留在字符路径，不能流入原UXC库。 */
        void (*text)(void *,const char *)=(void (*)(void *,const char *))(obj_base+0x16d2a4u);
        resident_required=1;text(sprite,management);return;
    }
    if (resource>=AF_AP_NAMES_TOKEN_FIRST && resource<AF_AP_NAMES_TOKEN_FIRST+AF_USERS) {
        uint32_t slot=resource-AF_AP_NAMES_TOKEN_FIRST+1u;
        const char *name;
        if (enabled && label(slot,&name)) {
            void (*text)(void *,const char *)=(void (*)(void *,const char *))(obj_base+0x16d2a4u);
            void *(*record)(void *)=(void *(*)(void *))(obj_base+0x16bc64u);
            text(sprite,name);
            if (record(sprite)) return;
        }
        resource=native_title(menu_for_slot(slot));
    }
    stock(sprite,resource);
}
