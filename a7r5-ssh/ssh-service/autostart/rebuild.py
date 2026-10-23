"""在新的本机临时目录逐字节复现，不覆盖已封装载荷。"""
import contextlib,hashlib,io,json,shutil,tempfile
from pathlib import Path
import build
HERE=Path(__file__).resolve().parent

def main():
    original=build.HERE;result={}
    with tempfile.TemporaryDirectory(prefix='rebuild-',dir=HERE/'verification') as path:
        tmp=Path(path)
        for name in ('src','materials','source-snapshot'):shutil.copytree(HERE/name,tmp/name)
        shutil.copy2(HERE/'operation.json',tmp/'operation.json')
        try:
            build.HERE=tmp
            with contextlib.redirect_stdout(io.StringIO()):build.main()
        finally:build.HERE=original
        for name in ('boot.so','ssh-service.arm64','control.static'):
            raw=(tmp/'materials'/name).read_bytes()
            if raw!=(HERE/'materials'/name).read_bytes():raise ValueError('重建字节不符：'+name)
            result[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),identical=True)
    record=dict(status='passed',camera_io=False,executed_artifacts=False,rebuilt=result)
    (HERE/'verification/rebuild.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
