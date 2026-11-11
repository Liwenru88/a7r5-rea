#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "r5sound_catalog.h"

typedef struct {
    char name[76];
    uint8_t *data;
    size_t size;
} StoredFile;

typedef struct {
    StoredFile files[8];
    const char *fail_write;
} MemoryStore;

static StoredFile *find_file(MemoryStore *store, const char *name) {
    for (size_t i = 0; i < sizeof(store->files) / sizeof(store->files[0]); i++) {
        if (!strcmp(store->files[i].name, name)) return &store->files[i];
    }
    return NULL;
}

static int read_file(void *context, const char *name, uint8_t *data, size_t cap, size_t *size) {
    StoredFile *file = find_file(context, name);
    if (!file) return 1;
    if (cap < file->size) return -1;
    memcpy(data, file->data, file->size);
    *size = file->size;
    return 0;
}

static int write_file(void *context, const char *name, const uint8_t *data, size_t size) {
    MemoryStore *store = context;
    if (store->fail_write && !strcmp(store->fail_write, name)) return -1;
    StoredFile *file = find_file(store, name);
    if (!file) file = find_file(store, "");
    assert(file && strlen(name) < sizeof(file->name));
    uint8_t *copy = malloc(size);
    assert(copy);
    memcpy(copy, data, size);
    free(file->data);
    strcpy(file->name, name);
    file->data = copy;
    file->size = size;
    return 0;
}

static int remove_file(void *context, const char *name) {
    StoredFile *file = find_file(context, name);
    if (!file) return -1;
    free(file->data);
    *file = (StoredFile){0};
    return 0;
}

static int read_audio(void *context, const char *name, const uint8_t *identity, size_t size,
                      unsigned step, uint8_t *out, size_t capacity, size_t *written) {
    StoredFile *file = find_file(context, name);
    if (!file || file->size != size) return -1;
    r5sound_package_info info;
    uint8_t hash[32];
    if (r5sound_package_header(file->data, size, size, &info) ||
        ss_sha256(file->data, R5SOUND_PACKAGE_HEADER_BYTES, hash) ||
        memcmp(hash, identity, sizeof(hash)) || capacity < info.encoded_bytes) return -1;
    const uint8_t *payload = file->data + R5SOUND_PACKAGE_HEADER_BYTES + (step - 1) * info.encoded_bytes;
    if (r5sound_package_audio(file->data, &info, step, payload, info.encoded_bytes)) return -1;
    memset(out, 0, capacity);
    memcpy(out, payload, info.encoded_bytes);
    *written = info.encoded_bytes;
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    static uint8_t pack[R5SOUND_PACKAGE_MAX_BYTES + 1], staging[R5SOUND_STAGING_BYTES];
    FILE *input = fopen(argv[1], "rb");
    assert(input);
    size_t size = fread(pack, 1, sizeof(pack), input);
    assert(!ferror(input) && fclose(input) == 0);
    r5sound_package_info info;
    assert(!r5sound_package_validate(pack, size, &info));
    assert(r5sound_package_validate(pack, size - 1, &info) == R5SOUND_BAD);
    pack[size - 1] ^= 1;
    assert(r5sound_package_validate(pack, size, &info) == R5SOUND_BAD);
    pack[size - 1] ^= 1;

    MemoryStore memory = {0};
    r5sound_storage store = {&memory, read_file, write_file, remove_file, NULL, read_audio};
    r5sound_catalog initial = {0}, restored, candidate;
    uint8_t index[R5SOUND_INDEX_BYTES];
    unsigned selected, volume;
    size_t written;
    assert(r5sound_catalog_load(&store, &restored, index, sizeof(index)) == R5SOUND_ABSENT);
    assert(!r5sound_selection_load(&store, &restored, &selected) && selected == 0);
    assert(!r5sound_volume_load(&store, &volume) && volume == 5);
    assert(r5sound_catalog_add(&store, &initial, 1, "Z.WAV", 5, pack, size) == R5SOUND_BAD);
    assert(!r5sound_catalog_add(&store, &initial, 1, "Z.R5S", 5, pack, size));
    assert(!r5sound_catalog_publish(&store, &initial, NULL, index, sizeof(index)));
    assert(!r5sound_selection_save(&store, &initial, 1));
    assert(!r5sound_volume_save(&store, 8));

    /* 重建目录状态，独立恢复所选身份和音量，校验单档载荷。 */
    assert(!r5sound_catalog_load(&store, &restored, index, sizeof(index)) && restored.count == 1);
    assert(!r5sound_selection_load(&store, &restored, &selected) && selected == 1);
    assert(!r5sound_volume_load(&store, &volume) && volume == 8);
    assert(!r5sound_catalog_audio(&store, &restored.entries[0], volume, staging, sizeof(staging), &written));
    assert(written == info.encoded_bytes);
    assert(!memcmp(staging, pack + R5SOUND_PACKAGE_HEADER_BYTES + 7 * written, written));
    for (size_t i = written; i < written + R5SOUND_F0_GUARD; i++) assert(!staging[i]);

    /* 构造第二个合法头部身份，模拟新文件插入后目录顺序变化。 */
    pack[40] ^= 1;
    memset(pack + 72, 0, 4);
    uint32_t crc = ss_crc32(pack, R5SOUND_PACKAGE_HEADER_BYTES);
    for (unsigned i = 0; i < 4; i++) pack[72 + i] = (uint8_t)(crc >> (8 * i));
    candidate = restored;
    assert(!r5sound_catalog_add(&store, &candidate, 0, "A.R5S", 5, pack, size));
    memory.fail_write = "R5SOUND.IDX";
    assert(r5sound_catalog_publish(&store, &candidate, &initial, index, sizeof(index)) == R5SOUND_IO);
    assert(!r5sound_catalog_load(&store, &restored, index, sizeof(index)) && restored.count == 1);
    assert(!r5sound_selection_load(&store, &restored, &selected) && selected == 1);
    assert(!r5sound_volume_load(&store, &volume) && volume == 8);

    memory.fail_write = NULL;
    assert(!r5sound_catalog_publish(&store, &candidate, &initial, index, sizeof(index)));
    assert(!r5sound_catalog_load(&store, &restored, index, sizeof(index)) && restored.count == 2);
    assert(!r5sound_selection_load(&store, &restored, &selected) && selected == 2);
    assert(!strcmp(restored.entries[selected - 1].name, "Z.R5S"));
    for (size_t i = 0; i < sizeof(memory.files) / sizeof(memory.files[0]); i++) free(memory.files[i].data);
    return 0;
}
