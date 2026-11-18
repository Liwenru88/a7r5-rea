"""LUT任务分批转换、取消与源快照；测试模型仅验证接线。"""
import ctypes as c
import pytest
from test_native_import import api, request, convert  # noqa: F401
from import_support import Candidate, ImportWork
from grid_support import Progress


def bind(api):
    api.af_import_state_bytes.restype=c.c_size_t
    api.af_import_start.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    api.af_import_step.argtypes=[c.c_void_p,c.c_uint32]
    return c.create_string_buffer(api.af_import_state_bytes())


def test_import_yields_before_publication_and_matches_complete_document(api):
    q=request(api);state=bind(api);storage=(c.c_float*24)();work=ImportWork()
    out=Candidate.from_buffer_copy(b'\xa5'*c.sizeof(Candidate));before=bytes(out);seen=[]
    progress=Progress(lambda _,done,total:seen.append((done,total))or 0)
    assert api.af_import_start(state,c.byref(q),storage,24,c.byref(work),c.byref(out),progress,None)==1
    assert bytes(out)==before
    for _ in range(100):
        status=api.af_import_step(state,3)
        if not status:break
        assert status==1 and bytes(out)==before
    else:pytest.fail('导入未在预算内结束')
    expected=convert(api,q)
    assert bytes(out)==bytes(expected)
    assert seen[-1]==(71,71)and all(a[0]<=b[0]for a,b in zip(seen,seen[1:]))
    assert api.af_import_step(state,3)==-5


@pytest.mark.parametrize('change',['cancel','source'])
def test_import_event_boundary_cancellation_or_source_change_does_not_publish(api,change):
    q=request(api);state=bind(api);storage=(c.c_float*24)();work=ImportWork();cancel=[False]
    out=Candidate.from_buffer_copy(b'\x5a'*c.sizeof(Candidate));before=bytes(out)
    progress=Progress(lambda _,done,total:int(cancel[0]))
    assert api.af_import_start(state,c.byref(q),storage,24,c.byref(work),c.byref(out),progress,None)==1
    assert api.af_import_start(state,c.byref(q),storage,24,c.byref(work),c.byref(out),progress,None)==-4
    assert api.af_import_step(state,2)==1
    if change=='cancel':cancel[0]=True
    else:q._source[0]=b'#'
    for _ in range(100):
        status=api.af_import_step(state,64)
        if status!=1:break
    assert status==(-20 if change=='cancel'else -5) and bytes(out)==before
