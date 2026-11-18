/* HDMI audio format parameter, not a physical HDMI audio output engine. */
struct hdmi_format_state { unsigned int format, applied; };
int hdmi_format_reply(struct hdmi_format_state *, const unsigned char *, unsigned int, unsigned char *);
struct hdmi_photo_state { unsigned int premium, desired_preset6, applied; };
int hdmi_photo_reply(struct hdmi_photo_state *, const unsigned char *, unsigned int, unsigned char *);
struct display_info { unsigned short panel_width, panel_height, evf_width, evf_height; unsigned char panel_aspect, evf_aspect; };
int display_info_reply(const struct display_info *, const unsigned char *, unsigned int, unsigned char *);
int yuv_layout_reply(const unsigned char *, unsigned int, unsigned char *);
int plane_config_reply(const unsigned char *, unsigned int, unsigned char *);
int pin_disconnect_reply(const unsigned char *, unsigned int, unsigned char *);
int pin_hdmi_reply(const unsigned char *, unsigned int, unsigned char *);
int prop_161_reply(const unsigned char *, unsigned int, unsigned char *);
int prop_13d_reply(const unsigned char *, unsigned int, unsigned char *);
int prop_11a_reply(const unsigned char *, unsigned int, unsigned char *);
