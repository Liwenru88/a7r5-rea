#include "a7r5-services.h"
int a7r5_plane_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw+0x3522f10..0x3523194：584 字节、18 个 32 字节平面；响应 12 字节，状态在 +8。 */
    static const unsigned char expected[8] = {0x0d,0x20,0x47,1,0x48,2,1,0x80};
    if (!request || !reply || size != 584) return -1024;
    for (unsigned int i=0; i<8; ++i) if (request[i] != expected[i]) return -1024;
    for (unsigned int i=0; i<18; ++i) {
        const unsigned char *p = request+8+i*32;
        if (p[2] || p[4] || p[5] || p[6] || p[7] ||
            p[8]!=0x80 || p[9]!=2 || p[10]!=0xe0 || p[11]!=1 || p[21] || p[24] ||
            p[28] || p[29] || p[30] || p[31]) return -1024;
    }
    static const unsigned char header[12] = {0x0d,0x20,0x47,0x11,12,0,1,0x80};
    for (unsigned int i=0; i<12; ++i) reply[i]=header[i];
    return 0;
}
int a7r5_hdmi_reply(struct a7r5_hdmi_state *state, const unsigned char *request,
                    unsigned int size, unsigned char *reply) {
    /* AppFw+0x3524cac 构造 10 字节请求，+0x3524d2c 读取响应+8 的状态。 */
    static const unsigned char expected[8] = {0x0d, 0x20, 0x2d, 3, 10, 0, 1, 0x80};
    if (!state || !request || !reply || size != 10) return -1024;
    for (unsigned int i = 0; i < 8; ++i) if (request[i] != expected[i]) return -1024;
    if (request[8] > 1 || request[9]) return -1024;
    static const unsigned char header[12] = {0x0d, 0x20, 0x2d, 0x13, 12, 0, 1, 0x80, 0, 0, 0, 0};
    for (unsigned int i = 0; i < 12; ++i) reply[i] = header[i];
    state->format = request[8];
    ++state->applied;
    return 0;
}
#ifdef A7R5_SERVICES_SELFTEST
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    struct a7r5_hdmi_state state = {0};
    unsigned char request[10] = {0x0d, 0x20, 0x2d, 3, 10, 0, 1, 0x80, 1, 0};
    unsigned char reply[12];
    assert(a7r5_hdmi_reply(&state, request, 10, reply) == 0);
    assert(state.format == 1 && state.applied == 1 && reply[2] == 0x2d && reply[3] == 0x13);
    for (unsigned int i = 8; i < 12; ++i) assert(reply[i] == 0);
    unsigned char before[12]; memcpy(before, reply, sizeof reply);
    for (unsigned int i = 0; i < 10; ++i) {
        unsigned char bad[10]; memcpy(bad, request, 10); bad[i] = 0xff;
        assert(a7r5_hdmi_reply(&state, bad, 10, reply) == -1024);
        assert(state.applied == 1 && !memcmp(before, reply, sizeof reply));
    }
    assert(a7r5_hdmi_reply(&state, request, 9, reply) == -1024);
    assert(a7r5_hdmi_reply(&state, request, 11, reply) == -1024);
    puts("A7R5_HDMI_032D_SELFTEST_PASS");
    unsigned char planes[584] = {0x0d,0x20,0x47,1,0x48,2,1,0x80};
    for (unsigned int i=0; i<18; ++i) {
        unsigned char *p=planes+8+i*32; p[8]=0x80; p[9]=2; p[10]=0xe0; p[11]=1;
    }
    assert(!a7r5_plane_reply(planes,584,reply) && reply[2]==0x47 && reply[3]==0x11);
    memcpy(before,reply,12);
    assert(a7r5_plane_reply(planes,583,reply)==-1024);
    planes[8+17*32+10]=0;
    assert(a7r5_plane_reply(planes,584,reply)==-1024 && !memcmp(before,reply,12));
    puts("A7R5_PLANE_584_SELFTEST_PASS");
    return 0;
}
#endif
