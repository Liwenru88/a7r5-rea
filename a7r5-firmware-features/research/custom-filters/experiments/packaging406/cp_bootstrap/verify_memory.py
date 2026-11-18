"""只读同源CPIO，在进程内生成/逆转CP候选；仅输出窄补丁计划和JSON回执。"""
from pathlib import Path
import argparse, hashlib, importlib.util, json
import memory_plan as P

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())

def verify(cp,output,build=None):
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT/'.local/fixed-custom-filters'):raise ValueError('只允许任务隔离输出')
    if output.exists() or output.is_symlink():raise ValueError('输出已存在')
    source_digest=hashlib.sha256(cp).hexdigest()
    plan=P.create_plan(cp,Path(build) if build is not None else HERE/'paired-v2')
    candidate=P.transform(cp,plan)
    assert P.transform(candidate,plan,True)==cp
    checks=['apply_reverse_byte_identity']
    for original,reverse,name in ((cp,False,'source_identity_reject'),(candidate,True,'candidate_identity_reject')):
        corrupt=bytearray(original);corrupt[512]^=1
        try:P.transform(corrupt,plan,reverse)
        except ValueError:checks.append(name)
        else:raise AssertionError('错误来源被接受')
    assert hashlib.sha256(cp).hexdigest()==source_digest
    assert candidate[0x11d3000-P.BASE:0x11d4900-P.BASE]==cp[0x11d3000-P.BASE:0x11d4900-P.BASE]
    assert candidate[0xbef700-P.BASE:0xbef9e8-P.BASE]==cp[0xbef700-P.BASE:0xbef9e8-P.BASE]
    result=dict(status='PASS_MEMORY_ONLY',checks=checks,source_unchanged=True,
                original_joint_source_and_code_prefix_unchanged=True,
                source_sha256=source_digest,candidate_sha256=plan['candidate_sha256'],
                patches=len(plan['patches']),CP_file_written=False,target_executed=False)
    output.mkdir(parents=True)
    (output/'memory-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-cpio',type=Path,default=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--build',type=Path,required=True)
    a=p.parse_args()
    check=P.load_module(ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406/check_placement.py','readonly_cp_source34')
    cp=check.read_cpio(a.source_cpio,{'cp/cpapp-b.bin'})['cp/cpapp-b.bin']
    verify(cp,a.output,a.build)

if __name__=='__main__':main()
