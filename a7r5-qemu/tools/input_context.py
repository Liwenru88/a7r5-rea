"""仅用本次操作和真实帧推断输入上下文；打开日志不等于当前页面。"""
MENU_SCREENS=(0x2d5,0x2d6)


class InputContext:
    def __init__(self):
        self.context = 'unknown'
        self.guide_origin = None
        self.guide_origin_context = None
        self.closed_popup_screen = None
        self.privacy_accepted = False
        self.fn_origin = None
        self.fn_closed_popup_screen = None
        self.custom_origin = None
        self.custom_stable_origin = None
        self.custom_setting = None
        self.custom_screen = None
        self.last_stable_pixel = None

    def observe(self, key, pixel, screen, privacy=None, stable_pixel=None):
        # 只归一化界面状态判断；客体接收的仍是独立摇杆五向事件，不替换成导航键。
        if key.startswith('JOYSTICK_'):
            key='ENTER' if key=='JOYSTICK_CENTER' else key.removeprefix('JOYSTICK_')
        previous_stable=self.last_stable_pixel
        self.last_stable_pixel=stable_pixel
        if privacy is not None:
            self.privacy_accepted = privacy == 2
        if key == 'INITIAL_SETUP' and screen == 0x1e3:
            self.context = 'initial_setup'
            return self.context
        if self.context in ('initial_setup', 'setup_on_camera', 'setup_complete'):
            if key == 'MENU' and screen == 0x2d6:
                self.context = 'menu'
            elif screen == 0x355 and self.privacy_accepted:
                self.context = 'setup_complete'
            elif screen == 0x1e0:
                self.context = 'setup_on_camera'
            else:
                self.context = 'initial_setup'
            return self.context
        if self.privacy_accepted:
            if self.context=='shooting_ready' and key in ('C1','C2','C3'):
                self.custom_stable_origin=previous_stable
                if screen==0x34f:
                    self.context='custom_notice'
                elif (key,screen) in (('C3',0xd4),('C2',0xd4),('C1',0xd6)):
                    self.context='custom_setting';self.custom_setting=pixel;self.custom_screen=screen
                else:self.context='unknown'
                return self.context
            if self.context=='custom_notice':
                if key=='ENTER' and stable_pixel==self.custom_stable_origin and stable_pixel is not None:
                    self.context='shooting_ready'
                else:self.context='unknown'
                return self.context
            if self.context=='shooting_ready' and key=='C4':
                self.context='shooting_ready' if screen in (0,2) else 'unknown'
                return self.context
            if self.context=='custom_setting_notice':
                self.context='custom_setting' if key=='ENTER' and pixel==self.custom_setting else 'unknown'
                return self.context
            if self.context=='custom_setting':
                if key=='MENU' and screen==0:self.context='shooting_ready'
                elif key=='ENTER' and screen==0:self.context='shooting_ready'
                elif key=='ENTER' and screen==0x332:self.context='custom_setting_notice'
                elif key in ('UP','DOWN') and screen in (self.custom_screen,0x332):self.custom_setting=pixel
                else:self.context='unknown'
                return self.context
            if key=='FN' and self.context in ('shooting_ready','fn'):
                self.context='fn' if screen==0xc2 else 'shooting_ready' if screen==0 else 'unknown'
                if self.context=='fn':self.fn_origin=pixel
                return self.context
            if key=='PLAYBACK' and self.context in ('shooting_ready','playback_empty'):
                self.context='playback_empty' if screen==0x45f else 'shooting_ready' if screen==0 else 'unknown'
                return self.context
            if self.context=='fn_notice':
                self.context='fn' if key=='ENTER' and pixel==self.fn_origin else 'unknown'
                if self.context=='fn':self.fn_closed_popup_screen=screen
                return self.context
            if self.context=='fn' and key!='MENU':
                if key=='ENTER' and screen==0x34f and pixel!=self.fn_origin:
                    self.context='fn_notice'
                elif screen==0xc2 or pixel==self.fn_origin or screen==self.fn_closed_popup_screen:
                    self.fn_origin=pixel
                else:
                    self.context='fn_notice' if screen==0x34f else 'unknown'
                return self.context
            if key=='MENU' and screen==0xc2:
                self.context='fn';self.fn_origin=pixel
                return self.context
            if self.context=='shooting_ready' and key in ('UP','DISP'):
                self.context='shooting_ready' if screen in (0,2) else 'unknown'
                return self.context
        if self.context in ('menu','menu_page') and key.startswith(('REAR_DIAL_L_','REAR_DIAL_R_')):
            self.context='menu_page' if screen==0x2d6 else 'unknown'
            return self.context
        if self.context=='menu_page' and key.startswith(('FRONT_DIAL_','CONTROL_WHEEL_')):
            self.context='menu' if screen==0x2d6 else 'unknown'
            if self.context=='menu':self.guide_origin=pixel
            return self.context
        if key == 'C4':
            self.guide_origin_context = self.context
            self.context = 'guide' if self.context in ('menu', 'menu_option') and screen == 0x259 else 'unknown'
        elif self.context == 'guide':
            if key == 'ENTER' and pixel == self.guide_origin:
                self.context = self.guide_origin_context or 'menu'
                self.closed_popup_screen = screen
            else:
                self.context = 'unknown'
        elif self.context == 'menu_option' and key in ('ENTER', 'MENU'):
            self.context = 'menu_group' if screen==0x2d5 else 'menu' if screen is not None and screen in (0x2d6, 0x2ed, self.closed_popup_screen) else 'unknown'
        elif key in ('INITIAL', 'MENU'):
            self.context = 'menu_group' if screen==0x2d5 else 'menu' if screen == 0x2d6 else ('shooting_ready' if self.privacy_accepted else 'shooting') if screen in (0, 0x1e9) else 'unknown'
        elif self.context in ('menu', 'menu_option','menu_group','menu_page'):
            if screen == 0x2ed:
                self.context = 'menu_option'
            elif screen == 0x2d5:
                self.context = 'menu_group'
            elif screen == 0x2d6:
                self.context = 'menu'
            elif self.closed_popup_screen is None or screen != self.closed_popup_screen:
                self.context = 'unknown'
        if self.context in ('menu', 'menu_option'):
            self.guide_origin = pixel
        if self.context=='shooting_ready':
            self.custom_stable_origin=stable_pixel
        return self.context
