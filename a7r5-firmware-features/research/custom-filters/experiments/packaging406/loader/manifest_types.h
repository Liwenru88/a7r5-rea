#ifndef AF_BOOT_MANIFEST_TYPES_H
#define AF_BOOT_MANIFEST_TYPES_H
#include <stddef.h>
#include <stdint.h>
typedef struct {uint32_t offset,bytes;const uint8_t *before,*after;} BootPatch;
typedef struct {const char *path;size_t bytes;uint8_t sha[32];} BootFile;
typedef struct {uint32_t va,offset,file_bytes,memory_bytes,flags;} BootSegment;
typedef struct {uint32_t at,add;} BootReloc;
typedef struct {const char *name;uint32_t at;} BootSymbol;
typedef struct {
 BootFile file;size_t span;
 const BootSegment *segments;size_t segment_count;
 const BootReloc *relocs;size_t reloc_count;
 const BootSymbol *symbols;size_t symbol_count;
} BootModule;
typedef struct {uint32_t at,before;const char *name;uint32_t link;} BootHook;
typedef struct {uint32_t at,before;} BootCheck;
#endif
