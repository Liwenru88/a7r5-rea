/* AFD1名称与原厂文字显示共享的有界UTF-8契约。 */
#ifndef AF_TEXT_H
#define AF_TEXT_H
#include <stddef.h>
#include <stdint.h>
static inline int af_text_name_valid(const char *name,size_t n) {
    if (!name || !n || n>63u) return 0;
    for (size_t i=0;i<n;) {
        uint32_t cp;unsigned count;uint8_t b=(uint8_t)name[i++];
        if (b<0x80) {if (b<0x20 || b==0x7f) return 0;continue;}
        if (b>=0xc2 && b<=0xdf) {count=1;cp=b&31u;}
        else if (b>=0xe0 && b<=0xef) {count=2;cp=b&15u;}
        else if (b>=0xf0 && b<=0xf4) {count=3;cp=b&7u;}
        else return 0;
        if (count>n-i) return 0;
        for (unsigned j=0;j<count;++j) {
            b=(uint8_t)name[i++];if ((b&0xc0)!=0x80) return 0;cp=(cp<<6)|(b&63u);
        }
        if ((count==1 && cp<0x80) || (count==2 && cp<0x800) ||
            (count==3 && cp<0x10000) || cp>0x10ffff ||
            (cp>=0xd800 && cp<=0xdfff) || (cp>=0x80 && cp<0xa0)) return 0;
    }
    return 1;
}
#endif
