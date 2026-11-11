#ifndef R5_ASPECT_CROP_ADAPTER_H
#define R5_ASPECT_CROP_ADAPTER_H
#include "geometry.h"
typedef R5AspectGeometry aspect_geometry;
#define ASPECT_GEOMETRY_AUX 0x100u
uint32_t aspect_crop_geometry(const aspect_geometry *, uint32_t, uint32_t, aspect_geometry *);
#endif
