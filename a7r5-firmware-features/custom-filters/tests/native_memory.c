/* 独立测试ELF的内存ABI；没有设备、锁或业务成功替代。 */
#include <stddef.h>
#include <stdint.h>
void *memcpy(void *to,const void *from,size_t n) {
    for (size_t i=0;i<n;++i) ((uint8_t *)to)[i]=((const uint8_t *)from)[i];return to;
}
void *memset(void *to,int value,size_t n) {
    for (size_t i=0;i<n;++i) ((uint8_t *)to)[i]=(uint8_t)value;return to;
}
void __aeabi_memcpy(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memcpy4(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memcpy8(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memmove(void *to,const void *from,size_t n) {
    if ((uintptr_t)to>(uintptr_t)from && (uintptr_t)to-(uintptr_t)from<n) {
        while (n) { --n;((uint8_t *)to)[n]=((const uint8_t *)from)[n]; }
    } else (void)memcpy(to,from,n);
}
void __aeabi_memclr(void *to,size_t n) { (void)memset(to,0,n); }
void __aeabi_memclr4(void *to,size_t n) { (void)memset(to,0,n); }
void __aeabi_memclr8(void *to,size_t n) { (void)memset(to,0,n); }
