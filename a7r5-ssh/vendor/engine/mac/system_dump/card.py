"""备用卡的普通文件材料；本模块不接受原始磁盘，不执行分区或格式化卡。"""
from pathlib import Path
import re
import struct
import subprocess
import uuid

from .images import E2FS, read_ext2_superblock


def mbr_bytes(layout, disk_id):
    if layout.get("scheme") != "MBR" or layout.get("sector_bytes") != 512:
        raise ValueError("只支持本次 512 字节 MBR 布局")
    data = bytearray(512)
    data[440:444] = uuid.UUID(disk_id).bytes[:4]
    for index, part in enumerate(layout["partitions"]):
        start, end = part["start_lba"], part["end_lba_exclusive"]
        if not 0 < start < end <= 2**32: raise ValueError("MBR 扇区越界")
        if index > 1: raise ValueError("本方案只有两个分区")
        data[446+index*16:462+index*16] = struct.pack(
            "<B3sB3sII", 0, b"\xfe\xff\xff", int(part["type"],16), b"\xfe\xff\xff", start, end-start)
    data[510:512] = b"\x55\xaa"
    return bytes(data)


def seed_ext2(image, size, card_uuid, marker):
    """只创建新的普通稀疏镜像；显式固定旧内核可审查的 ext2 特性。"""
    image = Path(image).absolute()
    if image.resolve().is_relative_to("/dev") or image.is_symlink(): raise ValueError("离线镜像不能位于设备目录")
    uuid.UUID(card_uuid)
    if not re.fullmatch(r"[0-9a-f]{32}", marker): raise ValueError("卡标记格式错误")
    if type(size) is not int or size < 16<<20 or size % 4096: raise ValueError("镜像长度无效")
    seed = image.with_suffix(".seed")
    seed.mkdir(mode=0o700)
    (seed/"A7R5_CARD_ID").write_text(marker+"\n")
    with image.open("xb") as handle: handle.truncate(size)
    command = [str(E2FS/"mke2fs"), "-q", "-F", "-t", "ext2", "-b", "4096", "-I", "128", "-N", "8192",
               "-m", "0", "-O", "none,filetype,sparse_super,large_file", "-L", "A7R5DUMP", "-U", card_uuid,
               "-d", str(seed), str(image)]
    result = subprocess.run(command,capture_output=True,text=True,timeout=180)
    if result.returncode: raise RuntimeError(f"普通 ext2 镜像构建失败：{result.stderr}")
    features = read_ext2_superblock(image)
    with image.open("rb") as handle:
        handle.seek(1024+104)
        actual = handle.read(16)
    if actual != uuid.UUID(card_uuid).bytes: raise ValueError("ext2 UUID 读回不符")
    check = subprocess.run([str(E2FS/"e2fsck"),"-fn",str(image)],capture_output=True,text=True,timeout=180)
    if check.returncode: raise ValueError("离线 ext2 结构检查未通过")
    return {"image":str(image),"bytes":size,"uuid":card_uuid,"features":features,
            "mke2fs_argv":command,"e2fsck_exit_code":check.returncode,"real_card_accessed":False}
