"""收集锁定依赖的版权说明，不下载或公开上传私钥。"""
from pathlib import Path
import json
import shutil
import tomllib
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'prepared/engine/notices';DEST.mkdir(exist_ok=True)
registry=next((Path.home()/'.cargo/registry/src').glob('index.crates.io-*'))
rows=[]
for package in tomllib.loads((ROOT/'src-tauri/Cargo.lock').read_text())['package']:
    if 'source' not in package:continue
    source=registry/(package['name']+'-'+package['version']);target=DEST/'rust'/source.name
    info=tomllib.loads((source/'Cargo.toml').read_text())['package']
    found=[]
    for path in source.iterdir():
        if path.is_file() and path.name.upper().startswith(('LICENSE','COPYING','NOTICE','AUTHORS','UNLICENSE')):
            target.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target/path.name);found.append(path.name)
    rows.append(dict(name=package['name'],version=package['version'],license=info.get('license'),repository=info.get('repository'),included=found))
(DEST/'rust-dependencies.json').write_text(json.dumps(rows,indent=2)+'\n')
for name,url in [('PMCA-LICENSE','https://raw.githubusercontent.com/ma1co/Sony-PMCA-RE/master/LICENSE.txt'),
                 ('PyUSB-LICENSE','https://raw.githubusercontent.com/pyusb/pyusb/master/LICENSE')]:
    with urllib.request.urlopen(url,timeout=30) as response:(DEST/name).write_bytes(response.read())
print('依赖版权说明已收集：'+str(len(rows))+'个锁定Rust依赖')
