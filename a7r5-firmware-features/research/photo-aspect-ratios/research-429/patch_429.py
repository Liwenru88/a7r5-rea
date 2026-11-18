"""将 4.28 build-tree 补丁为 4.29（增加 6 种自定义照片纵横比并修复 CP/AP 崩溃问题）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label} 匹配次数异常: {count}")
    return text.replace(old, new, 1)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_tree(tree: Path) -> dict:
    native = tree / "a7r5-firmware-features" / "native24-combined"
    unified_c = native / "runtime" / "unified-look.c"
    build_py = native / "build.py"

    # 1. 在 unified-look.c 的 n12_text() 入口拦截 0x0200ab60..0x0200ab65 纵横比标签，
    #    避免修改 nflasha15 中的 68 个语言 .uxc 文件。
    c_src = unified_c.read_text(encoding="utf-8")
    c_target = 'const char *n12_text(unsigned resource){\n    if(resource==TAB_TEXT)return "[原厂外观]  自定义滤镜";'
    c_replace = (
        'const char *n12_text(unsigned resource){\n'
        '    switch(resource){\n'
        '    case 0x0200ab60u:return "17:6";\n'
        '    case 0x0200ab61u:return "65:24";\n'
        '    case 0x0200ab62u:return "5:4";\n'
        '    case 0x0200ab63u:return "7:6";\n'
        '    case 0x0200ab64u:return "1.91:1";\n'
        '    case 0x0200ab65u:return "2.35:1";\n'
        '    }\n'
        '    if(resource==TAB_TEXT)return "[原厂外观]  自定义滤镜";'
    )
    c_new = _replace_exact(c_src, c_target, c_replace, "unified-look.c n12_text")
    unified_c.write_text(c_new, encoding="utf-8")

    # 2. 修改 native24-combined/build.py：接入 CP 常驻纵横比、AP 4.29、IPSX 图标、libmpr.so 与 AV-CAM.BIN。
    b_src = build_py.read_text(encoding="utf-8")

    b_src = _replace_exact(
        b_src,
        "    final_cp, record['lens_AF'] = lens.apply_lens_af(cp_raw, patches, cp_folder, source_sha=patches.digest(cp_raw))\n"
        "    (output / 'cpapp-b.bin').write_bytes(final_cp)",
        "    final_cp, record['lens_AF'] = lens.apply_lens_af(cp_raw, patches, cp_folder, source_sha=patches.digest(cp_raw))\n"
        "    cp_res = load(HERE / 'release429/cp_resident.py', 'release429_cp_resident')\n"
        "    cp_aspect_elf = cp_res.compile_resident_cp(work / 'aspect-cp-429')\n"
        "    final_cp, record['aspect_CP'] = cp_res.apply_resident_cp(final_cp, cp_aspect_elf, source_sha=patches.digest(final_cp))\n"
        "    (output / 'cpapp-b.bin').write_bytes(final_cp)",
        "build.py CP hook",
    )

    b_src = _replace_exact(
        b_src,
        "    ap_path, unified_receipt = unified.build(final_ap, output / 'unified', audit_path)\n"
        "    shutil.copyfile(ap_path, output / 'appFw.so')",
        "    ap_path, unified_receipt = unified.build(final_ap, output / 'unified', audit_path)\n"
        "    ap_429 = load(HERE / 'release429/build_ap_429.py', 'release429_ap')\n"
        "    ap_aspect_bytes, _, record['aspect_AP'] = ap_429.patch_ap_429(ap_path.read_bytes(), work / 'aspect-ap-429')\n"
        "    ap_path = output / 'appFw.so'\n"
        "    ap_path.write_bytes(ap_aspect_bytes)",
        "build.py AP hook",
    )

    b_src = _replace_exact(
        b_src,
        "    ext2 = load(FEATURE / 'upstream/firmware/r5/src/lib/ext2read.py', 'native24_stock_resource_reader')\n"
        "    usr = ext2.Ext2(str((inputs_directory or baseline / 'work/inputs') / 'nflasha15'))\n"
        "    try:\n"
        "        for name, expected in icons12.SOURCES.items():\n"
        "            original = usr.read_inode(usr.walk(name.removeprefix('usr/')))\n"
        "            if patches.digest(original) != expected:\n"
        "                raise ValueError('原厂图形资源身份不符：' + name)\n"
        "            candidate, proof = icons24.append_icons(original)\n"
        "            (output / Path(name).name).write_bytes(candidate)\n"
        "            icon_reports[name] = proof\n"
        "    finally:",
        "    dat_tool_dir = next(p / 'a7r5-dat-tool' for p in HERE.parents if (p / 'a7r5-dat-tool').is_dir())\n"
        "    if str(dat_tool_dir) not in sys.path:\n"
        "        sys.path.insert(0, str(dat_tool_dir))\n"
        "    aspect_res = load(HERE.parent / 'photo-aspect-ratios/src/build_resources.py', 'release429_aspect_icons')\n"
        "    aspect_mpr = load(HERE.parent / 'photo-aspect-ratios/src/build_mpr.py', 'release429_aspect_mpr')\n"
        "    ext2 = load(FEATURE / 'upstream/firmware/r5/src/lib/ext2read.py', 'native24_stock_resource_reader')\n"
        "    usr = ext2.Ext2(str((inputs_directory or baseline / 'work/inputs') / 'nflasha15'))\n"
        "    try:\n"
        "        for name, expected in icons12.SOURCES.items():\n"
        "            original = usr.read_inode(usr.walk(name.removeprefix('usr/')))\n"
        "            if patches.digest(original) != expected:\n"
        "                raise ValueError('原厂图形资源身份不符：' + name)\n"
        "            candidate, proof = icons24.append_icons(original)\n"
        "            candidate = aspect_res.icons(candidate)\n"
        "            proof['aspect_icons_sha256'] = patches.digest(candidate)\n"
        "            (output / Path(name).name).write_bytes(candidate)\n"
        "            icon_reports[name] = proof\n"
        "        raw_mpr = usr.read_inode(usr.walk('lib/libmpr.so'))\n"
        "        patched_mpr, record['aspect_mpr'] = aspect_mpr.build_mpr(raw_mpr, work / 'aspect-mpr')\n"
        "        (output / 'libmpr.so').write_bytes(patched_mpr)\n"
        "    finally:",
        "build.py icons+mpr hook",
    )

    b_src = _replace_exact(
        b_src,
        "    record['components'] = {name: {'bytes': (output/name).stat().st_size, 'sha256': checker.sha(output/name)}\n"
        "                            for name in ['appFw.so','cpapp-b.bin', *[Path(x).name for x in icons12.SOURCES]]}",
        "    avcam_src = (inputs_directory or baseline / 'work/inputs') / 'AV-CAM.BIN'\n"
        "    comp_names = ['appFw.so', 'cpapp-b.bin', 'libmpr.so', *[Path(x).name for x in icons12.SOURCES]]\n"
        "    if avcam_src.exists():\n"
        "        aspect_avcam = load(HERE.parent / 'photo-aspect-ratios/src/build_avcam.py', 'release429_aspect_avcam')\n"
        "        (work / 'aspect-avcam').mkdir(parents=True, exist_ok=True)\n"
        "        avcam_bundle = aspect_avcam.compile_avcam(work / 'aspect-avcam')\n"
        "        patched_avcam, record['aspect_avcam'] = aspect_avcam.apply_avcam(avcam_src.read_bytes(), avcam_bundle)\n"
        "        (output / 'AV-CAM.BIN').write_bytes(patched_avcam)\n"
        "        comp_names.append('AV-CAM.BIN')\n"
        "    record['components'] = {name: {'bytes': (output/name).stat().st_size, 'sha256': checker.sha(output/name)}\n"
        "                            for name in comp_names}",
        "build.py components+avcam hook",
    )

    build_py.write_text(b_src, encoding="utf-8")

    # 3. 将纵横比私有行号从 0x1600..0x1605 迁移至空闲区间 0x1640..0x1645，
    #    避免与 appFw.so 中仍挂钩的 r5_filter_row_parent / r5_filter_row_normalize (0x1600..0x160c) 冲突。
    aspect_src = tree / "a7r5-firmware-features" / "photo-aspect-ratios" / "src"
    ap_menu_c = aspect_src / "ap_menu.c"
    ap_menu_s = aspect_src / "ap_menu.S"
    ap_state_c = aspect_src / "ap_state.c"
    build_ap_py = aspect_src / "build_ap.py"

    ap_menu_c.write_text(
        _replace_exact(ap_menu_c.read_text(encoding="utf-8"), "ASPECT_PRIVATE_FIRST = 0x1600,", "ASPECT_PRIVATE_FIRST = 0x1640,", "ap_menu.c 0x1640"),
        encoding="utf-8",
    )
    ap_state_c.write_text(
        _replace_exact(
            ap_state_c.read_text(encoding="utf-8"),
            "else if (row - 0x1600u < R5_ASPECT_COUNT - 4u) id = row - 0x1600u + 4u;",
            "else if (row - 0x1640u < R5_ASPECT_COUNT - 4u) id = row - 0x1640u + 4u;",
            "ap_state.c 0x1640",
        ),
        encoding="utf-8",
    )
    s_txt = ap_menu_s.read_text(encoding="utf-8")
    if s_txt.count("#0x600") != 3:
        raise ValueError(f"ap_menu.S #0x600 匹配次数异常: {s_txt.count('#0x600')}")
    ap_menu_s.write_text(s_txt.replace("#0x600", "#0x640"), encoding="utf-8")
    build_ap_py.write_text(
        _replace_exact(build_ap_py.read_text(encoding="utf-8"), "FIRST_ROW = 0x1600", "FIRST_ROW = 0x1640", "build_ap.py FIRST_ROW"),
        encoding="utf-8",
    )

    return {
        "schema": "release429-tree-patch/1",
        "base": "4.28-427-af-debounce-20261117",
        "modified": {
            "a7r5-firmware-features/native24-combined/runtime/unified-look.c": _sha(unified_c),
            "a7r5-firmware-features/native24-combined/build.py": _sha(build_py),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.c": _sha(ap_menu_c),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.S": _sha(ap_menu_s),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_state.c": _sha(ap_state_c),
            "a7r5-firmware-features/photo-aspect-ratios/src/build_ap.py": _sha(build_ap_py),
        },
    }
