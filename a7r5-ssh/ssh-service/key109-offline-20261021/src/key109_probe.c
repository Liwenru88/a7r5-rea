/* 固定两路径的元数据探针；只有lstat和stdout，不打开或读取私钥。 */
#include "ns_abi.h"
#include "key109_metadata.h"
#include "probe_config.h"

static int output(const char *raw, size_t n)
{
    while (n) {
        ssize_t count = write(1, raw, n);
        if (count <= 0) return -1;
        raw += count;
        n -= (size_t)count;
    }
    return 0;
}

int main(int argc, char **argv)
{
    (void)argv;
    if (argc != 1) return 64;
#ifndef NS_HOST_TEST
    if (getuid() || geteuid()) return 65;
#endif
    const char begin[] = "KEY109_BEGIN1 run=" KEY109_RUN "\n";
    if (output(begin, sizeof(begin) - 1)) return 71;
    const char *paths[] = {KEY109_INSTALL, KEY109_INSTALL "/host_ecdsa"};
    const char *labels[] = {"install", "private"};
    for (unsigned i = 0; i < 2; i++) {
        char row[512];
        struct key109_metadata value = key109_capture(paths[i]);
        int n = key109_format(row, sizeof(row), KEY109_RUN, labels[i], &value, i == 1);
        if (n < 0 || output(row, (size_t)n)) return 72;
    }
    const char end[] = "KEY109_END1 run=" KEY109_RUN " samples=2 key_content_read=0 key_writes=0 ssh_started=0\n";
    return output(end, sizeof(end) - 1) ? 73 : 0;
}
