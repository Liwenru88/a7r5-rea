/* 最小复现旧代码：元数据检查失败时错误地留下前一步errno30。 */
#include <errno.h>
#include <stdio.h>
#include <sys/stat.h>
int main(void)
{
    struct stat st = {0};
    st.st_mode = 0100644;
    st.st_uid = 0;
    errno = 30;
    int code = (!S_ISREG(st.st_mode) || st.st_uid || (st.st_mode & 077)) ? 109 : 0;
    int recorded_errno = code ? errno : 0;
    printf("LEGACY code=%d errno=%d actual_failure=permission_predicate\n", code, recorded_errno);
    /* 期望非系统调用失败不能归因到陈旧EROFS；旧逻辑按预期失败。 */
    return recorded_errno == 0 ? 0 : 1;
}
