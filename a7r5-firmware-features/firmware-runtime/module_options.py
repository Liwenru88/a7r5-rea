"""只在独立版的构建副本上关闭选定能力。默认路径保持原构建输入。"""
from hashlib import sha256

from stability import replace_exact

OPTIONS = ('sd-import', 'preview', 'group-memory', 'tuning', 'selection-restore')


def edit(source, pairs):
    for old, new in pairs:
        source = replace_exact(source, old, new)
    return source


def derived(work, disabled, ledger):
    rules = {}
    if 'sd-import' in disabled:
        rules['import/r5_stage413_thread.c'] = [
            ('if(!cold){result=R5_ABSENT;goto done;}',
             '/* 冷启动与暖恢复均只读取有效机内库。 */\n'
             '    if(1){result=R5_ABSENT;goto done;}'),
        ]
    selection = 'selection-restore' not in disabled
    tuning = 'tuning' not in disabled
    if not selection or not tuning:
        changes = rules.setdefault('import/r5_filter_runtime423.c', [])
        if not selection:
            changes.append(('unsigned n=0;int rc=r5_filter_selection_load(d,&n);',
                '/* 新进程初值为零，暖恢复沿用当前已应用项。 */\n'
                '    (void)d;unsigned n=r5_filter_selected();int rc=R5_ABSENT;'))
        if not selection and not tuning:
            changes.append(('static int storage(unsigned n,int begin){',
                'static int storage(unsigned n,int begin){\n'
                '/* 无磁盘日志写入，仍保留 AP／CP 应用事务和回退。 */\n'
                '    if(!begin){saved=n;saved_valid=1;loaded_log=0;}return 0;'))
        elif not selection:
            changes.append(('if(begin){rc=r5_tune_begin(&d);if(!rc)rc=r5_filter_selection_begin(&d);}\n'
                            '    else {rc=r5_tune_save(&d);if(!rc)rc=r5_filter_selection_save(&d,n);if(!rc)r5_tune_finish(&d);}',
                            '/* 独立微调通过单文件原子提交。 */\n'
                            '    if(begin)rc=0;else rc=r5_tune_save(&d);'))
        else:
            changes.append(('if(begin){rc=r5_tune_begin(&d);if(!rc)rc=r5_filter_selection_begin(&d);}\n'
                            '    else {rc=r5_tune_save(&d);if(!rc)rc=r5_filter_selection_save(&d,n);if(!rc)r5_tune_finish(&d);}',
                            'if(begin)rc=r5_filter_selection_begin(&d);else rc=r5_filter_selection_save(&d,n);'))
    if not tuning:
        rules['import/r5_tune425.c'] = [
            ('int rc,restoring=0;STORE(&ready,0);', 'int rc,restoring=0;\n'
             ' /* 禁用时不读取或迁移旧微调，参数报文保持原生。 */\n'
             ' STORE(&ready,0);STORE(&status,0);return 0;\n STORE(&ready,0);'),
        ]
    for relative, pairs in rules.items():
        path = work / relative
        source = path.read_text()
        result = edit(source, pairs)
        path.write_text(result)
        ledger.append(dict(path=relative, stage='feature-options',
                           before_sha256=sha256(source.encode()).hexdigest(),
                           after_sha256=sha256(result.encode()).hexdigest()))


def menu(source, disabled):
    if 'group-memory' in disabled:
        source = edit(source, [
            ('static unsigned last_applied_factory,last_applied_custom;\nstatic uint32_t last_applied_bank;\n', ''),
            ('        if(flow.slot && flow.bank==r5_filter_bank_crc()){\n'
             '            last_applied_custom=flow.slot;last_applied_bank=flow.bank;\n        }\n', ''),
            ('    if(!busy() && !r5_filter_factory_reset_needed()){\n'
             '        unsigned state=r5_filter_command_state(),slot=r5_filter_selected();\n'
             '        if(slot && (state==0 || state==2) && !r5_filter_pending() && allowed(slot)){\n'
             '            last_applied_custom=slot;last_applied_bank=r5_filter_bank_crc();\n'
             '        }else if(!slot && !previous && state<4 && !flow.active && !flow.queued && !flow.ready_row){\n'
             '            unsigned applied=factory_applied_mid();\n'
             '            if(applied)last_applied_factory=applied;\n        }\n    }\n', ''),
            ('    if(tabs.group){\n        if(last_applied_bank==r5_filter_bank_crc() && allowed(last_applied_custom))\n'
             '            target=FIRST+last_applied_custom-1;\n'
             '    }else if(factory_eligible(last_applied_factory))target=last_applied_factory;\n'
             '    if(!target)target=tab_first(tabs.group);',
             '    /* 每次切组均按当前可用性定位首项。 */\n    target=tab_first(tabs.group);'),
        ])
    if 'preview' in disabled:
        source = edit(source, [
            ('void n12_preview(void *context,unsigned selector){if(tab_suppressed())return;',
             'void n12_preview(void *context,unsigned selector){if(selector>=19 || tabs.active)return;'),
            ('void n12_preview_menu(unsigned menu){', 'static void preview_target(unsigned menu){'),
            ('W n12_alias(unsigned menu)', 'void n12_preview_menu(unsigned menu){if(!tabs.active && !extra(menu))preview_target(menu);}\nW n12_alias(unsigned menu)'),
            ('        n12_preview_menu(menu);\n        factory_preview_ready(menu);',
             '        preview_target(menu);\n        factory_preview_ready(menu);'),
            ('!tab_suppressed() && r5_tune_changed(slot)',
             '!tab_suppressed() && r5_filter_selected()==slot && r5_tune_changed(slot)'),
        ])
    if 'tuning' in disabled:
        source = edit(source, [
            ('    if(custom() && allowed(mid()-FIRST+1)){',
             '    if(0 && custom() && allowed(mid()-FIRST+1)){'),
        ])
    if 'tuning' in disabled or 'preview' in disabled:
        guard = 'custom()' if 'tuning' in disabled else 'custom() && !current_applied(mid())'
        source = edit(source, [
            ('        if(logical==left){tab_switch(controller);return 1;}',
             '        unsigned right=layout?0x2010003u:0x2010009u;\n'
             f'        if(logical-right<=2u && ({guard}))return 1;\n'
             '        if(logical==left){tab_switch(controller);return 1;}'),
        ])
    return source
