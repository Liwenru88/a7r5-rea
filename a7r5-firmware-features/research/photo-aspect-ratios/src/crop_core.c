/* 上游局部 view 接口复用本地六档几何，原整数比例与对齐规则不变。 */
#include "crop_core.h"
uint32_t aspect_crop_geometry(const aspect_geometry *source, uint32_t id,
                              uint32_t physical, aspect_geometry *out)
{
    return r5_aspect_crop(id & ~ASPECT_GEOMETRY_AUX, source,
                         (id & ASPECT_GEOMETRY_AUX) != 0, physical, out);
}
