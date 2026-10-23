/* 只采集元数据；拒绝条件与旧109分支一致，不读取或修复密钥。 */
#ifndef KEY109_METADATA_H
#define KEY109_METADATA_H
#ifndef KEY109_LSTAT
#define KEY109_LSTAT lstat
#endif

struct key109_metadata {
    int lookup_rc;
    int lookup_errno;
    unsigned valid, mode, uid, gid;
    long long size;
};

static struct key109_metadata key109_capture(const char *path)
{
    struct stat st;
    struct key109_metadata value;
    memset(&st, 0, sizeof(st));
    memset(&value, 0, sizeof(value));
    /* 立即保存本次调用errno；成功时明确记0，不继承之前的EROFS。 */
    errno = 0;
    value.lookup_rc = KEY109_LSTAT(path, &st);
    value.lookup_errno = value.lookup_rc ? errno : 0;
    value.valid = value.lookup_rc == 0;
    if (value.valid) {
        value.mode = st.st_mode;
        value.uid = st.st_uid;
        value.gid = st.st_gid;
        value.size = st.st_size;
    }
    return value;
}

/* 位1=路径查询失败，位2=非普通文件，位4=非root，位8=组/其他权限。 */
static unsigned key109_private_reject(const struct key109_metadata *value)
{
    if (!value->valid) return 1;
    return (!S_ISREG(value->mode) ? 2U : 0U)
        | (value->uid ? 4U : 0U)
        | ((value->mode & 077) ? 8U : 0U);
}

static int key109_format(char *out, size_t capacity, const char *run,
                        const char *label, const struct key109_metadata *value,
                        unsigned private_policy)
{
    int n = snprintf(out, capacity,
        "KEY109_META1 run=%s label=%s rc=%d errno=%d valid=%u mode=%o uid=%u gid=%u size=%lld private_policy=%u reject_mask=%u\n",
        run, label, value->lookup_rc, value->lookup_errno, value->valid,
        value->mode, value->uid, value->gid, value->size, private_policy,
        private_policy ? key109_private_reject(value) : 0U);
    return n > 0 && (size_t)n < capacity ? n : -1;
}
#endif
