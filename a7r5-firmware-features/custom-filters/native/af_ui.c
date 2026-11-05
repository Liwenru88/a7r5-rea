#include "af_ui.h"

int af_ui_resolve(uint32_t menu, AfUiRoute *output) {
    AfUiRoute route = {0};
    if (!output) return AF_INVALID;
    route.menu = menu;
    route.native_index = UINT32_MAX;
    if (menu >= 0x84c && menu <= 0x857) {
        uint32_t index = menu - 0x84c;
        route.kind = AF_UI_BUILTIN;
        route.selector = (uint32_t)af_builtin_selector(index);
        route.native_index = route.selector >= 17 ? route.selector - 1 : route.selector;
    } else if (menu >= 0x858 && menu <= 0x85d) {
        route.kind = AF_UI_USER;
        route.slot = menu - 0x858 + 1;
        route.selector = route.slot + 9;
    } else if (menu >= AF_UI_NEW_FIRST && menu <= AF_UI_NEW_LAST) {
        route.kind = AF_UI_USER;
        route.slot = menu - AF_UI_NEW_FIRST + 7;
        route.selector = route.slot + 12;
    } else if (menu == 0x85e) {
        route.kind = AF_UI_SPECIAL;
        route.selector = 16;
    } else return AF_INVALID;
    *output = route;
    return AF_OK;
}

int af_ui_item(uint32_t row, AfUiRoute *output) {
    if (row < 18) return af_ui_resolve(0x84c + row, output);
    if (row < 32) return af_ui_resolve(AF_UI_NEW_FIRST + row - 18, output);
    if (row == 32) return af_ui_resolve(0x85e, output);
    return AF_INVALID;
}

int af_ui_read(const AfCatalog *catalog, uint32_t menu, uint32_t parameter, int *output) {
    AfUiRoute route;
    AfPreset preset;
    int status;
    if (!output || parameter >= AF_PARAMETERS || af_ui_resolve(menu, &route) != AF_OK)
        return AF_INVALID;
    if (route.kind == AF_UI_BUILTIN) return AF_UI_NATIVE;
    if (route.kind != AF_UI_USER) return AF_INVALID;
    status = af_read(catalog, route.slot, 0, &preset);
    if (status != AF_OK) return status;
    *output = preset.params[parameter];
    return AF_OK;
}

int af_ui_step(AfCatalog *catalog, uint32_t menu, uint32_t parameter,
               uint32_t direction, int *output) {
    static const int low[8] = {-9,-9,-9,0,-9,0,1,0};
    static const int high[8] = {9,9,9,9,9,9,5,9};
    AfUiRoute route;
    int value, next, status;
    if (!output || parameter >= AF_PARAMETERS || direction > 1 ||
        af_ui_resolve(menu, &route) != AF_OK) return AF_INVALID;
    status = af_ui_read(catalog, menu, parameter, &value);
    if (status != AF_OK) return status;
    next = value;
    if (direction == 0 && value < high[parameter]) ++next;
    if (direction == 1 && value > low[parameter]) --next;
    if (next != value) {
        status = af_edit(catalog, route.slot, parameter, next);
        if (status != AF_OK) return status;
    }
    *output = next;
    return AF_OK;
}

static void put32(uint8_t *out, uint32_t value) {
    uint32_t i;
    for (i = 0; i < 4; ++i) out[i] = (uint8_t)(value >> (i*8));
}

int af_ui_assign(AfCatalog *catalog, uint32_t menu, uint32_t parameter,
                 int value, int *output) {
    AfUiRoute route;
    int current, status;
    if (!output || af_ui_resolve(menu,&route) != AF_OK) return AF_INVALID;
    status = af_ui_read(catalog,menu,parameter,&current);
    if (status != AF_OK) return status;
    status = af_edit(catalog,route.slot,parameter,value);
    if (status != AF_OK) return status;
    *output = value;
    return AF_OK;
}

int af_ui_snapshot(const AfCatalog *catalog, uint32_t menu,
                   const uint8_t inhibited[AF_PARAMETERS], void *output) {
    AfUiRoute route;
    AfPreset preset;
    uint32_t i;
    int status;
    uint8_t *out = output;
    if (!out || !inhibited || af_ui_resolve(menu, &route) != AF_OK) return AF_INVALID;
    if (route.kind == AF_UI_BUILTIN) return AF_UI_NATIVE;
    if (route.kind != AF_UI_USER) return AF_INVALID;
    for (i = 0; i < AF_PARAMETERS; ++i) if (inhibited[i] > 1) return AF_INVALID;
    status = af_read(catalog, route.slot, 0, &preset);
    if (status != AF_OK) return status;
    for (i = 0; i < AF_PARAMETERS; ++i) {
        put32(out+0x34+i*12, i);
        put32(out+0x38+i*12, (uint32_t)(int32_t)preset.params[i]);
        out[0x3c+i*12] = inhibited[i];
    }
    put32(out+0x94, 0);
    return AF_OK;
}
