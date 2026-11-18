"""让统一创意外观覆盖层保留声音菜单、独立资源及动态重定位。"""


def apply(builder, runtime, replace):
    builder = replace(builder, 'RX, RW, ANCHOR = 0x8f00000, 0x8f10000, 0x8f00400',
                      'RX, RW, ANCHOR = 0x8f10000, 0x8f20000, 0x8f10400')
    builder = replace(builder, "'usleep',", "'r5sound_menu_register_extra','r5sound_rows_register_extra','r5sound_menu_row_available','usleep',")
    builder = replace(builder, "    if relas[-1] != (0x5053670,1027,", "    if relas[-5] != (0x5053670,1027,")
    builder = replace(builder, '    for i,(at,info,addend) in enumerate(relas[:-1]):',
                      "    kept=relas[:-5]+relas[-4:]\n    for i,(at,info,addend) in enumerate(kept):\n"
                      "        put(rela['sh_offset']+i*24,struct.pack('<QQq',at,info,addend),'保留声音重定位并移除滤镜父项')")
    builder = replace(builder, "    put(0x16d3b58,old_plt,'恢复原 PLT 字节')\n", '')
    builder = replace(builder, "rela['sh_size']-24 if tag==8 else 0x16d3b58", "rela['sh_size']-24 if tag==8 else plt['sh_addr']")
    builder = replace(builder, "        if s.name=='.rela.plt':put(at+16,struct.pack('<QQ',0x16d3b58,0x16d3b58),'恢复原 PLT 段表')", '')
    # 最终构建已检查所有段和权限，新增私有BSS与覆盖层之间不重叠。
    runtime = replace(runtime, 'void n12_menus(void *m,const void *b,const void *e){r5_native_menu_insert(m,b,e);}',
                      'extern void r5sound_menu_register_extra(void *),r5sound_rows_register_extra(void *);\n'
                      'extern unsigned r5sound_menu_row_available(unsigned);\n'
                      'static unsigned sound_row(unsigned id){return id-0x1680u<61u||id-0x16c0u<10u||id-0x1700u<61u||id-0x1740u<10u;}\n'
                      'void n12_menus(void *m,const void *b,const void *e){r5_native_menu_insert(m,b,e);r5sound_menu_register_extra(m);}')
    runtime = replace(runtime, '(W)n12_anchor-0x8f00400u+n', '(W)n12_anchor-0x8f10400u+n')
    runtime = replace(runtime, 'return menu==0x635?0x1f2:r5_native_menu_normalize(o,menu);',
                      'return menu==0x635?0x1f2:menu>=0x636&&menu<=0x639?menu:r5_native_menu_normalize(o,menu);')
    runtime = replace(runtime, 'r5_native_row_insert(m,pairs,pairs+COUNT);}',
                      'r5_native_row_insert(m,pairs,pairs+COUNT);r5sound_rows_register_extra(m);}')
    for function in ('n12_visible', 'n12_available'):
        runtime = replace(runtime, f'W {function}(void *o,unsigned menu){{',
                          f'W {function}(void *o,unsigned menu){{\n    if(sound_row(menu))return r5sound_menu_row_available(menu);')
    return builder, runtime
