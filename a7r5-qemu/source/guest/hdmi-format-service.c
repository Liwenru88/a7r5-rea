/* CP packet 0x032f -> command 0xc7 -> legacy 0x0304 -> stored format word. */
#include "hdmi-format-service.h"
static unsigned int halfword(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8; }
int hdmi_format_reply(struct hdmi_format_state *state, const unsigned char *request,
                      unsigned int size, unsigned char *reply) {
    if (!state || !request || !reply || size < 10 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x32f || halfword(request + 4) != 10 ||
        halfword(request + 6) != 0x8001 || request[8] > 1 || request[9]) return -1024;
    state->format = request[8]; /* 0=LPCM; 1=LPCM/AC3, CP debug command documentation */
    ++state->applied;
    /* CP file+0xbe6a2 tags the legacy result with audio domain 0x580000. */
    const unsigned char header[8] = {0x0d, 0x20, 0x2f, 0x13, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = i < 8 ? header[i] : 0;
    reply[10] = 0x58;
    return 0;
}
int hdmi_photo_reply(struct hdmi_photo_state *state, const unsigned char *request,
                    unsigned int size, unsigned char *reply) {
    if (!state || !request || !reply || size < 12 || halfword(request) != 0x2500 ||
        halfword(request + 2) != 0x102 || halfword(request + 4) != 12 ||
        halfword(request + 6) != 1 || request[8] > 1 || request[9] || request[10] || request[11]) return -1024;
    /* CP file+0x623c70 stores premium; +0x623c80 selects desired-output preset 6. */
    state->premium = request[8];
    state->desired_preset6 = request[8];
    ++state->applied;
    const unsigned char header[8] = {0, 0x25, 2, 0x81, 12, 0, 1, 0};
    for (int i = 0; i < 12; ++i) reply[i] = i < 8 ? header[i] : 0;
    return 0;
}
int display_info_reply(const struct display_info *display, const unsigned char *request,
                       unsigned int size, unsigned char *reply) {
    if (!display || !request || !reply || size < 8 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x16a || halfword(request + 4) != 8 || halfword(request + 6) != 0x8001 ||
        !display->panel_width || !display->panel_height || !display->evf_width || !display->evf_height ||
        display->panel_aspect > 3 || display->evf_aspect > 3) return -1024;
    /* CP +0xc1478 preserves the old +8..+17 payload in the 18-byte new completion. */
    const unsigned char header[8] = {0x0d, 0x20, 0x6a, 0x11, 18, 0, 1, 0x80};
    for (int i = 0; i < 8; ++i) reply[i] = header[i];
    const unsigned short dimensions[4] = {display->panel_width, display->panel_height, display->evf_width, display->evf_height};
    for (int i = 0; i < 4; ++i) { reply[8 + 2*i] = dimensions[i]; reply[9 + 2*i] = dimensions[i] >> 8; }
    reply[16] = display->panel_aspect; reply[17] = display->evf_aspect;
    return 0;
}
int yuv_layout_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34f1638..0x34f1708 builds the observed 40-byte 0x14c request.
       CP 0x594964 returns 12-byte 0x114c; AppFw 0x34e34e4 accepts status 0. */
    if (!request || !reply || size < 40 || halfword(request) != 0x200d || halfword(request + 2) != 0x14c ||
        halfword(request + 4) != 40 || halfword(request + 6) != 0x8001) return -1024;
    if (request[8] > 7 || request[9] > 1 || request[10] != 1 || request[11] ||
        halfword(request + 12) || halfword(request + 14) ||
        halfword(request + 16) < 64 || halfword(request + 16) > 8192 ||
        halfword(request + 18) < 64 || halfword(request + 18) > 8192 || request[32] != 3) return -1024;
    /* the requested layout size follows whatever geometry we reported, so only sanity-check it
       (it used to be pinned to the old 640x480 placeholder) */
    const unsigned char header[12] = {0x0d, 0x20, 0x4c, 0x11, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
int plane_config_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34e90e8..0x34e9388 builds the observed 680-byte 0x147 plane table
       (memset 680, header at +0, 640x480 plane constants, per-output 44-byte records).
       CP 0x69c712 builds the 12-byte 0x1147 completion {0x200d,0x1147,12,0x8001,status@+8};
       AppFw 0x34e936c maps reply+8 through 0x34e349c (0 or 0x580000 -> success).
       Only this single observed request shape is accepted; the body is AppFw model state. */
    if (!request || !reply || size < 680 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x147 || halfword(request + 4) != 680 ||
        halfword(request + 6) != 0x8001) return -1024;
    const unsigned char header[12] = {0x0d, 0x20, 0x47, 0x11, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
int pin_disconnect_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34ef858..0x34ef918 builds the observed 12-byte MSGID_PIN_DISCONNECT
       (code 0x101, frame 0, flags 1, byte8 mode) to 0x909c015b and expects the
       16-byte MSGID_PIN_DISCONNECT_COMP (code 0x8101): status u32 at +8 must be 0
       (else error 147 via 0x34e4734) and reply byte +12 must echo request byte +8
       (0x34ef8f8 cmp). CP builder at 0x725f5a: {u16 0, u16 0x8101, u16 16, u16 1,
       u32 status@+8, echo byte@+12 from request, rest zero}; CP name table
       0x45d1b8/0x45d1d0 -> "MSGID_PIN_DISCONNECT"/_COMP. */
    if (!request || !reply || size < 12 || halfword(request) != 0 ||
        halfword(request + 2) != 0x101 || halfword(request + 4) != 12 ||
        halfword(request + 6) != 1 || request[8] > 1 || request[9] || request[10] || request[11]) return -1024;
    for (int i = 0; i < 16; ++i) reply[i] = 0;
    reply[2] = 0x01; reply[3] = 0x81;
    reply[4] = 16; reply[6] = 1;
    reply[12] = request[8];
    return 0;
}
int pin_hdmi_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34ec830..0x34ec8ec builds the observed 12-byte {0x2500,0x109,12,flags=1,
       mode@+8} request to 0x909a015a and prefills the reply {0x2500,0x8109,12,1,
       sentinel 0xEFFFFFFF@+8}; only status@+8 is consulted (mapper 0x34e4438).
       CP builds {0x2500,0x8109,12,...} completions at four independent sites
       (0x72ccbc, 0x72f150, 0x72fdf6, 0x731086) with status 0 on success.
       PinHandler strings (cpapp-b file+0x1298a0..0x1299c4) name this channel family
       MSGID_PIN_* "for HDMI AUDIO"/"for HDMI VIDEO". */
    if (!request || !reply || size < 12 || halfword(request) != 0x2500 ||
        halfword(request + 2) != 0x109 || halfword(request + 4) != 12 ||
        halfword(request + 6) != 1 || request[8] > 1 || request[9] || request[10] || request[11]) return -1024;
    const unsigned char header[12] = {0x00, 0x25, 0x09, 0x81, 12, 0, 1, 0};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
int prop_161_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34e9cd0..0x34e9d68 builds the observed 10-byte {0x200d,0x161,10,0x8001,
       byte8 = 0..4 from input jump table} request; 12-byte reply, status@+8 mapped by
       0x34e349c (0 or 0x580000 -> success). CP completion thunk at 0x69cafe (0x200d/0x1161/
       12/0x8001 builder, same table as the 0x1147/0x114c thunks). */
    if (!request || !reply || size < 10 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x161 || halfword(request + 4) != 10 ||
        halfword(request + 6) != 0x8001 || request[8] > 4 || request[9]) return -1024;
    const unsigned char header[12] = {0x0d, 0x20, 0x61, 0x11, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
int prop_13d_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34e89b8..0x34e8a2c builds the observed 10-byte {0x200d,0x13d,10,0x8001,
       byte8=[input+4], byte9 = 0/1/2 from input} request; 12-byte reply, status@+8
       mapped by 0x34e349c. CP completion thunk builds {0x200d,0x113d,12,0x8001}
       (movw 0x113d at VA 0x69c81c, sizes/flags at 0x69c820..0x69c836). */
    if (!request || !reply || size < 10 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x13d || halfword(request + 4) != 10 ||
        halfword(request + 6) != 0x8001 || request[9] > 2) return -1024;
    const unsigned char header[12] = {0x0d, 0x20, 0x3d, 0x11, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
int prop_11a_reply(const unsigned char *request, unsigned int size, unsigned char *reply) {
    /* AppFw 0x34e850c..0x34e864c (and sibling 0x34e8708) builds the observed 14-byte
       {0x200d,0x11a,14,0x8001} request; body bytes come from caller mode tables
       (values 1/2/4/6/8 at +12), so only the header is validated. 12-byte reply,
       status@+8 mapped by 0x34e349c. CP completion builder at 0x1c72b8
       ({0x200d,0x111a,12,0x8001} with status word, next to send helper 0x1c78e0). */
    if (!request || !reply || size < 14 || halfword(request) != 0x200d ||
        halfword(request + 2) != 0x11a || halfword(request + 4) != 14 ||
        halfword(request + 6) != 0x8001) return -1024;
    const unsigned char header[12] = {0x0d, 0x20, 0x1a, 0x11, 12, 0, 1, 0x80};
    for (int i = 0; i < 12; ++i) reply[i] = header[i];
    return 0;
}
#ifdef PROP_11A_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[14] = {0x0d, 0x20, 0x1a, 1, 14, 0, 1, 0x80, 1, 14, 0, 14, 2, 0}, reply[12];
    assert(!prop_11a_reply(request, 14, reply));
    assert(halfword(reply) == 0x200d && halfword(reply + 2) == 0x111a && halfword(reply + 4) == 12);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
    assert(prop_11a_reply(request, 13, reply) == -1024);
    request[2] = 0x19;
    assert(prop_11a_reply(request, 14, reply) == -1024);
    puts("PROP_11A_SELFTEST_PASS");
}
#endif
#ifdef PROP_13D_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[10] = {0x0d, 0x20, 0x3d, 1, 10, 0, 1, 0x80, 0, 1}, reply[12];
    assert(!prop_13d_reply(request, 10, reply));
    assert(halfword(reply) == 0x200d && halfword(reply + 2) == 0x113d && halfword(reply + 4) == 12);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
    request[9] = 3;
    assert(prop_13d_reply(request, 10, reply) == -1024);
    request[9] = 1; request[2] = 0x3c;
    assert(prop_13d_reply(request, 10, reply) == -1024);
    puts("PROP_13D_SELFTEST_PASS");
}
#endif
#ifdef PROP_161_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[10] = {0x0d, 0x20, 0x61, 1, 10, 0, 1, 0x80, 2, 0}, reply[12];
    assert(!prop_161_reply(request, 10, reply));
    assert(halfword(reply) == 0x200d && halfword(reply + 2) == 0x1161 && halfword(reply + 4) == 12);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
    request[8] = 5;
    assert(prop_161_reply(request, 10, reply) == -1024);
    request[8] = 2; request[2] = 0x60;
    assert(prop_161_reply(request, 10, reply) == -1024);
    puts("PROP_161_SELFTEST_PASS");
}
#endif
#ifdef PIN_HDMI_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[12] = {0, 0x25, 9, 1, 12, 0, 1, 0, 1, 0, 0, 0}, reply[12];
    assert(!pin_hdmi_reply(request, 12, reply));
    assert(halfword(reply) == 0x2500 && halfword(reply + 2) == 0x8109 && halfword(reply + 4) == 12 && halfword(reply + 6) == 1);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
    request[8] = 2;
    assert(pin_hdmi_reply(request, 12, reply) == -1024);
    request[8] = 1; request[2] = 0x08;
    assert(pin_hdmi_reply(request, 12, reply) == -1024);
    puts("PIN_HDMI_SELFTEST_PASS");
}
#endif
#ifdef PIN_DISCONNECT_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[12] = {0, 0, 1, 1, 12, 0, 1, 0, 1, 0, 0, 0}, reply[16];
    assert(!pin_disconnect_reply(request, 12, reply));
    assert(halfword(reply) == 0 && halfword(reply + 2) == 0x8101 && halfword(reply + 4) == 16 && halfword(reply + 6) == 1);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11] && reply[12] == 1);
    request[8] = 0;
    assert(!pin_disconnect_reply(request, 12, reply) && reply[12] == 0);
    request[8] = 2;
    assert(pin_disconnect_reply(request, 12, reply) == -1024);
    request[8] = 1; request[6] = 0x81;
    assert(pin_disconnect_reply(request, 12, reply) == -1024);
    puts("PIN_DISCONNECT_SELFTEST_PASS");
}
#endif
#ifdef PLANE_CONFIG_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    unsigned char request[680] = {0x0d, 0x20, 0x47, 1, 0xa8, 2, 1, 0x80}, reply[12];
    assert(!plane_config_reply(request, 680, reply));
    assert(halfword(reply) == 0x200d && halfword(reply + 2) == 0x1147 && halfword(reply + 4) == 12);
    assert(!reply[8] && !reply[9] && !reply[10] && !reply[11]);
    assert(plane_config_reply(request, 679, reply) == -1024);
    request[2] = 0x46;
    assert(plane_config_reply(request, 680, reply) == -1024);
    puts("PLANE_CONFIG_SELFTEST_PASS");
}
#endif
#ifdef HDMI_FORMAT_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    struct hdmi_format_state state = {1, 0};
    unsigned char request[10] = {0x0d, 0x20, 0x2f, 3, 10, 0, 1, 0x80, 0, 0};
    unsigned char reply[12];
    assert(hdmi_format_reply(&state, request, 10, reply) == 0 && state.format == 0 && state.applied == 1);
    assert(halfword(reply) == 0x200d && halfword(reply + 2) == 0x132f && halfword(reply + 4) == 12);
    assert(reply[8] == 0 && reply[9] == 0 && reply[10] == 0x58 && reply[11] == 0);
    request[8] = 1;
    assert(hdmi_format_reply(&state, request, 10, reply) == 0 && state.format == 1 && state.applied == 2);
    request[8] = 2;
    assert(hdmi_format_reply(&state, request, 10, reply) == -1024 && state.format == 1 && state.applied == 2);
    request[8] = 0; request[2] = 0x30;
    assert(hdmi_format_reply(&state, request, 10, reply) == -1024);
    request[2] = 0x2f;
    assert(hdmi_format_reply(&state, request, 9, reply) == -1024);
    puts("HDMI_FORMAT_SELFTEST_PASS");
}
#endif
#ifdef DISPLAY_INFO_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    const struct display_info display = {640,480,640,480,1,1};
    unsigned char request[8] = {0x0d,0x20,0x6a,1,8,0,1,0x80}, reply[18];
    assert(!display_info_reply(&display, request, 8, reply));
    assert(halfword(reply+2) == 0x116a && halfword(reply+4) == 18);
    assert(halfword(reply+8) == 640 && halfword(reply+10) == 480 && reply[16] == 1);
    assert(display_info_reply(&display, request, 7, reply) == -1024);
    request[2] = 0x69;
    assert(display_info_reply(&display, request, 8, reply) == -1024);
    puts("DISPLAY_INFO_SELFTEST_PASS");
}
#endif
#ifdef HDMI_PHOTO_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    struct hdmi_photo_state state = {0};
    unsigned char request[12] = {0, 0x25, 2, 1, 12, 0, 1, 0, 1}, reply[12];
    assert(hdmi_photo_reply(&state, request, 12, reply) == 0);
    assert(state.premium == 1 && state.desired_preset6 == 1 && state.applied == 1);
    assert(halfword(reply) == 0x2500 && halfword(reply + 2) == 0x8102 && reply[8] == 0);
    request[8] = 0;
    assert(hdmi_photo_reply(&state, request, 12, reply) == 0 && !state.premium && !state.desired_preset6);
    request[8] = 2;
    assert(hdmi_photo_reply(&state, request, 12, reply) == -1024 && state.applied == 2);
    request[8] = 1;
    assert(hdmi_photo_reply(&state, request, 11, reply) == -1024 && state.applied == 2);
    puts("HDMI_PHOTO_SELFTEST_PASS");
}
#endif
