/* 仅验证结构布局与槽隔离，不实现CP颜色消费者或共享堆分配器。 */
#include <stdint.h>
#include <stddef.h>
#include "r5_boot_bank.h"
#include "native_gamma.h"
#include "r5_grid_diagnostics.h"
#include "r5_look_transfer.h"

struct prototype_view { uint32_t ready,bank,selected,table,route,normal_route; };
struct prototype_restore {
    uint32_t ready,key;
    uint8_t raw[1216],work[92];
    uint32_t packed[405];
};
struct prototype_grid {
    uint32_t ready,mask;
    uint32_t packed[R5_LOOK_SLOTS][8][405];
    uint32_t restore_used,reserved;
    struct prototype_restore restore[32];
};
struct prototype_bank {
    struct r5_boot_bank values;
    struct r5_native_gamma418 gamma_first;
    uint32_t off_table[75][7];
    struct prototype_view views[R5_LOOK_SLOTS+1];
    /* 原12槽views末尾到诊断区的现有间隙，不推测其可回收。 */
    uint8_t opaque_legacy_space[1044];
    struct r5_grid_diag diag;
    struct r5_transfer_cp transfer;
    uint32_t grid_alignment;
    struct prototype_grid grid;
    struct r5_native_gamma418 gamma_extra[R5_LOOK_SLOTS-1];
    uint32_t tail_alignment;
};

#define AT(field) ((uint32_t)offsetof(struct prototype_bank,field))
/* 目标对象的常量表由ELF读取；不依赖宿主指针宽度或手算结果。 */
const uint32_t prototype_layout_constants[] = {
    R5_LOOK_SLOTS, sizeof(struct r5_native_look), sizeof(struct r5_look_set),
    sizeof(struct r5_boot_value), sizeof(struct r5_boot_bank),
    sizeof(struct r5_native_gamma418), sizeof(struct prototype_view),
    sizeof(struct prototype_restore), sizeof(struct prototype_bank),
    AT(values), AT(gamma_first), AT(off_table), AT(views),
    AT(opaque_legacy_space), AT(diag), AT(transfer), AT(grid_alignment),
    AT(grid), AT(gamma_extra), AT(tail_alignment), sizeof(struct prototype_grid)
};
_Static_assert(sizeof(struct prototype_view)==24,"view ABI");
_Static_assert(sizeof(struct prototype_restore)==2936,"restore ABI");
_Static_assert(offsetof(struct prototype_bank,grid)%8==0,"grid alignment");
#if R5_LOOK_SLOTS == 12
_Static_assert(sizeof(struct prototype_bank)==522152,"original allocation");
_Static_assert(AT(off_table)==48796 && AT(views)==50896,"original tables");
_Static_assert(AT(diag)==52252 && AT(transfer)==52324,"original controls");
_Static_assert(AT(grid)==52352 && AT(gamma_extra)==301840,"original grid");
#endif

unsigned prototype_exercise(uint8_t *memory,size_t capacity) {
    struct prototype_bank *b=(void *)memory;
    unsigned n,j; size_t i;
    if(!memory || ((uintptr_t)memory&7u) || capacity<sizeof(*b))return 0;
    for(i=0;i<sizeof(*b);i++)memory[i]=0;
    for(n=0;n<R5_LOOK_SLOTS;n++) {
        struct r5_native_gamma418 *g=n?&b->gamma_extra[n-1]:&b->gamma_first;
        uint8_t *p=(void *)&b->values.value[n];
        for(i=0;i<sizeof(b->values.value[n]);i++)p[i]=(uint8_t)(n+1);
        p=(void *)g;
        for(i=0;i<sizeof(*g);i++)p[i]=(uint8_t)(n+1);
        for(j=0;j<8*405;j++)((uint32_t *)b->grid.packed[n])[j]=n+1;
        b->views[n+1].selected=n+1;
        b->views[n+1].table=0x04000000u+(uint32_t)((uint8_t *)g-memory);
    }
    return R5_LOOK_SLOTS;
}
