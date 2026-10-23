"""终端身份缺失或非 root 时，不得被后续命令成功码掩盖。"""
import importlib.util
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import Mock,patch
LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
spec=importlib.util.spec_from_file_location('guest_shell',LAB/'tools/shell.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ShellIdentity(unittest.TestCase):
    def test_missing_or_nonroot_credentials_are_rejected(self):
        for data in (b'sh: id: not found\n',b'Uid:\t1000\t1000\t1000\t1000\nGid:\t1000\t1000\t1000\t1000\n'):
            with self.subTest(data=data),tempfile.TemporaryDirectory() as directory:
                out=Path(directory);console=out/'console.log';console.write_bytes(data)
                vm=Mock(out=out,console=console)
                vm.command.return_value=data
                vm.close.return_value={'method':'qmp-quit','exit_code':0}
                with patch.object(module,'NativeVM',return_value=vm),patch.object(sys,'argv',['shell.py','--command','true']),patch('builtins.print'):
                    with self.assertRaisesRegex(ValueError,'UID/GID'):module.main()
                vm.close.assert_called_once()
                self.assertEqual(vm.command.call_count,1)

if __name__=='__main__':unittest.main()
