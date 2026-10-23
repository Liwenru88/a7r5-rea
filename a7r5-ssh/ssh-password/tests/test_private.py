"""账户字节契约与构建拒绝测试；不连接相机或主机网络。"""
import base64
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build

HASH="$6$rounds=10000$"+"S"*16+"$"+"H"*86


class PrivateTests(unittest.TestCase):
    def test_c_account_copy_changes_only_root_hash_and_shell_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"test.c";binary=root/"test"
            source.write_text('#include <stdio.h>\n#include <string.h>\n#include "private_account.h"\nint main(int argc,char **argv){if(argc!=2)return 63;char original[8192],output[8192];int n=(int)fread(original,1,sizeof(original),stdin);int k=private_account(original,n,argv[1],output);if(k<0)return 64;return fwrite(output,1,(size_t)k,stdout)==(size_t)k?0:65;}\n')
            subprocess.run(["/usr/bin/clang","-O2","-Wall","-Wextra","-Werror","-I",str(build.ROOT),str(source),"-o",str(binary)],check=True,capture_output=True)
            original=b"nobody:*:65534:65534::/:/bin/false\nroot:*:0:0:root:/root:/bin/false\nsshd:*:77:77:sshd:/var/run/sshd:/bin/false\n"
            result=subprocess.run([str(binary),HASH],input=original,capture_output=True,check=True)
            expected=b"nobody:*:65534:65534::/:/bin/false\nroot:"+HASH.encode()+b":0:0:root:/root:/bin/sh\nsshd:*:77:77:sshd:/var/run/sshd:/bin/false\n"
            self.assertEqual(result.stdout,expected)
            for raw in (original[:-1],original+original,original.replace(b"root:*:0:0:root:/root:/bin/false\n",b""),original.replace(b"root:/root:/bin/false",b"root:/root:/bin/sh"),b"x"*8192,original.replace(b"root:*:0:0",b"root:*:1:0"),b"#"*8100+b"\n"+original):
                with self.subTest(length=len(raw)):
                    failed=subprocess.run([str(binary),HASH],input=raw,capture_output=True)
                    self.assertEqual(failed.returncode,64);self.assertEqual(failed.stdout,b"")

    def test_invalid_address_hash_or_lifetime_never_builds_or_creates_directory(self):
        cases=[("10.10.10.117",HASH,60),("8.8.8.8",HASH,60),("127.0.0.1",HASH,60),
               ("0.0.0.0\n",HASH,60),("0.0.0.0",HASH+" comment",60),
               ("0.0.0.0","$1$bad",60),("0.0.0.0",HASH,601)]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"candidate"
            with patch("subprocess.run",side_effect=AssertionError("拒绝前不能调用编译器")):
                for address,public,seconds in cases:
                    with self.subTest(address=address),self.assertRaises(ValueError):build.build(out,public,address,seconds)
                    self.assertFalse(out.exists())


if __name__=="__main__":unittest.main()
