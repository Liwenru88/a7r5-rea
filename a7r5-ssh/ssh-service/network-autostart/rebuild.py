"""在临时目录重建并比对生产ELF，不执行它们，不访问相机。"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    source=json.loads((HERE/'verification/build.json').read_text())
    libc=HERE/'sdk/libc-2.25.so'
    if sha(libc)!='f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':raise ValueError('libc改变')
    results={}
    oldroot=Path(source['commands'][0][source['commands'][0].index('-I')+1]).parent
    with tempfile.TemporaryDirectory(prefix='a7r5-net-rebuild-') as temp:
        for original in source['commands']:
            name=Path(original[-1]).name;target=Path(temp)/name;command=[]
            for item in original:
                if item.startswith(str(oldroot)+'/'):item=str(HERE)+item[len(str(oldroot)):]
                if item.endswith('/lib/libc-2.25.so'):item=str(libc)
                command.append(item)
            command[-1]=str(target)
            subprocess.run(command,capture_output=True,check=True,timeout=60)
            if target.read_bytes()!=(HERE/'materials'/name).read_bytes():raise ValueError('重建字节不同：'+name)
            results[name]=dict(identical=True,bytes=target.stat().st_size,sha256=sha(target))
    receipt=dict(status='passed',camera_io=False,executed_artifacts=False,rebuilt=results)
    (HERE/'verification/rebuild.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
