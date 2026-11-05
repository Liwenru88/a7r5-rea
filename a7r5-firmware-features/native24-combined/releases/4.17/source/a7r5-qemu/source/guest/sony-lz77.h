#ifndef SONY_LZ77_H
#define SONY_LZ77_H
/* Exact output_size, complete input consumption. NULL output validates without writing. */
int sony_lz77_decode(const unsigned char *, unsigned long, unsigned char *, unsigned long);
/* 原图像资源兼容性检查：独立4KiB输出块，末块允许不足一页。 */
int sony_lz77_decode_pages(const unsigned char *, unsigned long, unsigned char *, unsigned long);
#endif
