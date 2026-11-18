#!/usr/bin/env python3
"""电脑端CUBE有界整数拟合，输出现有AJR2/AFD1；仅运行宿主参考模型。"""
from __future__ import annotations

import argparse
import collections
import contextlib
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
if str(HERE) not in sys.path:sys.path.insert(0,str(HERE))
import recipe_file

HOME=HERE.parent
NATIVE=HOME/'native'
SOURCES=tuple(dict.fromkeys((*recipe_file._SOURCES,'af_joint_basis.c','af_reference_assets.c',
    'af_reference_samples.c','af_reference_domain.c','af_reference_joint.c','af_reference_grid.c',
    'af_edit_joint.c','af_color406.c','af_edit_cp_gamma.c','af_gamma406.c','af_edit_reference.c',
    'af_edit_chain.c','af_edit_gamma_table.c','af_edit_matrix_table.c','af_edit_context.c')))
VECTOR=c.c_int16*45
GRID=c.c_int8*1215
PROGRESS=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)
FitResult=collections.namedtuple('FitResult','asset document metadata report')


class FitError(ValueError):pass
class FitCancelled(FitError):pass
class _Budget(Exception):pass


def _sha(data):return hashlib.sha256(data).hexdigest()


def _check(status):
    if status:raise FitError(f'原生参考处理失败：{status}')


@contextlib.contextmanager
def native_solver(matrix_sectors=1):
    """独立编译本机C，不加载旧模拟器或目标ELF，不增加Python数值依赖。"""
    if type(matrix_sectors) is not int or matrix_sectors not in (1,16):raise FitError('矩阵区域须为1或16')
    compiler=shutil.which('clang')
    if not compiler:raise FitError('需要宿主clang')
    sources=[HERE/'desktop_fit_bridge.c',*[NATIVE/name for name in SOURCES]]
    pins=list(dict.fromkeys([*sources,*sorted(NATIVE.glob('*.h')),Path(__file__),HERE/'recipe_file.py',
                             HOME/'assets/reference-context4.bin',HOME/'assets/reference-context4.json']))
    inputs={str(p.relative_to(HOME)):_sha(p.read_bytes()) for p in pins}
    with tempfile.TemporaryDirectory(prefix='a7r5-desktop-fit-') as temporary:
        library=Path(temporary)/'fit.so'
        command=[compiler,'-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
            '-shared','-fPIC','-I'+str(NATIVE),*[str(p) for p in sources],'-lm','-o',str(library)]
        run=subprocess.run(command,capture_output=True,text=True)
        if run.returncode:raise FitError('宿主拟合桥编译失败：'+run.stderr)
        api=c.CDLL(str(library))
        api.desktop_open.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(c.c_int)];api.desktop_open.restype=c.c_void_p
        api.desktop_close.argtypes=[c.c_void_p];api.desktop_close.restype=None
        api.desktop_mode.argtypes=[c.c_void_p,c.c_uint]
        api.desktop_count.argtypes=[c.c_void_p,c.c_uint];api.desktop_count.restype=c.c_uint32
        api.desktop_cells.argtypes=[c.c_void_p,c.c_uint];api.desktop_cells.restype=c.c_uint64
        api.desktop_digest.argtypes=[c.c_void_p,c.c_uint,c.c_void_p]
        api.desktop_load_cube.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t]
        api.desktop_baseline.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,PROGRESS]
        api.desktop_grid_order.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
        api.desktop_asset.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.c_size_t]
        api.desktop_decode.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p]
        for name in ('desktop_loss','desktop_report'):
            getattr(api,name).argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_uint,c.c_void_p]
        for name in ('recipe_file_asset','recipe_file_document'):
            getattr(api,name).argtypes=[c.c_void_p,c.c_size_t]
        raw=recipe_file.read_regular(HOME/'assets/reference-context4.bin',377304)
        image=c.create_string_buffer(raw);status=c.c_int()
        state=api.desktop_open(image,len(raw),c.byref(status));_check(status.value)
        if not state:raise FitError('参考模型未初始化')
        try:
            _check(api.desktop_mode(state,int(matrix_sectors==16)))
            yield Solver(api,state,inputs,_sha(raw),matrix_sectors)
        finally:api.desktop_close(state)
        if inputs!={str(p.relative_to(HOME)):_sha(p.read_bytes()) for p in pins}:
            raise FitError('求解期间源码变化，不能交付当前结果')


