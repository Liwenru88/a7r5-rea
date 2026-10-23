/* 固定初始化入口不能从拍摄、启动中、弹层或已确认状态打开。 */
#include <assert.h>
#include <stdio.h>
#include "a7r5-privacy-policy.h"
int main(void) {
    const unsigned int forbidden[]={0,0x315,0x355,0x1e3,0x2ed,0xffffffff};
    assert(a7r5_privacy_can_open(0x2d6,0,0));
    for(unsigned int i=0;i<sizeof forbidden/sizeof forbidden[0];++i)
        assert(!a7r5_privacy_can_open(forbidden[i],0,0));
    assert(!a7r5_privacy_can_open(0x2d6,0x472,0));
    assert(!a7r5_privacy_can_open(0x2d6,1,0));
    assert(!a7r5_privacy_can_open(0x2d6,0,1));
    assert(!a7r5_privacy_can_open(0x2d6,0,2));
    puts("privacy request policy: PASS");
    return 0;
}
