#include "requests.h"

static uint16_t read16(const uint8_t *src)
{
    return (uint16_t)(src[0] | (uint16_t)src[1] << 8);
}

static void write16(uint8_t *dst, uint16_t value)
{
    dst[0] = (uint8_t)value;
    dst[1] = (uint8_t)(value >> 8);
}

static uint32_t read32(const uint8_t *src)
{
    return read16(src) | (uint32_t)read16(src + 2) << 16;
}

static R5AspectGeometry read_geometry(const uint8_t *src)
{
    return (R5AspectGeometry) {
        read16(src), read16(src + 2), read16(src + 4),
        read16(src + 6), read16(src + 8), read16(src + 10)
    };
}

int r5_aspect_heif_request(uint32_t id, uint8_t *packet, uint32_t bytes)
{
    if (!packet || bytes != R5_ASPECT_NOTIFY_BYTES || read32(packet) != 2 ||
        !(read32(packet + 4) & 4u))
        return 0;

    uint32_t primary = read32(packet + 0x1b0);
    uint32_t secondary = read32(packet + 0x1bc);
    if (primary != 4 && secondary != 4)
        return 0;
    if ((primary != 0 && primary != 2 && primary != 4) ||
        (secondary != 0 && secondary != 2 && secondary != 4) ||
        (primary == 4 && secondary == 4))
        return 0;

    static const uint16_t fields[] = {0x2b4, 0x2d4, 0x2f4};
    R5AspectGeometry cropped[3];
    for (unsigned i = 0; i < 3; ++i) {
        R5AspectGeometry source = read_geometry(packet + fields[i]);
        if (!r5_aspect_crop(id, &source, i != 0, 0, &cropped[i]))
            return 0;
    }

    /* 三组区域全部有效后才写入，RAW 的格式尺寸和缓冲区描述保留。 */
    for (unsigned i = 0; i < 3; ++i) {
        uint8_t *geometry = packet + fields[i];
        write16(geometry + 4, cropped[i].width);
        write16(geometry + 6, cropped[i].height);
        write16(geometry + 8, cropped[i].x);
        write16(geometry + 10, cropped[i].y);
    }
    uint8_t *dimensions = packet + (primary == 4 ? 0x1b6 : 0x1c2);
    write16(dimensions, cropped[0].width);
    write16(dimensions + 2, cropped[0].height);
    return 1;
}

int r5_aspect_thumbnail(uint32_t id, uint16_t *input, uint16_t *output)
{
    if (!input || !output || output[4] != 160 || output[5] != 120)
        return 0;
    R5AspectGeometry source = {input[0], input[1], input[4], input[5], input[2], input[3]};
    R5AspectGeometry cropped;
    if (!r5_aspect_crop(id, &source, 1, 0, &cropped))
        return 0;

    /* 按实际裁切后的整数尺寸居中适配，不二次应用名义比例。 */
    R5AspectRect view = {0, 0, output[4], output[5]};
    R5AspectRect fit;
    if (!r5_aspect_fit(cropped.width, cropped.height, &view, &fit))
        return 0;
    fit.width &= (uint16_t)~3u;
    fit.height &= (uint16_t)~1u;
    if (!fit.width || !fit.height)
        return 0;

    input[2] = cropped.x;
    input[3] = cropped.y;
    input[4] = input[8] = cropped.width;
    input[5] = input[9] = cropped.height;
    output[6] = (view.width - fit.width) / 2u;
    output[7] = (view.height - fit.height) / 2u;
    output[8] = fit.width;
    output[9] = fit.height;
    return 1;
}