class Solver:
    def __init__(self,api,state,sources,asset_sha,matrix_sectors=1):
        self.api,self.state,self.sources,self.asset_sha=api,state,dict(sources),asset_sha
        self.matrix_sectors=matrix_sectors;self.matrix_count=18 if matrix_sectors==1 else 288
        self.vector_count=3+self.matrix_count+24;self.vector=c.c_int16*self.vector_count
        self.asset_bytes=1943 if matrix_sectors==1 else 2483
        self.digests=[]
        for kind in range(3):
            raw=(c.c_uint8*32)();_check(api.desktop_digest(state,kind,raw));self.digests.append(bytes(raw).hex())
        self.splits={name:{'samples':api.desktop_count(state,n),
                          'cells':f'{api.desktop_cells(state,n):016x}'}
                     for n,name in enumerate(('training','selection','test'))}

    def inspect(self,raw):return recipe_file.inspect(raw,self.api)

    def fit(self,cube,name,*,budget=4096,starts=3,cancel=None,progress=None):
        if type(budget) is not int or not 300<=budget<=131072:raise FitError('候选预算须为300～131072')
        if type(starts) is not int or not 1<=starts<=12:raise FitError('起点须为1～12')
        if not isinstance(cube,bytes) or not 0<len(cube)<=4*1024*1024:raise FitError('CUBE须为4MiB内的字节')
        if not isinstance(name,str) or not 1<=len(name.encode('utf-8'))<=63 or any(ord(ch)<32 for ch in name):
            raise FitError('名称须为1～63个UTF-8字节且不含控制字符')
        began=time.monotonic();used=257;rejected=0;cancelled=False;callback_error=[];completed=0;history=[]

        def notify(stage):
            if cancel and cancel():raise FitCancelled('拟合已取消，未发布文件')
            if progress:progress(stage,used,budget)
        notify('参考基线')
        raw=c.create_string_buffer(cube);_check(self.api.desktop_load_cube(self.state,raw,len(cube)))
        baseline_v,baseline_g=self.vector(),GRID()
        def baseline_progress(_,done,total):
            nonlocal cancelled
            try:
                if cancel and cancel():cancelled=True;return 1
            except BaseException as error:callback_error.append(error);cancelled=True;return 1
            return 0
        callback=PROGRESS(baseline_progress)
        status=self.api.desktop_baseline(self.state,baseline_v,baseline_g,callback)
        if callback_error:raise FitCancelled('取消回调中断，未发布文件') from callback_error[0]
        if cancelled:raise FitCancelled('拟合已取消，未发布文件')
        _check(status)

        def loss(v,g,split):
            nonlocal used,rejected
            if used>=budget:raise _Budget()
            notify('整数候选');used+=1;out=(c.c_double*2)()
            status=self.api.desktop_loss(self.state,self.vector(*v),GRID(*g),split,out)
            if status==-21:rejected+=1;return (math.inf,math.inf)
            _check(status)
            if not all(math.isfinite(x) for x in out):raise FitError('模型返回非有限误差')
            # 整数RGB误差先选优；浮点误差及轻微L2仅在整数目标相同时决胜。
            penalty=1e-9*(sum((x/1024)**2 for x in v)+sum((x/64)**2 for x in g))
            return out[0],out[1]+penalty

        bv,bg=list(baseline_v),list(baseline_g)
        baseline_train=loss(bv,bg,0);baseline_selection=loss(bv,bg,1)
        selected=(baseline_selection,bv[:],bg[:],'native-257')
        starts_used=0
        for start in range(starts):
            if used>=budget-2 or baseline_train==(0.0,0.0):break
            starts_used+=1
            v,g=(bv[:],bg[:]) if start!=1 else ([0]*self.vector_count,[0]*1215)
            if start>=2:
                rng=random.Random(406+start)
                for _ in range(4):
                    index=rng.randrange(3,self.vector_count);v[index]=max(-1024,min(1024,v[index]+rng.choice((-4,4))))
            quota=(budget-used)//(starts-start);end=min(budget-1,used+max(quota,1))
            best=loss(v,g,0)
            native_end=used+max(1,(end-used)*2//5)
            try:
                # 三tone、18矩阵和24CC1均独立，不按端点共享控制量。
                # 固定context4的Q8权重[256,0,0,0]选择端点1；优先可辨识参数。
                indices=list(range(self.vector_count)) if self.matrix_sectors==1 else [
                    *range(3),*range(99,195),*range(299,307),*range(3,99),*range(195,299),*range(307,315)]
                for step in (16,8,4,2,1):
                    for index in indices:
                        for sign in (1,-1):
                            if used>=native_end:raise _Budget()
                            trial=v[:];trial[index]+=sign*step
                            if not -1024<=trial[index]<=1024:continue
                            score=loss(trial,g,0)
                            if score<best:best,v=score,trial
            except _Budget:pass
            # 先整体通道偏移，再依训练残差/节点覆盖顺序细化整数网格。
            order=(c.c_uint32*1215)()
            status=self.api.desktop_grid_order(self.state,self.vector(*v),order)
            if status==-21:order[:]=range(1215)
            else:_check(status)
            try:
                for step in (4,2,1):
                    for index in [*range(-3,0),*order]:
                        for sign in (1,-1):
                            if used>=end:raise _Budget()
                            trial=g[:]
                            indices=range((index+3)*405,(index+4)*405) if index<0 else (index,)
                            legal=True
                            for at in indices:
                                trial[at]+=sign*step
                                if not -64<=trial[at]<=63:legal=False;break
                            if not legal:continue
                            score=loss(v,trial,0)
                            if score<best:best,g=score,trial
            except _Budget:pass
            if used<budget:
                choice=loss(v,g,1)
                if choice<selected[0]:selected=(choice,v[:],g[:],f'desktop-start-{start}')
                history.append({'start':start,'training_mse':best[0] if math.isfinite(best[0]) else None,
                                'selection_mse':choice[0] if math.isfinite(choice[0]) else None})
            completed+=1
        notify('最终独立测试')
        # 至此选择已冻结；最终测试不用于起点、停止或候选取舍。
        _,v,g,selected_name=selected
        def report(vector,grid):
            out=(c.c_double*8)();_check(self.api.desktop_report(self.state,self.vector(*vector),GRID(*grid),2,out))
            return {'samples':int(out[0]),'clipped':int(out[1]),'delta_e76':list(out[2:7]),'rgb_rmse':out[7]}
        baseline_test=report(bv,bg);final_test=report(v,g)
        asset=c.create_string_buffer(self.asset_bytes)
        _check(self.api.desktop_asset(self.state,self.vector(*v),GRID(*g),asset,self.asset_bytes))
        asset=asset.raw
        initial=[0,0,0,0,0,0,3,0]
        metadata={'schema':recipe_file.METADATA_SCHEMA,'target_cp_sha256':self.digests[1],
            'base':0,'name':name,'lut_sha256':_sha(cube),'model_sha256':self.digests[0],
            'initial_params':initial,'saved_params':initial[:],
            'report':{'samples':final_test['samples'],'clipped':final_test['clipped'],
                      'delta_e76_milli':[int(x*1000+.5) for x in final_test['delta_e76']],'scope':1}}
        document=recipe_file.pack(asset,metadata,self.api)
        result={'schema':'a7r5-desktop-fit/1' if self.matrix_sectors==1 else 'a7r5-desktop-fit/2',
            'matrix_sectors':self.matrix_sectors,'research_only':True,'camera_apply_allowed':False,
            'scope':'ST/context4参考整数链与固定PT经验残差；不是机身色差',
            'parameters':{'tone':3,'matrix':self.matrix_count,'cc1':24,'grid':1215},'splits':{k:dict(v) for k,v in self.splits.items()},
            'evaluations':used,'budget':budget,'rejected_desktop':rejected,
            'baseline_budget':257,'starts_requested':starts,'starts_completed':max(1,completed),
            'optimizer':'有界整数坐标搜索/多起点/粗到细/训练残差网格排序，选优区域独立',
            'objective':'8bit RGB MSE优先；连续MSE及L2仅同整数误差时决胜',
            'selected':selected_name,'selected_selection_mse':selected[0][0],
            'baseline_selection_mse':baseline_selection[0],'baseline_test':baseline_test,'final_test':final_test,
            'baseline_controls':bv,'baseline_grid_hex':bytes(x&255 for x in bg).hex(),
            'history':history,'tone':v[:3],'matrix':v[3:3+self.matrix_count],'cc1':v[3+self.matrix_count:],
            'model_sha256':self.digests[0],'target_cp_sha256':self.digests[1],
            'reference_asset_sha256':self.asset_sha,'source_sha256':dict(self.sources),
            'lut_sha256':_sha(cube),'asset_sha256':_sha(asset),'document_sha256':_sha(document),
            'seconds':time.monotonic()-began,'test_used_for_selection':False,
            'limitations':['不输出任意Gamma；AJR2表达范围不变' if self.matrix_sectors==1 else
                           'AJR3为16色相区增量；固定权重下仅96项矩阵可辨识，非288项独立实拍标定',
                           '灰阶/暖色标签为代理，不能当实拍肤色',
                           '最终测试可能比基线退步，报告保留真实结果，不据测试重选']}
        return FitResult(asset,document,metadata,result)

    def verify(self,cube,document,report):
        """不重新拟合；以同源模型重新计算已选配方的最终留出误差。"""
        if (report.get('schema')!=('a7r5-desktop-fit/1' if self.matrix_sectors==1 else 'a7r5-desktop-fit/2')
                or report.get('matrix_sectors',1)!=self.matrix_sectors or report.get('camera_apply_allowed') is not False
                or report.get('test_used_for_selection') is not False or report.get('research_only') is not True):
            raise FitError('报告范围不匹配')
        if (report.get('document_sha256')!=_sha(document) or report.get('lut_sha256')!=_sha(cube)
                or report.get('model_sha256')!=self.digests[0] or report.get('target_cp_sha256')!=self.digests[1]
                or report.get('reference_asset_sha256')!=self.asset_sha or report.get('source_sha256')!=self.sources
                or report.get('splits')!=self.splits):raise FitError('报告、输入或求解来源不匹配')
        inspected=self.inspect(document)
        if not inspected['supported_for_sd_import'] or inspected['kind']!=1:raise FitError('不是当前完整配方')
        if (inspected['initial_params']!=[0,0,0,0,0,0,3,0]
                or inspected['lut_sha256']!=_sha(cube)
                or report.get('parameters')!={'tone':3,'matrix':self.matrix_count,'cc1':24,'grid':1215}):
            raise FitError('成品初始参数、源LUT或模型维度与参考报告不匹配')
        asset=document[-self.asset_bytes:]
        if report.get('asset_sha256')!=_sha(asset):raise FitError('载荷摘要不匹配')
        vector,grid=self.vector(),GRID();raw=c.create_string_buffer(asset)
        _check(self.api.desktop_decode(self.state,raw,len(asset),vector,grid))
        raw=c.create_string_buffer(cube);_check(self.api.desktop_load_cube(self.state,raw,len(cube)))
        if (list(vector[:3])!=report.get('tone') or list(vector[3:3+self.matrix_count])!=report.get('matrix')
                or list(vector[3+self.matrix_count:])!=report.get('cc1')):raise FitError('报告参数与成品不一致')
        baseline=report.get('baseline_controls')
        if (type(baseline) is not list or len(baseline)!=self.vector_count
                or any(type(x) is not int or not -1024<=x<=1024 for x in baseline)):
            raise FitError('基线参数无效')
        try:baseline_grid=bytes.fromhex(report['baseline_grid_hex'])
        except (ValueError,TypeError,KeyError) as error:raise FitError('基线网格无效') from error
        if len(baseline_grid)!=1215:raise FitError('基线网格长度无效')
        baseline_grid=GRID.from_buffer_copy(baseline_grid)
        outputs={}
        for key,cv,cg in (('final_test',vector,grid),('baseline_test',self.vector(*baseline),baseline_grid)):
            out=(c.c_double*8)();_check(self.api.desktop_report(self.state,cv,cg,2,out))
            expected=report.get(key,{})
            values=[expected.get('samples'),expected.get('clipped'),*expected.get('delta_e76',[]),expected.get('rgb_rmse')]
            if len(values)!=8 or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
                raise FitError('报告误差字段无效')
            if any(abs(a-b)>1e-6*max(1,abs(a),abs(b)) for a,b in zip(out,values)):
                raise FitError('导出整数配方的复算误差与报告不一致')
            loss=(c.c_double*2)();_check(self.api.desktop_loss(self.state,cv,cg,1,loss))
            field='selected_selection_mse' if key=='final_test' else 'baseline_selection_mse'
            value=report.get(field)
            if type(value) not in (int,float) or not math.isfinite(value) or abs(loss[0]-value)>1e-12:
                raise FitError('选优区域误差不一致')
            outputs[key]=out
        out=outputs['final_test']
        if (inspected['report']['samples']!=int(out[0]) or inspected['report']['clipped']!=int(out[1])
                or inspected['report']['delta_e76_milli']!=[int(v*1000+.5) for v in out[2:7]]):
            raise FitError('文件内误差摘要不一致')
        return {'verified':True,'samples':int(out[0]),'delta_e76':list(out[2:7]),
                'baseline_recomputed':True,'selection_recomputed':True,'camera_verified':False}


def publish(result,destination):
    """独占创建新交付目录；元数据先写，滤镜最后写，不覆盖既有内容。"""
    destination=Path(destination)
    files={'fit.ajr':result.asset,'metadata.json':(json.dumps(result.metadata,ensure_ascii=False,indent=2)+'\n').encode(),
           'fit-report.json':(json.dumps(result.report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode(),
           'filter.a7filter':result.document}
    if _sha(result.document)!=result.report['document_sha256'] or _sha(result.asset)!=result.report['asset_sha256']:
        raise FitError('交付对象已改变，不发布')
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name,data in files.items():
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    fd=os.open(destination,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    fit_parser=commands.add_parser('fit',help='CUBE拟合并导出现有格式')
    fit_parser.add_argument('cube',type=Path);fit_parser.add_argument('--name',required=True)
    fit_parser.add_argument('--output',type=Path,required=True,help='不存在的新交付目录')
    fit_parser.add_argument('--budget',type=int,default=4096);fit_parser.add_argument('--starts',type=int,default=3)
    fit_parser.add_argument('--matrix-sectors',type=int,choices=(1,16),default=1,
                            help='1保留AJR2；16导出显式新版AJR3，须配套新固件软件')
    verify_parser=commands.add_parser('verify',help='复算交付目录中的最终留出误差，不重新拟合')
    verify_parser.add_argument('cube',type=Path);verify_parser.add_argument('--bundle',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='verify':
            source=recipe_file.read_regular(args.cube,4*1024*1024)
            document=recipe_file.read_regular(args.bundle/'filter.a7filter',recipe_file.DOCUMENT_MAX)
            report=recipe_file.load_metadata(recipe_file.read_regular(args.bundle/'fit-report.json',65536))
            with native_solver(report.get('matrix_sectors',1)) as solver:result=solver.verify(source,document,report)
            print(json.dumps(result,ensure_ascii=False));return 0
        if args.output.exists():raise FitError('交付目录已存在，不覆盖')
        source=recipe_file.read_regular(args.cube,4*1024*1024)
        last=[0.0]
        def progress(stage,used,total):
            now=time.monotonic()
            if now-last[0]>2:print(f'{stage}：{used}/{total}',file=sys.stderr,flush=True);last[0]=now
        with native_solver(args.matrix_sectors) as solver:
            result=solver.fit(source,args.name,budget=args.budget,starts=args.starts,progress=progress)
        publish(result,args.output)
        print(json.dumps({'output':str(args.output/'filter.a7filter'),'report':str(args.output/'fit-report.json'),
                          'selection':result.report['selected'],'camera_verified':False},ensure_ascii=False))
        return 0
    except (FitError,recipe_file.RecipeFileError,OSError,UnicodeError,json.JSONDecodeError,KeyboardInterrupt) as error:
        print('电脑拟合未完成：'+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
