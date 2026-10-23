"""从固定官方发布源码构建USB库；只用于开发机，不枚举设备。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'prepared/dependencies';DEST.mkdir(parents=True,exist_ok=True)
URL='https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2'
EXPECTED='fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf'
archive=DEST/'libusb-1.0.30.tar.bz2'
if not archive.exists():
    with urllib.request.urlopen(URL,timeout=45) as stream:archive.write_bytes(stream.read())
if hashlib.sha256(archive.read_bytes()).hexdigest()!=EXPECTED:raise ValueError('官方源码摘要不符')
with tempfile.TemporaryDirectory(prefix='libusb-build-') as folder:
    with tarfile.open(archive) as stream:stream.extractall(folder,filter='data')
    source=Path(folder)/'libusb-1.0.30'
    env=dict(os.environ,MACOSX_DEPLOYMENT_TARGET='14.0',CC='/usr/bin/clang',CFLAGS='-O2 -mmacosx-version-min=14.0',LDFLAGS='-mmacosx-version-min=14.0')
    log=DEST/'libusb-build.log'
    with log.open('w') as out:
        subprocess.run(['./configure','--disable-static','--enable-shared','--disable-examples-build','--disable-tests-build'],cwd=source,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['/usr/bin/make','-j4'],cwd=source,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
    shutil.copyfile(source/'libusb/.libs/libusb-1.0.0.dylib',DEST/'libusb-1.0.dylib')
    shutil.copyfile(source/'COPYING',DEST/'libusb-COPYING')
(DEST/'libusb-build.json').write_text(json.dumps(dict(source_url=URL,source_sha256=EXPECTED,version='1.0.30',deployment_target='14.0',camera_IO=False),indent=2)+'\n')
print('USB库构建完成，最低系统目标14.0；未枚举设备')
