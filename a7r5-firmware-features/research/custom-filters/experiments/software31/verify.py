"""只编译和宿主文件测试；不启动虚拟机、外设模拟器或设备连接。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
FEATURE = ROOT / 'a7r5-firmware-features/custom-filters'
NATIVE = FEATURE / 'native'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--recipe-bridge', action='store_true', help='配对编译完整配方真实消息入口；不安装或开放成像')
    parser.add_argument('--capture-copies', action='store_true', help='编译四处真实复制入口及输入版本伴随；不执行目标')
    parser.add_argument('--bootstrap-only', action='store_true', help='启动库依赖构建；不运行需要历史临时ld的裸AP/CP探针')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.local/fixed-custom-filters'):
        raise ValueError('回执只写本任务隔离目录')
    output.mkdir(parents=True, exist_ok=False)
    paths = (sorted(NATIVE.glob('*.[chS]')) + sorted(NATIVE.glob('*.ld')) +
             sorted((FEATURE / 'tests').glob('*.py')) + sorted((FEATURE / 'tests').glob('*.c')) + [Path(__file__)])
    paths += sorted((FEATURE/'tests/fixtures').glob('*source_lock.json'))
    paths += sorted((FEATURE/'tests/fixtures').glob('*encoding.json'))
    paths += sorted((FEATURE/'tests/fixtures').glob('*.h'))
    paths += sorted((FEATURE/'assets').glob('*'))
    paths += sorted((FEATURE/'tools').glob('*.py'))
    paths += sorted((FEATURE/'tools').glob('*.c'))
    paths += sorted((FEATURE/'experiments/packaging406').rglob('*.py'))
    paths += sorted((FEATURE/'experiments/packaging406/cp_carve406/bootstrap').glob('*'))
    linker_root = ROOT/'.local/fixed-custom-filters/build-17-runtime-final'
    if not args.bootstrap_only:
        paths += [linker_root/'ap.ld', linker_root/'cp.ld']
    before = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    commands = []
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'a7r5-desktop/prepared/engine/site'), str(FEATURE)))

    def run(argv):
        start = time.monotonic()
        result = subprocess.run(list(map(str, argv)), cwd=ROOT, env=environment, capture_output=True, text=True)
        commands.append(dict(argv=list(map(str, argv)), exit_code=result.returncode,
                             seconds=time.monotonic()-start, stdout=result.stdout, stderr=result.stderr))
        (output / 'commands.json').write_text(json.dumps(commands, ensure_ascii=False, indent=2)+'\n')
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)

    ui_sources = ('af_slots.c', 'af_ui.c', 'af_ap_ui.c', 'af_ap_ui.S', 'af_labels.c', 'af_ap_names.c',
                  'af_ap_manage.c', 'af_ap_targets.c', 'af_ap_browser.c', 'af_ap_cards.c', 'af_ap_media.c')
    for mode in ('legacy', 'dynamic'):
        directory = output / mode
        directory.mkdir()
        objects = []
        for name in ui_sources:
            obj = directory / (name+'.o')
            flags = ['clang', '--target=aarch64-none-elf', '-O2', '-ffreestanding', '-fno-builtin',
                     '-fno-stack-protector', '-Wall', '-Wextra', '-Werror', '-I'+str(NATIVE)]
            if mode == 'dynamic':
                flags += ['-DAF_AP_DYNAMIC', '-fPIC']
            run(flags+['-c', NATIVE/name, '-o', obj])
            objects.append(obj)
        flags = ['/opt/homebrew/opt/lld/bin/ld.lld', '--build-id=none']
        if mode == 'dynamic':
            flags += ['-shared', '-Bsymbolic', '--no-undefined', '-z', 'max-page-size=4096']
        run(flags+['-T', NATIVE/('af_ap_ui_dynamic.ld' if mode == 'dynamic' else 'af_ap_ui.ld'),
                   *objects, '-o', directory/'ap-ui.elf'])

    # 复用已经核对的同包glibc ABI，只执行链接，不运行目标文件。
    exports = output / 'service.exports'
    exports.write_text('{ global: af_media_read; af_media_scan; af_repository_service_*; '
                      'af_repository_recipe_*; af_reference_joint_*; af_reference_map_eval; '
                      'af_reference_import_bind; af_reference_import_info; '
                      'af_recipe_tx_*; local: *; };\n')
    backend = ('af_repository_service.c', 'af_repository_import.c', 'af_repository.c', 'af_media.c',
               'af_posix.c', 'af_slots.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c',
               'af_ui.c', 'af_persist.c', 'af_store.c', 'af_document.c', 'af_record.c', 'af_sha256.c',
               'af_import.c', 'af_joint.c', 'af_joint_fit.c', 'af_joint_basis.c', 'af_joint_asset.c', 'af_joint_report.c',
               'af_grid.c', 'af_grid_fit.c', 'af_cube.c', 'af_repository_recipe.c',
               'af_recipe_transport.c', 'af_reference_joint.c', 'af_edit_joint.c', 'af_color406.c',
               'af_edit_cp_gamma.c', 'af_gamma406.c', 'af_edit_reference.c', 'af_edit_chain.c',
               'af_edit_gamma_table.c', 'af_edit_matrix_table.c', 'af_edit_context.c',
               'af_reference_assets.c', 'af_reference_domain.c', 'af_reference_samples.c',
               'af_reference_import.c', 'af_reference_grid.c', 'af_reference_blob.S')
    run(['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
         '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-nostdlib', '-ffreestanding', '-fno-builtin',
         '-fno-stack-protector', '-mno-outline-atomics', '-shared', '-fPIC', '-std=c11', '-O2',
         '-Wall', '-Wextra', '-Werror', '-ffp-contract=off', '-DAF_TARGET_GLIBC225', '-DAF_JOINT_BASIS406',
         '-DAF_REFERENCE_IMPORT406', *(['-DAF_RECIPE_BRIDGE406'] if args.recipe_bridge else []), '-I'+str(NATIVE),
         '-Wl,--no-undefined', '-Wl,-soname,libaf_repository_media.so', '-Wl,--version-script='+str(exports),
         *[NATIVE/name for name in backend], ROOT/'a7r5-qemu/sdk/lib/libc-2.25.so',
         ROOT/'a7r5-qemu/sdk/lib/ld-2.25.so', '-o', output/'libaf_repository_media.so'])

    # 新配对通信与具体UI回调胶合一起链接；只检查固定映射研究ELF，不执行它。
    for kind in (() if args.bootstrap_only else ('ap', 'cp')):
        directory=output/(kind+'-requests');directory.mkdir();objects=[]
        names=['af_slots.c','af_apply_wire.c','af_handshake.c']
        if kind=='ap':
            names += ['af_hs_ap406.c','af_hs_ap406.S','af_runtime.c','af_runtime_ap406.c',
                      'af_factory406.c','af_imaging406.c']
            target=['--target=aarch64-none-elf']
            exported=['af_ap_hs_begin','af_ap_hs_poll','af_ap_runtime_gate','af_ap_runtime_poll',
                      'af_ap_runtime_send_preset','af_ap_runtime_release_preset',
                      'af_ap_runtime_preset_capabilities','af_ap_runtime_preset_status','af_imaging406_binding']
            if args.recipe_bridge:
                names += ['af_recipe_transport.c','af_sha256.c']
                exported += ['af_ap_runtime_send_recipe','af_ap_runtime_send_stored_recipe',
                             'af_ap_runtime_recipe_result','af_imaging406_bind_recipe_source']
        else:
            names += ['af_hs_cp406.c','af_hs_cp406.S','af_cp406_state.c','af_cp406_state.S',
                      'af_cp_override406.c','af_cp_override406.S']
            target=['--target=armv7a-none-eabi','-mthumb','-march=armv7-a','-mfpu=none',
                    '-mfloat-abi=soft','-fno-vectorize','-fno-slp-vectorize']
            exported=['af_cp_hs_configure','af_cp_runtime_gate','af_cp_override406_snapshot_gate']
            # 完整配方软件核心单独链接；没有接原handler、安装gate或授予RW空间。
            names += ['af_recipe_transport.c','af_joint_asset.c','af_joint.c','af_sha256.c']
            exported += ['af_recipe_rx_init','af_recipe_rx_frame','af_recipe_rx_validate',
                         'af_recipe_rx_take','af_recipe_rx_finish','af_recipe_rx_release']
            if args.recipe_bridge:
                names += ['af_cp_recipe406.c']
                exported += ['af_cp_recipe406_bind','af_cp_recipe406_finish','af_cp_recipe406_release']
            if args.capture_copies:
                names += ['af_cp_input406.c','af_cp_copy406.c','af_cp_copy406.S']
                exported += ['af_cp_copy406_gate','af_cp_override406_read_input']
        for src in [*[NATIVE/name for name in names],FEATURE/'tests/native_memory.c']:
            obj=directory/(src.name+'.o');objects.append(obj)
            run(['clang',*target,'-O2','-ffreestanding','-fno-builtin','-fno-stack-protector',
                 '-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror',
                 '-DAF_RUNTIME406=1','-DAF_CP_PRESET406=1','-DAF_FACTORY_RESTORE406=1','-DAF_SNAPSHOT_OVERLAY406=1',
                 *(['-DAF_RECIPE_BRIDGE406=1'] if args.recipe_bridge else []),
                 *(['-DAF_CP_CAPTURE_INPUT406=1','-DAF_CP_CAPTURE_COPIES406=1']
                   if kind=='cp' and args.capture_copies else []),
                 '-I'+str(NATIVE),'-c',src,'-o',obj])
        run(['/opt/homebrew/opt/lld/bin/ld.lld','-T',linker_root/(kind+'.ld'),
             '--gc-sections','--build-id=none',*['--undefined='+name for name in exported],
             *objects,'-o',directory/(kind+'-requests.elf')])
    for name in ('af_edit_front.c','af_legacy406.c','af_grid406_source.c','af_fsys406.c','af_media_snapshot406.c'):
        run(['clang','--target=aarch64-none-elf','-std=c11','-O2','-ffreestanding',
             '-ffp-contract=off','-fno-fast-math','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
             '-c',NATIVE/name,'-o',output/(name+'.o')])

    # 选择受影响的宿主契约，不运行含Unicorn/QEMU的目标执行测试。
    tests = ('test_joint_incremental', 'test_native_joint', 'test_import_incremental', 'test_native_import',
             'test_joint_basis', 'test_import_basis_binding', 'test_repository_basis_integration',
             'test_joint_asset_workspace', 'test_recipe_transport', 'test_repository_recipe',
             'test_native_tone_asset406', 'test_cp_native_bank406', 'test_cp_jobs406',
             'test_cp_components406', 'test_cp_native_binding406', 'test_user20_protocol406',
             'test_cp_capture406', 'test_cp_capture_fields406', 'test_cp_capture_target406',
             'test_cp_capture_components406',
             'test_cp_capture_color406', 'test_cp_capture_color_components406',
             'test_cp_request_snapshot406', 'test_cp_request_target406',
             'test_stored_recipe_stream406', 'test_loader_recipe_source406',
             'test_explicit_native_exit406', 'test_loader_startup406',
             'test_ap_disabled_passthrough406',
             'test_reference_joint', 'test_reference_import_pipeline',
             'test_reference_to_receiver', 'test_reference_domain', 'test_reference_samples',
             'test_reference_assets', 'test_reference_default_import', 'test_loader_reference_binding',
             'test_recipe_freestanding_link',
             'test_native_repository', 'test_native_repository_import', 'test_native_repository_schemas',
             'test_native_repository_export', 'test_repository_import_service', 'test_native_media',
             'test_prepared_recipe_import', 'test_recipe_file_tool', 'test_desktop_fit', 'test_desktop_gamma', 'test_sector_reference', 'test_ap_browser',
             'test_ap_media', 'test_ap_media_importer', 'test_ap_media_importer_busy',
             'test_media_provider','test_media_provider_alias','test_media_snapshot406','test_fsys406',
             'test_media_card_service','test_ap_cards','test_ap_cards_flow','test_loader_picker','test_fsys406_utf8','test_fsys406_dates',
             'test_ap_import_progress', 'test_ap_import_targets', 'test_ap_lut_management', 'test_lut_management', 'test_ap_manage',
             'test_ap_menu_intent', 'test_ap_export_menu', 'test_ap_targets', 'test_ap_targets_overwrite',
             'test_ap_targets_clear', 'test_ap_preset_sender', 'test_cp_preset_ingress',
             'test_ap_recipe_sender', 'test_cp_recipe406', 'test_recipe_actual_ingress',
             'test_cp_carve406', 'test_recipe_build_pair',
             'test_cp_input406', 'test_cp_snapshot_copy406', 'test_cp_image_copy406', 'test_cp_copy_fault406',
             'test_native_persistence', 'test_native_labels', 'test_ap_imaging_requests', 'test_ap_imaging_provider',
             'test_ap_overlay_ui', 'test_ap_legacy_overlay',
             'test_factory406', 'test_factory_protocol', 'test_factory_roundtrip',
             'test_ap_lifecycle', 'test_ap_post_registration', 'test_storage406',
             'test_snapshot_protocol', 'test_cp_override406', 'test_cp_version_atomic', 'test_ui_factory_pending',
             'test_grid406_source', 'test_edit_front',
             'test_legacy406', 'test_native_handshake', 'test_native_runtime')
    selected = [FEATURE/'tests'/(name+'.py') for name in tests]
    selected += [FEATURE/'tests/test_loader_maps406.py',FEATURE/'tests/test_ui_icons.py']
    if args.bootstrap_only:
        # 仅对本次启动库依赖验证，不把缺失的旧颜色参考材料伪装为通过。
        selected=[FEATURE/'tests'/(name+'.py') for name in (
            'test_loader_maps406','test_loader_startup406','test_loader_reference_binding',
            'test_loader_recipe_source406','test_loader_picker','test_ui_icons',
            'test_request_bindings','test_candidate_preflight','test_recipe_build_pair',
            'test_marker_bootstrap','test_ap_lifecycle','test_ap_post_registration',
            'test_storage406')]
    if args.recipe_bridge:
        # 完整配方候选必须验证同一ST导入结果到原生组件的连续链路。
        selected.append(FEATURE/'tests/test_st_lut_pipeline406.py')
    run([ROOT/'.venv/bin/python', '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *selected,
         str(FEATURE/'tests/test_native_apply.py')+'::test_native_transaction_contract_and_independent_wire_bytes', '--tb=short'])
    after = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    if before != after:
        raise RuntimeError('验证期间源码变化，不能复用本次证据')
    artifact_paths=[output/'dynamic/ap-ui.elf',output/'legacy/ap-ui.elf',output/'libaf_repository_media.so']
    if not args.bootstrap_only:
        artifact_paths += [output/'ap-requests/ap-requests.elf',output/'cp-requests/cp-requests.elf']
    artifacts = {str(p.relative_to(output)): dict(sha256=digest(p), bytes=p.stat().st_size)
                 for p in artifact_paths}
    checks = re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+)\}',
                        (NATIVE/'af_ap_ui.c').read_text().split('static const AfApCheck checks[] = {', 1)[1].split('};', 1)[0])
    if len(checks) != 132:
        raise RuntimeError('AP前像声明数量变化')
    receipt = dict(status='PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS', source_sha256=before,
                   artifacts=artifacts, commands=commands, AP_preimage_declarations=132,
                   hardware_simulation=False, VM_started=False, camera_io=False,
                   actual_camera_color_model=False, actual_EVF_JPG_acceptance=False,
                   recipe_bridge_enabled=args.recipe_bridge,
                   capture_copies_enabled=args.capture_copies,
                   ST_photo_chain_software_verified=args.recipe_bridge,
                   bootstrap_only=args.bootstrap_only,
                   AP_CP_probe_ELFs_linked=not args.bootstrap_only,
                   host_test_scope='bootstrap_dependencies_and_runtime_contracts' if args.bootstrap_only else 'full_selected_feature_suite',
                   installable_firmware=False)
    (output/'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(status=receipt['status'], artifacts=artifacts,
                          tests=commands[-1]['stdout'].strip()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
