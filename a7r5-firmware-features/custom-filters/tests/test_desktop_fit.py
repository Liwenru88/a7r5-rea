"""电脑拟合使用实际参考C链与现有导入codec；不执行目标指令或设备操作。"""
import importlib.util
import copy
import hashlib
from pathlib import Path
import subprocess

import pytest
from test_prepared_recipe_import import driver

HOME=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def tool():
    spec=importlib.util.spec_from_file_location('desktop_fit_tool',HOME/'tools/fit_recipe.py')
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture(scope='module')
def solver(tool):
    with tool.native_solver() as value:
        yield value


def cube(warm=False):
    lines=['LUT_3D_SIZE 2']
    for b in range(2):
        for g in range(2):
            for r in range(2):
                lines.append(f'{r*.94 if warm else r} {g*.98 if warm else g} {b*.90 if warm else b}')
    return ('\n'.join(lines)+'\n').encode()


def test_identity_real_reference_fit_exports_existing_format(solver):
    result=solver.fit(cube(),'电脑中性',budget=300,starts=1)
    assert result.asset[:5]==b'AJR2\x02' and len(result.asset)==1943
    inspected=solver.inspect(result.document)
    assert inspected['supported_for_sd_import'] and not inspected['camera_verified']
    report=result.report
    assert report['research_only'] and not report['camera_apply_allowed']
    assert report['parameters']=={'tone':3,'matrix':18,'cc1':24,'grid':1215}
    assert report['final_test']['delta_e76'][0]==0
    masks=[int(report['splits'][name]['cells'],16) for name in ('training','selection','test')]
    assert all(masks) and all(not masks[i]&masks[j] for i in range(3) for j in range(i))


def test_nonidentity_fit_selection_and_determinism(solver):
    first=solver.fit(cube(True),'电脑暖调',budget=384,starts=2)
    second=solver.fit(cube(True),'电脑暖调',budget=384,starts=2)
    assert first.asset==second.asset and first.document==second.document
    report=first.report
    assert report['selected_selection_mse']<=report['baseline_selection_mse']
    assert report['evaluations']<=384 and report['starts_completed']>=1
    assert report['final_test']['samples']>0 and report['baseline_test']['samples']>0


def test_invalid_input_and_cancel_never_return_candidate(solver,tool):
    for data in (b'LUT_3D_SIZE 2\n0 0 0\n',cube().replace(b'1 1 1',b'nan 1 1')):
        with pytest.raises(tool.FitError):solver.fit(data,'坏输入',budget=300,starts=1)
    with pytest.raises(tool.FitCancelled):
        solver.fit(cube(True),'取消',budget=300,starts=1,cancel=lambda:True)


def test_result_bundle_exclusive_and_reverifiable(solver,tool,tmp_path):
    result=solver.fit(cube(),'导出',budget=300,starts=1)
    destination=tmp_path/'export'
    tool.publish(result,destination)
    assert (destination/'filter.a7filter').read_bytes()==result.document
    assert solver.inspect((destination/'filter.a7filter').read_bytes())['name']=='导出'
    assert solver.verify(cube(),result.document,result.report)['verified']
    bad=copy.deepcopy(result.report);bad['final_test']['delta_e76'][0]+=1
    with pytest.raises(tool.FitError):solver.verify(cube(),result.document,bad)
    bad=copy.deepcopy(result.report);bad['baseline_test']['delta_e76'][0]+=1
    with pytest.raises(tool.FitError):solver.verify(cube(),result.document,bad)
    # 合法重封装也不能把固定参考域的误差移到另一初始八值或另一源LUT。
    for field in ('initial','lut','samples','clipped'):
        metadata=copy.deepcopy(result.metadata)
        if field=='initial':metadata['initial_params'][0]=1
        elif field=='lut':metadata['lut_sha256']='ab'*32
        elif field=='samples':metadata['report']['samples']+=1
        else:metadata['report']['clipped']=1
        document=tool.recipe_file.pack(result.asset,metadata,solver.api)
        report=copy.deepcopy(result.report);report['document_sha256']=hashlib.sha256(document).hexdigest()
        with pytest.raises(tool.FitError):solver.verify(cube(),document,report)
    before={p.name:p.read_bytes() for p in destination.iterdir()}
    with pytest.raises(FileExistsError):tool.publish(result,destination)
    assert before=={p.name:p.read_bytes() for p in destination.iterdir()}


def test_fitted_file_enters_actual_service_and_survives_restore(solver,driver,tmp_path):
    result=solver.fit(cube(True),'暖色胶片',budget=384,starts=2)
    (tmp_path/'电脑配方.A7FILTER').write_bytes(result.document)
    run=subprocess.run([str(driver),str(tmp_path),'external','fd'],capture_output=True,text=True)
    assert run.returncode==0,run.stderr


def test_sector_fitter_explicit_format_replay_and_actual_service(tool,driver,tmp_path):
    with tool.native_solver(16) as sector:
        result=sector.fit(cube(True),'暖色胶片',budget=384,starts=2)
        assert result.asset[:5]==b'AJR3\x03' and len(result.asset)==2483
        assert result.report['parameters']['matrix']==288
        assert result.report['matrix_sectors']==16
        assert sector.verify(cube(True),result.document,result.report)['verified']
        inspected=sector.inspect(result.document)
        assert inspected['supported_for_sd_import'] and not inspected['camera_verified']
        identity=sector.fit(cube(),'零增量',budget=300,starts=1)
        assert identity.report['final_test']['delta_e76'][0]==0
    with tool.native_solver() as legacy:
        with pytest.raises(tool.FitError):legacy.verify(cube(True),result.document,result.report)
    (tmp_path/'电脑配方.A7FILTER').write_bytes(result.document)
    run=subprocess.run([str(driver),str(tmp_path),'external','fd'],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
