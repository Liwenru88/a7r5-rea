#ifndef GPE_SPRITE_H
#define GPE_SPRITE_H
#include "gpe-copy.h"
struct gpe_sprite_plan {
    struct gpe_copy_plan memory;
    int dx, dy;
    unsigned int width, height, source_width, source_height;
    unsigned int left, top, right, bottom;
    unsigned int source_format, mode, alpha, tint, tile;
};
int gpe_plan_sprite(const unsigned int *, struct gpe_sprite_plan *);
int gpe_draw_sprite(unsigned char *, unsigned long, const unsigned char *, unsigned long,
                    const struct gpe_sprite_plan *);
int gpe_fill_rgba4444(unsigned char *, unsigned long, const unsigned int *);
#endif
