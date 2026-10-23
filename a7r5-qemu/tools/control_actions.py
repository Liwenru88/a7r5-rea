"""正式控制的固定动作；界面和工作进程共用，不接收原始键码。"""
TAPS = ('UP','DOWN','LEFT','RIGHT','ENTER','MENU','C4','FN','DISP','PLAYBACK','C1','C2','C3')
DIALS = ('FRONT_DIAL','REAR_DIAL_L','REAR_DIAL_R','CONTROL_WHEEL')
MODES = ('AUTO','P','A','S','M')
PAD_DIRECTIONS = ('UP','DOWN','LEFT','RIGHT','CENTER')
ACTION_SPECS = {key:(key,'tap',None) for key in TAPS}
ACTION_SPECS.update({control+'_'+suffix:(control,'rotate',value)
                     for control in DIALS for suffix,value in (('LEFT',-1),('RIGHT',1))})
ACTION_SPECS.update({'MODE_'+mode:('MODE_DIAL','select',mode) for mode in MODES})
ACTION_SPECS.update({'JOYSTICK_'+direction:('JOYSTICK','pad',direction) for direction in PAD_DIRECTIONS})


def request_for_action(action):
    if not isinstance(action,str) or action not in ACTION_SPECS:
        raise ValueError('未知固定动作')
    control,event,value = ACTION_SPECS[action]
    return dict(action='input',control=control,event=event,value=value)


def action_for_request(request):
    control,event,value = request['control'],request['event'],request['value']
    if event=='tap' and value is None and control in TAPS:
        return control
    if event=='rotate' and control in DIALS and type(value) is int and value in (-1,1):
        return control+('_LEFT' if value==-1 else '_RIGHT')
    if event=='select' and control=='MODE_DIAL' and isinstance(value,str) and value in MODES:
        return 'MODE_'+value
    if event=='pad' and control=='JOYSTICK' and isinstance(value,str) and value in PAD_DIRECTIONS:
        return 'JOYSTICK_'+value
    raise ValueError('仅允许固定点按或一次正反向步进')
