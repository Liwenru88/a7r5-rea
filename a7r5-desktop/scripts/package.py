"""手工封装Tauri应用，保留内层代码签名和资源摘要。"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
DIST=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'dist'
APP=DIST/'A7R5 Studio.app'
if APP.exists():raise FileExistsError('交付包已存在；请保留验证记录后选择新的交付目录')
contents=APP/'Contents';mac=contents/'MacOS';resources=contents/'Resources'
mac.mkdir(parents=True);resources.mkdir()
shutil.copyfile(ROOT/'src-tauri/target/release/a7r5-desktop',mac/'a7r5-desktop');(mac/'a7r5-desktop').chmod(0o755)
shutil.copytree(ROOT/'prepared/engine',resources/'engine',symlinks=False)
iconset=ROOT/'prepared/app.iconset';iconset.mkdir(exist_ok=True)
for n in (16,32,128,256,512):
    for scale in (1,2):
        size=n*scale;target=iconset/(f'icon_{n}x{n}'+('@2x' if scale==2 else '')+'.png')
        subprocess.run(['/usr/bin/sips','-z',str(size),str(size),str(ROOT/'src-tauri/icons/icon.png'),'--out',str(target)],capture_output=True,check=True)
subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(resources/'AppIcon.icns')],check=True)
plist=dict(CFBundleName='A7R5 Studio',CFBundleDisplayName='A7R5 Studio',CFBundleIdentifier='local.a7r5.studio',
    CFBundleExecutable='a7r5-desktop',CFBundleIconFile='AppIcon',CFBundlePackageType='APPL',CFBundleShortVersionString='0.1.0',
    CFBundleVersion='1',LSMinimumSystemVersion='14.0',NSHighResolutionCapable=True,LSApplicationCategoryType='public.app-category.utilities',
    NSHumanReadableCopyright='本地研究测试版；包含研究签名身份，未经签名公证及实机验收。')
(contents/'Info.plist').write_bytes(plistlib.dumps(plist))
# 不使用deep重签内层，否则会改变已经嵌入主程序的资源摘要。
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(APP)],check=True,capture_output=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(APP)],check=True,capture_output=True)
subprocess.run([str(mac/'a7r5-desktop'),'--selfcheck'],check=True)
archive=DIST/'A7R5-Studio-0.1.0-mac-arm64-test.zip'
subprocess.run(['/usr/bin/ditto','-c','-k','--keepParent',str(APP),str(archive)],check=True)
report=dict(app=str(APP),archive=str(archive),archive_bytes=archive.stat().st_size,
    archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),app_file_bytes=sum(p.stat().st_size for p in APP.rglob('*') if p.is_file()),
    minimum_system='macOS 14.0',architecture='arm64',signature='ad-hoc',notarized=False,camera_IO=False)
(DIST/'package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
