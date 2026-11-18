/* 私有菜单已取消；保留原厂构造函数委派，不再构造私有对象池。 */
#include <stdint.h>
#include <stddef.h>
extern char r5_filter_page_anchor[];
typedef uint64_t (*F6)(uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t);
static uintptr_t A(uintptr_t n){return (uintptr_t)r5_filter_page_anchor-0x9000000u+n;}
uint64_t r5_filter_parent_presenter425(uint64_t i,uint64_t v,uint64_t c,uint64_t p,uint64_t s,uint64_t l){
    return ((F6)A(0x1d90c7c))(i,v,c,p,s,l);
}
uint64_t r5_filter_controller425(uint64_t i,uint64_t m,uint64_t c,uint64_t s,uint64_t p,uint64_t l){
    return ((F6)A(0x1d2e488))(i,m,c,s,p,l);
}
uint64_t r5_filter_presenter425(uint64_t i,uint64_t v,uint64_t c,uint64_t p,uint64_t s,uint64_t l){
    return ((F6)A(0x1e1e1a4))(i,v,c,p,s,l);
}
const char *r5_filter_page_text425(unsigned id){(void)id;return 0;}
int r5_filter_parent_refresh425(void){return -1;}
