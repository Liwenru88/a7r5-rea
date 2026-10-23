"""独立核号、一致快照与未知外设失败不能变成传输就绪。"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/'tools'))
from cp_boot_state import export_boot_state, REGIONS
from cp_native_probe import prepare_tomco, prepare_backup, run
from cp_transport_state import analyze
from media_candidate import extract
from runtime_manifest import verified_inputs


class SnapshotContract(unittest.TestCase):
    def test_independent_cpu_selection_and_read_only_commands(self):
        with tempfile.TemporaryDirectory(dir=LAB/'build') as directory:
            vm = SimpleNamespace(out=Path(directory)); calls = []

            def command(vm, request):
                calls.append(request)
                if request['execute'] == 'query-status':
                    return {'status': 'paused'}
                args = request['arguments']
                if request['execute'] == 'pmemsave':
                    Path(args['filename']).write_bytes(bytes(args['size']))
                    return {}
                if args['command-line'] == 'info registers':
                    return f'CPU#{args["cpu-index"]}\r\nR15=005cc278'
                self.assertTrue(args['command-line'].startswith('xp /5wx 0xf104'))
                return 'timer registers'

            result = export_boot_state(vm, command, 4)
            self.assertEqual([t.splitlines()[0] for t in result['cpu_registers']],
                             ['CPU#0', 'CPU#1', 'CPU#2', 'CPU#3'])
            self.assertEqual(len(result['regions']), 3)
            self.assertEqual(result['guest_memory_writes'], 0)
            self.assertFalse(result['CP_service_ready_proven'])
            self.assertTrue(all(c['execute'] in ('query-status', 'pmemsave', 'human-monitor-command') for c in calls))
            with self.assertRaisesRegex(ValueError, '拒绝覆盖'):
                export_boot_state(vm, command, 4)

    def test_wrong_cpu_or_running_guest_refused_before_memory_export(self):
        for status, text in [('running', 'CPU#0'), ('paused', 'CPU#9')]:
            with self.subTest(status=status), tempfile.TemporaryDirectory(dir=LAB/'build') as directory:
                calls = []
                def command(vm, request):
                    calls.append(request)
                    return {'status': status} if request['execute'] == 'query-status' else text
                with self.assertRaises(ValueError):
                    export_boot_state(SimpleNamespace(out=Path(directory)), command, 1)
                self.assertFalse(any(c['execute'] == 'pmemsave' for c in calls))
                self.assertFalse((Path(directory)/'cp-boot-state.json').exists())

    def test_short_export_preserves_raw_without_acceptance_receipt(self):
        with tempfile.TemporaryDirectory(dir=LAB/'build') as directory:
            def command(vm, request):
                if request['execute'] == 'query-status': return {'status': 'paused'}
                if request['execute'] == 'human-monitor-command': return 'CPU#0'
                Path(request['arguments']['filename']).write_bytes(b'partial')
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, '长度不符'):
                export_boot_state(SimpleNamespace(out=root), command, 1)
            self.assertEqual((root/REGIONS[0][2]).read_bytes(), b'partial')
            self.assertFalse((root/'cp-boot-state.json').exists())


class OriginalBootContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        files = extract(verified_inputs()['initrd'], ['cp/cpapp-b.bin', 'cp/tomco.txt','seed-backup.bin'])
        cls.cp = files['cp/cpapp-b.bin']; cls.tomco = files['cp/tomco.txt']
        cls.backup=files['seed-backup.bin']

    def test_original_configuration_and_only_explicit_watchdog_variant(self):
        self.assertEqual(prepare_tomco(self.tomco), self.tomco)
        candidate = prepare_tomco(self.tomco, True)
        differences = [n for n, (a, b) in enumerate(zip(self.tomco, candidate)) if a != b]
        self.assertEqual(differences, [self.tomco.index(b'wdt_on=1')+7])
        self.assertIn(b'usrrtn_cfggrp=2\n', candidate)
        for broken in (self.tomco[:-1], self.tomco.replace(b'cfggrp=2', b'cfggrp=1')):
            with self.assertRaises(ValueError): prepare_tomco(broken, True)

    def test_original_initializer_group_difference_and_no_false_readiness(self):
        for group in (0, 2):
            runtime = bytearray(0x500000)
            struct.pack_into('<I', runtime, 0x195e9dc-0x1500000, group)
            result = analyze(self.cp, runtime, '')
            selected = [r['name'] for r in result['initializers'] if r['selected_by_original_group']]
            self.assertEqual('OSAL_UIPC_INIT' in selected, group == 2)
            self.assertEqual('PCIEIF_INIT' in selected, group == 2)
            self.assertIn('cross_domain_callback_unregistered', result['transmission_blockers'])
            self.assertFalse(result['CP_service_ready_proven'])
            self.assertFalse(result['CP_generated_0x2040'])

    def test_first_abort_is_primary_and_callback_is_not_processing_proof(self):
        runtime = bytearray(0x500000)
        struct.pack_into('<I', runtime, 0x195e9dc-0x1500000, 2)
        struct.pack_into('<I', runtime, 0x193eb08-0x1500000, 0x1164434)
        trace = ('0x005443ac:\nwith DFSR 0x8 DFAR 0xf11e0274\n'
                 'with DFSR 0x808 DFAR 0xf102f048\n')
        result = analyze(self.cp, runtime, trace)
        self.assertEqual(result['first_data_abort']['DFAR'], '0xf11e0274')
        self.assertIn('unmodeled_MMIO:0xf11e0274', result['transmission_blockers'])
        self.assertFalse(result['AP_init_processed'])
        self.assertFalse(result['CP_service_ready_proven'])
        pci = next(r for r in result['initializers'] if r['name'] == 'PCIDMA_INIT')
        self.assertTrue(pci['entry_translation_observed'])
        for cp, ram in [(b'unknown', runtime), (self.cp, runtime[:-1])]:
            with self.assertRaises(ValueError): analyze(cp, ram, trace)

    def test_invalid_execution_combinations_rejected_before_io(self):
        for flags in ({'boot_detail': True}, {'with_tomco': True}, {'without_watchdog': True}, {'with_backup':True}):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                run(Path('/does-not-exist'), **flags)

    def test_fixed_backup_seed_is_loaded_unchanged_and_unknown_seed_refused(self):
        self.assertEqual(prepare_backup(self.backup),self.backup)
        for raw in (self.backup[:-1], bytes(len(self.backup))):
            with self.assertRaisesRegex(ValueError,'种子身份'):
                prepare_backup(raw)

    def test_low_address_translation_fault_is_not_an_unknown_mmio_register(self):
        runtime=bytearray(0x500000)
        result=analyze(self.cp,runtime,'with DFSR 0x7 DFAR 0x10\n')
        self.assertIn('translation_fault:0x10',result['transmission_blockers'])
        self.assertNotIn('unmodeled_MMIO:0x10',result['transmission_blockers'])


if __name__ == '__main__': unittest.main()
