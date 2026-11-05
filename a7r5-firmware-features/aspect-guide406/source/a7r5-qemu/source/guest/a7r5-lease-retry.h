/* 只重试已释放全部租约的暂时忙；协议、身份与清理错误直接返回。 */
#ifndef A7R5_LEASE_RETRY_H
#define A7R5_LEASE_RETRY_H
static int a7r5_retry_capture(int (*attempt)(void *), void *context,
                              int (*pause_us)(unsigned int), unsigned int *tries) {
    for (*tries=1; *tries<=1000; ++*tries) {
        int result=attempt(context);
        if (result!=-2) return result;
        if (*tries==1000 || pause_us(1000)) return -1;
    }
    return -1;
}
#endif
