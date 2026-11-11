/* 原厂纵横比菜单只将私有编号保存在本模块。 */
#include <stdint.h>
#include "geometry.h"

enum {
    ASPECT_LEAF = 33,
    ASPECT_STOCK_FIRST = 126,
    ASPECT_STOCK_COUNT = R5_ASPECT_NATIVE_COUNT,
    ASPECT_PRIVATE_FIRST = 0x1600,
    ASPECT_PRIVATE_COUNT = R5_ASPECT_COUNT - R5_ASPECT_NATIVE_COUNT,
    ASPECT_TOTAL = R5_ASPECT_COUNT,
};

struct row {
    uint32_t id, identity, label;
    uint32_t stock_fields[29];
};

struct registration {
    uint32_t key, reserved;
    const struct row *value;
};

struct pair {
    uint32_t key, value;
};

struct list_row {
    uint32_t kind, reserved;
    uint32_t *model;
};

extern const struct row r5_aspect_rows[ASPECT_TOTAL];
extern uint32_t aspect_selection;
extern struct registration aspect_registrations[ASPECT_PRIVATE_COUNT];
extern unsigned stock_get(void);
extern void stock_set(unsigned value);
extern void stock_commit(unsigned row_id);
extern void stock_list_commit(unsigned row_id);
extern void prior_register(void *tree, const void *first, const void *end);
extern void stock_register(void *tree, const void *first, const void *end);
extern void stock_parent_register(void *tree, const void *first, const void *end);
extern void stock_alias_register(void *tree, const void *first, const void *end);
extern void r5_aspect_stock_list(void *context, struct list_row *rows, const uint32_t *params);

void r5_aspect_register(void *tree, const void *first, const void *end)
{
    prior_register(tree, first, end);
    for (unsigned i = 0; i < ASPECT_PRIVATE_COUNT; ++i) {
        const struct row *option = &r5_aspect_rows[ASPECT_STOCK_COUNT + i];
        aspect_registrations[i] = (struct registration){option->id, 0, option};
    }
    stock_register(tree, aspect_registrations, aspect_registrations + ASPECT_PRIVATE_COUNT);
}

#define PAIR(i, value) {ASPECT_PRIVATE_FIRST + (i), (value)}
#define ALIAS(i) PAIR(i, ASPECT_PRIVATE_FIRST + (i))
#define PARENT(i) PAIR(i, ASPECT_LEAF)

void r5_aspect_parent_register(void *tree, const void *first, const void *end)
{
    static const struct pair parents[] = {
        PARENT(0), PARENT(1), PARENT(2), PARENT(3), PARENT(4), PARENT(5),
    };
    stock_parent_register(tree, first, end);
    stock_parent_register(tree, parents, parents + ASPECT_PRIVATE_COUNT);
}

void r5_aspect_alias_register(void *tree, const void *first, const void *end)
{
    /* 原厂别名按区间起点查找，先封住原表末尾到新增编号之间的空洞。 */
    static const struct pair aliases[] = {
        {ASPECT_PRIVATE_FIRST - 1, 0x15d8},
        ALIAS(0), ALIAS(1), ALIAS(2), ALIAS(3), ALIAS(4), ALIAS(5),
        {ASPECT_PRIVATE_FIRST + ASPECT_PRIVATE_COUNT, 0x15d8},
    };
    stock_alias_register(tree, first, end);
    stock_alias_register(tree, aliases, aliases + sizeof(aliases) / sizeof(*aliases));
}

void r5_aspect_list(void *context, struct list_row *rows, const uint32_t *params)
{
    r5_aspect_stock_list(context, rows, params);
    if (params[2] != ASPECT_LEAF || params[1] > 98)
        return;
    const struct list_row *row = &rows[params[1]];
    uint32_t *model = row->model;
    if (row->kind != 28 || !model || model[0xd30 / 4] != ASPECT_TOTAL)
        return;

    for (unsigned i = 0; i < ASPECT_TOTAL; ++i) {
        model[0x030 / 4 + i] = UINT32_MAX;
        model[0x430 / 4 + i] = UINT32_MAX;
        model[0x830 / 4 + i] = r5_aspect_rows[i].label;
    }
}

unsigned r5_aspect_get(void)
{
    unsigned stock = stock_get();
    unsigned selected = __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE) & 0xff;
    if (stock == 0 && selected - ASPECT_STOCK_COUNT < ASPECT_PRIVATE_COUNT)
        return selected;
    return stock;
}

static void publish(unsigned value)
{
    unsigned selected = value < ASPECT_STOCK_COUNT ? 0 : value;
    uint32_t old = __atomic_load_n(&aspect_selection, __ATOMIC_RELAXED);
    /* 快速往返同一档时，旧取景结果也必须失效。 */
    while ((old & 0xff) != selected) {
        uint32_t next = ((old & ~0xffu) + 0x100u) | selected;
        if (__atomic_compare_exchange_n(&aspect_selection, &old, next, 0,
                                        __ATOMIC_RELEASE, __ATOMIC_RELAXED))
            break;
    }
}

void r5_aspect_set(unsigned value)
{
    if (value >= ASPECT_TOTAL)
        return;
    publish(value);
    stock_set(value < ASPECT_STOCK_COUNT ? value : 0);
}

unsigned r5_aspect_project_apply(unsigned row)
{
    if (row - ASPECT_STOCK_FIRST < ASPECT_STOCK_COUNT) {
        publish(0);
    } else if (row - ASPECT_PRIVATE_FIRST < ASPECT_PRIVATE_COUNT) {
        publish(row - ASPECT_PRIVATE_FIRST + ASPECT_STOCK_COUNT);
        return ASPECT_STOCK_FIRST;
    }
    return row;
}

void r5_aspect_commit(unsigned row)
{
    stock_commit(r5_aspect_project_apply(row));
}

void r5_aspect_list_commit(unsigned row)
{
    if (row - ASPECT_PRIVATE_FIRST < ASPECT_PRIVATE_COUNT)
        r5_aspect_commit(row);
    else
        stock_list_commit(r5_aspect_project_apply(row));
}
