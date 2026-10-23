"""真实离线封包：不枚举设备，核对可用材料、脚本语法及私有权限。"""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import package
import tool


def test_real_offline_package_is_sealed_private_and_non_autostart(tmp_path):
    # 项目还存在同名旧package.py，先导入build不能改变本工具的模块选择。
    probe='import sys; sys.path.insert(0,'+repr(str(ROOT))+'); import build,package; from pathlib import Path; assert Path(package.__file__).parent==Path('+repr(str(ROOT))+')'
    subprocess.run([sys.executable,'-B','-c',probe],check=True,capture_output=True)
    password=tmp_path/'test-input';password.write_text('12345678\n');password.chmod(0o600)
    destination=tmp_path/'package'
    manifest=package.prepare(destination,password,qemu_only=True)
    assert tool.check(destination)==manifest
    assert manifest['ttl_seconds']==0 and manifest['autostart'] is False
    assert manifest['qemu_only'] is True and manifest['camera_execution_verified'] is False
    assert len(manifest['files'])>20
    assert (destination/'src/trigger.c').is_file() and (destination/'tests/test_contract.py').is_file()
    for path in destination.rglob('*'):
        assert path.stat().st_mode&0o077==0
    assert not (destination/'.state').exists()
    for path in destination.glob('*.command'):
        result=subprocess.run(['/bin/zsh','-n',str(path)],capture_output=True)
        assert result.returncode==0
