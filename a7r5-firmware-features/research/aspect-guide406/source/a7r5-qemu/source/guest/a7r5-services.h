/* A7R5 已观察到的虚拟参数协议；不代表物理 HDMI 输出。 */
struct a7r5_hdmi_state { unsigned int format, applied; };
int a7r5_hdmi_reply(struct a7r5_hdmi_state *, const unsigned char *, unsigned int, unsigned char *);
int a7r5_plane_reply(const unsigned char *, unsigned int, unsigned char *);
