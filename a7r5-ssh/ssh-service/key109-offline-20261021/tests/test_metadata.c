/* 本机可执行契约测试；不调用相机、Linux权限修改或SSH。 */
#define NS_HOST_TEST 1
#include "ns_abi.h"
#include <assert.h>

static struct stat sample;
static int lookup_error, lookup_calls;
static int fake_lstat(const char *path, struct stat *out)
{
    assert(!strcmp(path, "/fixed/host_ecdsa"));
    lookup_calls++;
    if (lookup_error) { errno = lookup_error; return -1; }
    *out = sample;
    /* 成功时故意遗留errno；模拟旧109报告的误导来源。 */
    errno = 30;
    return 0;
}
#define KEY109_LSTAT fake_lstat
#include "key109_metadata.h"

int main(void)
{
    struct { unsigned mode, uid, gid, expected; } cases[] = {
        {0100600, 0, 0, 0}, {0100400, 0, 99, 0},
        {0100644, 0, 0, 8}, {0100660, 0, 0, 8},
        {0100600, 501, 0, 4}, {0040700, 0, 0, 2},
        {0120777, 501, 0, 14}
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        memset(&sample, 0, sizeof(sample));
        sample.st_mode = cases[i].mode;
        sample.st_uid = cases[i].uid;
        sample.st_gid = cases[i].gid;
        sample.st_size = 321;
        lookup_error = lookup_calls = 0;
        errno = 30;
        struct key109_metadata result = key109_capture("/fixed/host_ecdsa");
        assert(result.valid && result.lookup_errno == 0 && lookup_calls == 1);
        assert(key109_private_reject(&result) == cases[i].expected);
        int old_reject = !S_ISREG(sample.st_mode) || sample.st_uid || (sample.st_mode & 077);
        assert((key109_private_reject(&result) != 0) == (old_reject != 0));
        char row[512];
        int n = key109_format(row, sizeof(row), "test", "private", &result, 1);
        assert(n > 0 && strstr(row, "errno=0 valid=1") && row[n - 1] == '\n');
        assert(key109_format(row, 8, "test", "private", &result, 1) == -1);
    }
    int errors[] = {2, 13};
    for (unsigned i = 0; i < sizeof(errors) / sizeof(errors[0]); i++) {
        lookup_error = errors[i]; lookup_calls = 0; errno = 30;
        struct key109_metadata result = key109_capture("/fixed/host_ecdsa");
        assert(result.lookup_rc == -1 && result.lookup_errno == errors[i]);
        assert(!result.valid && result.mode == 0 && result.uid == 0 && result.size == 0);
        assert(key109_private_reject(&result) == 1 && lookup_calls == 1);
    }
    puts("KEY109_CONTRACT_PASS cases=9 stale_errno_cleared=1 old_rejection_policy_preserved=1");
    return 0;
}
