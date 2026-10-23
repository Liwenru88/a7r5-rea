# 公开研究签名身份

经持有人于 2026-10-23 明确确认，`research-signing-private.pem` 随 GitHub 源码保留。它是当前研究 DAT 的真实配对私钥，不是索尼官方私钥。`research-public.pem` 是配对公钥，`sony-original-public.pem` 是原厂验签公钥。

这一研究身份按公开身份使用：任何取得源码的人都可以用它签名，不能再以该签名证明固件来自某一位作者，也不应将它用于其他秘密或认证用途。更换身份需要同时适配公钥和相机信任规则。

本地签名工具仍要求私钥权限为 0600。Git 不保存这项权限，克隆后请运行 `chmod 600 a7r5-dat-tool/keys/research-signing-private.pem`，或执行 DAT 工具的依赖安装入口。发布检查只允许这个路径下的当前固定摘要，其他 SSH 私钥继续排除。本次没有生成新密钥、替换身份或上传 GitHub。
