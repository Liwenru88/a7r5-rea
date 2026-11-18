/* 同修改版4.06的固定机内目录准入；不创建仓库、不写文件、不修改权限。 */
#ifndef AF_STORAGE406_H
#define AF_STORAGE406_H
enum AfStorage406Result {
    AF_STORAGE406_OK=0, AF_STORAGE406_INVALID=-1, AF_STORAGE406_IO=-2,
    AF_STORAGE406_IDENTITY=-3, AF_STORAGE406_READONLY=-4,
    AF_STORAGE406_CAPACITY=-5, AF_STORAGE406_FORMAT=-6
};
/* 成功才写parent；返回只读、CLOEXEC的/setting目录fd，调用者负责close。
 * 必须在后续写入获准时才传给仓库；本函数本身绝不mkdir/marker/chmod。
 * /proc缺mnt_id、非匹配挂载、目录非私有或容量不足均拒绝，不回退别的目录。 */
int af_storage406_open(int *parent);
#endif
