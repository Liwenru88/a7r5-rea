"""串联现有严格门禁，生成隔离研究候选；不部署、不授予实机验收资格。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[4]
PACKAGE=ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406'


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-dat','source-workspace','software','cp-receipt','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--version',choices=('4.10','4.12'),default='4.10')
    args=parser.parse_args()
    out=args.output.resolve();assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    inputs={name:getattr(args,name.replace('-','_')).resolve() for name in ('source-dat','source-workspace','software','cp-receipt')}
    assert all(p.is_file() and not p.is_symlink() for n,p in inputs.items() if n!='source-workspace')
    assert inputs['source-workspace'].is_dir() and not inputs['source-workspace'].is_symlink()
    software=json.loads(inputs['software'].read_text());assert software['status']=='PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS'
    if software.get('ST_photo_chain_software_verified') is not True:
        raise ValueError('缺少ST导入、保存与双域组件连续软件验证；拒绝使用旧构建回执打包')
    out.mkdir();steps=[]
    env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'a7r5-desktop/prepared/engine/site')

    def run(label,script,*arguments,python=None):
        argv=[str(python or sys.executable),'-B',str(script),*map(str,arguments)]
        print('STAGE',label,flush=True);start=time.monotonic()
        runtime_env=env
        if python:
            # DAT工具已有独立密码库及完整安装元数据，不能被prepared/site覆盖。
            runtime_env=dict(os.environ);runtime_env.pop('PYTHONPATH',None)
        r=subprocess.run(argv,cwd=ROOT,env=runtime_env,capture_output=True,text=True)
        row=dict(stage=label,argv=argv,exit_code=r.returncode,seconds=time.monotonic()-start,stdout=r.stdout,stderr=r.stderr)
        steps.append(row);(out/'commands.json').write_text(json.dumps(steps,ensure_ascii=False,indent=2)+'\n')
        if r.returncode:raise RuntimeError(f'{label}失败，原始日志：{out/"commands.json"}')

    try:
        preflight=out/'preflight';loader=out/'loader';manifest=out/'staging.json';usr=out/'usr';update=out/('update'+args.version.replace('.',''))
        run('AP预检',PACKAGE/'build_and_audit.py','--ui',inputs['software'].parent/'dynamic/ap-ui.elf',
            '--ui-receipt',inputs['software'],'--recipe-bridge','--include-photo-markers','--output',preflight)
        run('产品启动库',PACKAGE/'loader/build_loader.py','--preflight',preflight/'verification.json',
            '--software',inputs['software'],'--output',loader)
        run('冻结清单',PACKAGE/'freeze_staging_manifest.py','--preflight',preflight/'verification.json',
            '--software',inputs['software'],'--loader',loader/'verification.json','--output',manifest)
        run('USR完整回读',PACKAGE/'stage_unsigned_usr.py','--manifest',manifest,'--manifest-sha256',digest(manifest),'--output',usr)
        run('DAT封装与独立回读',PACKAGE/'build_update.py','--source-dat',inputs['source-dat'],
            '--source-workspace',inputs['source-workspace'],'--usr-manifest',manifest,
            '--usr-receipt',usr/'verification.json','--cp-receipt',inputs['cp-receipt'],'--output',update,'--version',args.version,
            python=ROOT/'a7r5-dat-tool/.venv/bin/python')
        result=json.loads((update/'verification.json').read_text());completed=json.loads((update/'COMPLETED.json').read_text())
        assert result['status']==completed['status']=='RESEARCH_UPGRADE_PACKAGED_AND_INDEPENDENTLY_READ_BACK'
        dat=update/'BODYDATA.DAT';assert digest(dat)==result['sha256']==completed['sha256']
        report=dict(status='OFFLINE_RESEARCH_PACKAGE_READY_NOT_DEVICE_ACCEPTED',package=result,
            commands_sha256=digest(out/'commands.json'),source_sha256=digest(Path(__file__)),
            camera_io=False,CP_ISP_hardware_emulated=False,device_installation_approved=False)
        (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(status=report['status'],path=str(dat),sha256=result['sha256']),ensure_ascii=False),flush=True)
    except BaseException as error:
        (out/'FAILED.json').write_text(json.dumps(dict(error=str(error),completed_stages=[s['stage'] for s in steps if not s['exit_code']],camera_io=False),ensure_ascii=False,indent=2)+'\n')
        raise


if __name__=='__main__':main()
