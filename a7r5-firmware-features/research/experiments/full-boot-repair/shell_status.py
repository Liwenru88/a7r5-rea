"""修复固定更新器中残留 errno 覆盖 system 退出状态的问题。"""

import hashlib


def repair_status(raw):
    if hashlib.sha256(raw).hexdigest() != '6582eba530025d17fab81420050433cd998714c922aa4c16fd4d5cdc5a378ee9':
        raise ValueError('更新器 Shell 调用库完整前像不符')
    if raw[0x189b0:0x189b4] != bytes.fromhex('41010054'):
        raise ValueError('errno 特殊分支前像不符')
    # 无条件按 system 的 wait status 判断结果；-1 也进入原有异常路径。
    result = bytearray(raw)
    result[0x189b0:0x189b4] = bytes.fromhex('0a000014')
    return bytes(result)
