"""逐字核验原编码资格函数的读取边界；只使用映射元数据，不执行目标。"""
from pathlib import Path
import ctypes as C
import subprocess
import sys

import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
SOURCE=Path(__file__).with_name('af_bootstrap406.c')


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    raw=SOURCE.read_text()
    body=raw[raw.index('static int protection('):raw.index('static int jump(')]
    source=r'''
#include "af_fsys406.h"
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
typedef struct {uintptr_t lo,hi;int flags;} Region;
static Region regions[10];static size_t region_count;
'''+body+r'''
int test_mapping(int index,int flags,int shorten,int special){
 static const uint32_t offsets[]={0x843bc,0x85688,0x9445c,0x945c4,
     0x946ec,0x94714,0x94750,0x94778,0xb9e68,0xd4418};
 uintptr_t base=0x50000000u;region_count=10;
 for(unsigned i=0;i<10;++i){
  size_t n=i<7?16:i<9?8:0x48;
  regions[i]=(Region){base+offsets[i],base+offsets[i]+n,i<8?5:i==8?1:3};
 }
 if(index>=0&&index<10){regions[index].flags=flags;if(shorten)regions[index].hi--;}
 if(special==1)base++;
 if(special==2)base=UINTPTR_MAX&~(uintptr_t)4095;
 if(special==3)base=0;
 return fsys_codec_mapping(base);
}
'''
    folder=tmp_path_factory.mktemp('fsys-codec-boundary')
    path=folder/'mapping.c';path.write_text(source);target=folder/'mapping.dylib'
    command=['clang','-dynamiclib' if sys.platform=='darwin' else '-shared','-fPIC','-std=c11',
             '-O1','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(path),'-o',str(target)]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    library=C.CDLL(str(target));library.test_mapping.argtypes=[C.c_int]*4
    return library


def test_only_all_required_read_windows_permit_policy(api):
    assert api.test_mapping(-1,0,0,0)==1
    for index in range(10):
        assert api.test_mapping(index,0,0,0)==0
        assert api.test_mapping(index,5 if index<8 else 1 if index==8 else 3,1,0)==0
    assert api.test_mapping(8,3,0,0)==1
    assert api.test_mapping(8,5,0,0)==0
    assert api.test_mapping(9,1,0,0)==0
    for special in (1,2,3):
        assert api.test_mapping(-1,0,0,special)==0
