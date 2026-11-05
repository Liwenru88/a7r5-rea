"""特殊2B的原A/Q和Gamma来源审计，输出仅限离线证据。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
FEATURE = ROOT / 'a7r5-firmware-features/custom-filters'
sys.path.insert(0, str(FEATURE))
from a7filters.cp_gamma_lineage406 import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '.local/fixed-custom-filters') or output.exists():
        raise ValueError('仅允许新的本地研究目录，不能覆盖已有证据')
    source = ROOT / '.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin'
    raw = source.read_bytes()
    report = audit(raw)
    changed = bytearray(raw)
    changed[0] ^= 1
    try:
        audit(bytes(changed))
    except ValueError:
        report['wrong_CP_rejected'] = True
    else:
        raise AssertionError('错误CP未被拒绝')
    report['implementation_sources'] = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), FEATURE / 'a7filters/cp_gamma_lineage406.py',
                  FEATURE / 'a7filters/cp_machine.py', FEATURE / 'a7filters/access_evidence.py')}
    report['input_path'] = str(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != report['CP_sha256']:
        raise ValueError('审计期间原CP来源改变')
    output.mkdir(parents=True)
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], phases=len(report['phases']),
                          producer_branches=len(report['producer_branches']),
                          bank_version_association_verified=False,
                          hardware_emulated=False, camera_io=False)))


if __name__ == '__main__':
    main()
