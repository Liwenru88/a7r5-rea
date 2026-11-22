"""将 4.28 build-tree 补丁为 4.31（增加 6 种自定义照片纵横比与 JPEG/HEIF 全功能裁切、原厂创意外观放行及 AP BSS 扩容）。"""

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

    # 1. 在 unified-look.c 中：
    #    (a) 修复 bank_unavailable_only 隔离逻辑：当自定义滤镜库激活失败 (command_state==7)
    #        且当前未选中自定义滤镜 (r5_filter_selected()==0 && available_mask==0) 时，
    #        不锁死原厂创意外观的预览、选择与调参；
    #    (b) 在 n12_text() 入口拦截 0x0200ab60..0x0200ab65 纵横比标签，
    #        避免修改 nflasha15 中的 68 个语言 .uxc 文件。
    c_src = unified_c.read_text(encoding="utf-8")
    c_src = _replace_exact(
        c_src,
        "static int parameter_locked(void){return r5_filter_recovery_required() || r5_filter_command_state()==6 || r5_filter_factory_reset_needed() || custom() || (factory(mid()) &&\n"
        "    (flow.active || flow.queued || busy() || r5_filter_selected()));}",
        "static int bank_unavailable_only(void){return r5_filter_command_state()==7 && !r5_filter_selected() && !r5_filter_available_mask();}\n"
        "static int parameter_locked(void){return (r5_filter_recovery_required() && !bank_unavailable_only()) || r5_filter_command_state()==6 || r5_filter_factory_reset_needed() || custom() || (factory(mid()) &&\n"
        "    (flow.active || flow.queued || busy() || r5_filter_selected()));}",
        "unified-look.c parameter_locked",
    )
    c_src = _replace_exact(
        c_src,
        "static int release_native(void){\n"
        "    if(flow.leaving)return 0;\n"
        "    if(!factory(mid()))return !flow.active && !flow.queued && !busy() && !r5_filter_recovery_required() && r5_filter_command_state()!=6 && !r5_filter_factory_reset_needed() && !r5_filter_selected() && !r5_filter_pending();\n"
        "    if(!flow.active && !flow.queued && !busy() && !r5_filter_recovery_required() && r5_filter_command_state()!=6 && !r5_filter_selected() && !r5_filter_pending()){",
        "static int release_native(void){\n"
        "    if(flow.leaving)return 0;\n"
        "    if(!factory(mid()))return !flow.active && !flow.queued && !busy() && (!r5_filter_recovery_required() || bank_unavailable_only()) && r5_filter_command_state()!=6 && !r5_filter_factory_reset_needed() && !r5_filter_selected() && !r5_filter_pending();\n"
        "    if(!flow.active && !flow.queued && !busy() && (!r5_filter_recovery_required() || bank_unavailable_only()) && r5_filter_command_state()!=6 && !r5_filter_selected() && !r5_filter_pending()){",
        "unified-look.c release_native",
    )
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

    # 2. 修改 native24-combined/build.py：接入 CP 常驻纵横比、AP 4.31、IPSX 图标、libmpr.so 与 AV-CAM.BIN。
    b_src = build_py.read_text(encoding="utf-8")

    b_src = _replace_exact(
        b_src,
        "    final_cp, record['lens_AF'] = lens.apply_lens_af(cp_raw, patches, cp_folder, source_sha=patches.digest(cp_raw))\n"
        "    (output / 'cpapp-b.bin').write_bytes(final_cp)",
        "    final_cp, record['lens_AF'] = lens.apply_lens_af(cp_raw, patches, cp_folder, source_sha=patches.digest(cp_raw))\n"
        "    cp_res = load(HERE / 'release431/cp_resident.py', 'release431_cp_resident')\n"
        "    cp_aspect_elf = cp_res.compile_resident_cp(work / 'aspect-cp-431')\n"
        "    final_cp, record['aspect_CP'] = cp_res.apply_resident_cp(final_cp, cp_aspect_elf, source_sha=patches.digest(final_cp))\n"
        "    (output / 'cpapp-b.bin').write_bytes(final_cp)",
        "build.py CP hook",
    )

    b_src = _replace_exact(
        b_src,
        "    ap_path, unified_receipt = unified.build(final_ap, output / 'unified', audit_path)\n"
        "    shutil.copyfile(ap_path, output / 'appFw.so')",
        "    ap_path, unified_receipt = unified.build(final_ap, output / 'unified', audit_path)\n"
        "    ap_431 = load(HERE / 'release431/build_ap_431.py', 'release431_ap')\n"
        "    ap_aspect_bytes, _, record['aspect_AP'] = ap_431.patch_ap_431(ap_path.read_bytes(), work / 'aspect-ap-431')\n"
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
        "    aspect_res = load(HERE.parent / 'photo-aspect-ratios/src/build_resources.py', 'release431_aspect_icons')\n"
        "    aspect_mpr = load(HERE.parent / 'photo-aspect-ratios/src/build_mpr.py', 'release431_aspect_mpr')\n"
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
        "        aspect_avcam = load(HERE.parent / 'photo-aspect-ratios/src/build_avcam.py', 'release431_aspect_avcam')\n"
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
        _replace_exact(
            _replace_exact(
                _replace_exact(
                    build_ap_py.read_text(encoding="utf-8"),
                    "FIRST_ROW = 0x1600",
                    "FIRST_ROW = 0x1640",
                    "build_ap.py FIRST_ROW",
                ),
                "SELECTION = 0x8f12b60",
                "SELECTION = 0x8f13000",
                "build_ap.py SELECTION 0x8f13000",
            ),
            "rx_base, rw_base, state_size = 0x8f00000 + shift, 0x8f10000 + shift, 0x2e00",
            "rx_base, rw_base, state_size = 0x8f00000 + shift, 0x8f10000 + shift, 0x3300",
            "build_ap.py state_size 0x3300",
        ),
        encoding="utf-8",
    )

    # 3b. 扩容 AP BSS 隔离带：将画幅状态区从 0x8f12b60 后移至 0x8f13000（距 unified-look BSS 末尾 0x8f12b50 留出 1200B 余量）。
    ap_ld = aspect_src / "ap.ld"
    ap_ld_src = ap_ld.read_text(encoding="utf-8")
    for old, new, label in (
        ("aspect_selection = 0x8f12b60;", "aspect_selection = 0x8f13000;", "ap.ld aspect_selection"),
        ("aspect_registrations = 0x8f12b68;", "aspect_registrations = 0x8f13008;", "ap.ld aspect_registrations"),
        ("aspect_guide_slots = 0x8f12bc8;", "aspect_guide_slots = 0x8f13068;", "ap.ld aspect_guide_slots"),
        ("aspect_session = 0x8f12d00;", "aspect_session = 0x8f131a0;", "ap.ld aspect_session"),
    ):
        ap_ld_src = _replace_exact(ap_ld_src, old, new, label)
    ap_ld.write_text(ap_ld_src, encoding="utf-8")

    # 3c. 在 AV-CAM.BIN 的 avcam_views.c 中补齐 APS-C S (3120x2080) 六档裁切尺寸识别，
    #     使 HEIF (4:2:0 / 4:2:2) 及 RAW+HEIF 在全画幅 L/M/S 与 APS-C L/M/S 下全部生效。
    avcam_views_c = aspect_src / "avcam_views.c"
    av_src = avcam_views_c.read_text(encoding="utf-8")
    av_src = _replace_exact(
        av_src,
        "/* 与已核实 Sony L/M/S 的 crop_core 输出及 AP 精确尺寸识别表一致。 */\n"
        "uint32_t aspect_avcam_heif_id(const uint8_t *ctx, uint32_t slot)\n"
        "{\n"
        "    static const uint16_t sizes[R5_CUSTOM_SIZE_COUNT][2] = R5_CUSTOM_SIZE_PAIRS;\n"
        "    const uint8_t *s = ctx + 0x440;\n"
        "    const uint8_t *f = s + (slot == 1 ? 0xa4 : 0x224);\n"
        "    if ((slot != 1 && slot != 16) || word(f) != 4 || word(f + 8) != 0) return 0;\n"
        "    const uint16_t *wh = (const uint16_t *)(s + (slot == 1 ? 0x3a4 : 0x3a8));\n"
        "    for (uint32_t i = 0; i < R5_CUSTOM_SIZE_COUNT; ++i)\n"
        "        if (wh[0] == sizes[i][0] && wh[1] == sizes[i][1]) return i / 3 + 4;\n"
        "    return 0;\n"
        "}",
        "/* 统一匹配全画幅 L/M/S（含 APS-C L/M）与 APS-C S (3120x2080) 的六档自定义裁切宽高。 */\n"
        "static uint32_t aspect_match_custom_wh(uint32_t w, uint32_t h)\n"
        "{\n"
        "    static const uint16_t sizes[R5_CUSTOM_SIZE_COUNT][2] = R5_CUSTOM_SIZE_PAIRS;\n"
        "    static const uint16_t apsc_s[6][2] = {\n"
        "        {3120, 1104}, {3120, 1152}, {2608, 2080},\n"
        "        {2432, 2080}, {3120, 1632}, {3120, 1328}\n"
        "    };\n"
        "    for (uint32_t i = 0; i < R5_CUSTOM_SIZE_COUNT; ++i)\n"
        "        if (w == sizes[i][0] && h == sizes[i][1]) return i / 3 + 4;\n"
        "    for (uint32_t i = 0; i < 6; ++i)\n"
        "        if (w == apsc_s[i][0] && h == apsc_s[i][1]) return i + 4;\n"
        "    return 0;\n"
        "}\n\n"
        "/* 与已核实 Sony L/M/S 及 APS-C S 的 crop_core 输出一致。 */\n"
        "uint32_t aspect_avcam_heif_id(const uint8_t *ctx, uint32_t slot)\n"
        "{\n"
        "    const uint8_t *s = ctx + 0x440;\n"
        "    const uint8_t *f = s + (slot == 1 ? 0xa4 : 0x224);\n"
        "    if ((slot != 1 && slot != 16) || word(f) != 4 || word(f + 8) != 0) return 0;\n"
        "    const uint16_t *wh = (const uint16_t *)(s + (slot == 1 ? 0x3a4 : 0x3a8));\n"
        "    return aspect_match_custom_wh(wh[0], wh[1]);\n"
        "}",
        "avcam_views.c aspect_avcam_heif_id",
    )
    av_src = _replace_exact(
        av_src,
        "uint32_t aspect_avcam_raw_crop(const uint8_t *ctx, uint32_t *width, uint32_t *height)\n"
        "{\n"
        "    static const uint16_t sizes[R5_CUSTOM_SIZE_COUNT][2] = R5_CUSTOM_SIZE_PAIRS;\n"
        "    const uint8_t *info = ctx + 0x440;\n"
        "    if (word(info + 0xa4) != 2 && word(info + 0x224) != 2) return 0;\n"
        "    void *base = *(void **)(ctx + 0x840);\n"
        "    if (!base) return 0;\n"
        "    void *headers[19];\n"
        "    aspect_native_raw_headers((void *)info, base, headers);\n"
        "    const uint8_t *extra = headers[18];\n"
        "    if (!extra) return 0;\n"
        "    /* RAW preview WH already frozen by CP into native EMB header.\n"
        "     * SonyCrop/DefaultCrop remain full frame and are deliberately not read. */\n"
        "    uint32_t w = word(extra + 0xa50), h = word(extra + 0xa54);\n"
        "    for (uint32_t i = 0; i < R5_CUSTOM_SIZE_COUNT; ++i) {\n"
        "        if (w == sizes[i][0] && h == sizes[i][1]) {\n"
        "            *width = w; *height = h;\n"
        "            return i / 3 + 4;\n"
        "        }\n"
        "    }\n"
        "    return 0;\n"
        "}",
        "uint32_t aspect_avcam_raw_crop(const uint8_t *ctx, uint32_t *width, uint32_t *height)\n"
        "{\n"
        "    const uint8_t *info = ctx + 0x440;\n"
        "    if (word(info + 0xa4) != 2 && word(info + 0x224) != 2) return 0;\n"
        "    void *base = *(void **)(ctx + 0x840);\n"
        "    if (!base) return 0;\n"
        "    void *headers[19];\n"
        "    aspect_native_raw_headers((void *)info, base, headers);\n"
        "    const uint8_t *extra = headers[18];\n"
        "    if (!extra) return 0;\n"
        "    /* RAW preview WH already frozen by CP into native EMB header.\n"
        "     * SonyCrop/DefaultCrop remain full frame and are deliberately not read. */\n"
        "    uint32_t w = word(extra + 0xa50), h = word(extra + 0xa54);\n"
        "    uint32_t id = aspect_match_custom_wh(w, h);\n"
        "    if (id) {\n"
        "        *width = w; *height = h;\n"
        "    }\n"
        "    return id;\n"
        "}",
        "avcam_views.c aspect_avcam_raw_crop",
    )
    avcam_views_c.write_text(av_src, encoding="utf-8")

    # 3d. 修复 AV-CAM.BIN 的 avcam_views.S：原厂 0x200734 入口的 w0 为编码通道号 (0/1)，
    #     实际槽位 (1 主槽 / 16 副槽) 位于调用者寄存器 w21（与 Hearts-Ace 4.65 avcam_heif.S 及原厂反汇编一致）。
    avcam_views_s = aspect_src / "avcam_views.S"
    av_s_src = avcam_views_s.read_text(encoding="utf-8")
    av_s_src = _replace_exact(
        av_s_src,
        "    /* 槽位是原生入口的 w0 参数，不能依赖调用者的 x21。 */\n"
        "    mov w3, w0",
        "    /* 原厂 0x200734 的 w0 为通道号 (0/1)，实际槽位 (1/16) 位于调用者 w21。 */\n"
        "    mov w3, w21",
        "avcam_views.S mov w3, w21",
    )
    avcam_views_s.write_text(av_s_src, encoding="utf-8")

    # 4. 加固冷启动 AP->CP 自定义滤镜探测超时与激活重试窗口：
    #    - r5_stage413_probe.c：单次 CP 探测超时从 1s (11次) 放宽至 3s (31次)，避免开机早期 CP 响应稍慢误判超时；
    #    - r5_stage413_thread.c：冷启动 activate() 重试次数从 3 次放宽至 8 次，覆盖开机早期 CP 堆波动窗口。
    probe_c = native / "runtime" / "r5_stage413_probe.c"
    p_src = probe_c.read_text(encoding="utf-8")
    p_src = _replace_exact(
        p_src,
        "    for(poll=0;poll<11;poll++) {\n"
        "        s->polls=poll+1;\n"
        "        if(!r5_session_current()||now_ms(clock,&now)||now<last||now<start||now-start>=1000u){s->result=3;goto done;}",
        "    for(poll=0;poll<31;poll++) {\n"
        "        s->polls=poll+1;\n"
        "        if(!r5_session_current()||now_ms(clock,&now)||now<last||now<start||now-start>=3000u){s->result=3;goto done;}",
        "r5_stage413_probe.c 3s timeout",
    )
    p_src = _replace_exact(
        p_src,
        "        if(poll==10||sleep(&delay,0)){s->result=3;goto done;}",
        "        if(poll==30||sleep(&delay,0)){s->result=3;goto done;}",
        "r5_stage413_probe.c poll==30",
    )
    probe_c.write_text(p_src, encoding="utf-8")

    thread_c = native / "runtime" / "r5_stage413_thread.c"
    t_src = thread_c.read_text(encoding="utf-8")
    t_src = _replace_exact(
        t_src,
        "            for(poll=0;poll<3&&r5_session_current();poll++){\n"
        "                activate(s,cold);",
        "            for(poll=0;poll<8&&r5_session_current();poll++){\n"
        "                activate(s,cold);",
        "r5_stage413_thread.c 8 retries",
    )
    thread_c.write_text(t_src, encoding="utf-8")

    return {
        "schema": "release431-tree-patch/1",
        "base": "4.28-427-af-debounce-20261117",
        "modified": {
            "a7r5-firmware-features/native24-combined/runtime/unified-look.c": _sha(unified_c),
            "a7r5-firmware-features/native24-combined/runtime/r5_stage413_probe.c": _sha(probe_c),
            "a7r5-firmware-features/native24-combined/runtime/r5_stage413_thread.c": _sha(thread_c),
            "a7r5-firmware-features/native24-combined/build.py": _sha(build_py),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap.ld": _sha(ap_ld),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.c": _sha(ap_menu_c),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.S": _sha(ap_menu_s),
            "a7r5-firmware-features/photo-aspect-ratios/src/ap_state.c": _sha(ap_state_c),
            "a7r5-firmware-features/photo-aspect-ratios/src/avcam_views.c": _sha(avcam_views_c),
            "a7r5-firmware-features/photo-aspect-ratios/src/avcam_views.S": _sha(avcam_views_s),
            "a7r5-firmware-features/photo-aspect-ratios/src/build_ap.py": _sha(build_ap_py),
        },
    }
