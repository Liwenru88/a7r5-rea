#ifndef SONY_LZ77_H
#define SONY_LZ77_H
/* Exact output_size, complete input consumption. NULL output validates without writing. */
int sony_lz77_decode(const unsigned char *, unsigned long, unsigned char *, unsigned long);
#endif
