# 固定只读示例；不启动后台任务，不修改相机配置。
set -eu
echo A7R5_ROOT_INFO_BEGIN
/bin/cat /proc/self/status
/bin/cat /version.txt
/bin/cat /proc/version
/bin/cat /proc/mounts
echo A7R5_ROOT_INFO_END
