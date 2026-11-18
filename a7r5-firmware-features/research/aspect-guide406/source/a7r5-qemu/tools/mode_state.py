"""从原厂拍摄信息页识别模式标志；只验证像素，不绘制替代画面。"""
import hashlib
import time

# 原帧见 runs/native-app-s8kvuv7x/research-{0003,0006,0009,0012,0015}-OBSERVE.bin。
# 左上模式标志固定区域，排除顶部无卡闪烁；未知布局不能据此识别模式。
MODE_ICONS = {
    'P':'86f27c75bb366957aa56fa6404bee918d2b76c7799e4420f2ccae3578f9479af',
    'S':'a69d7ef2c68cc9e9c3bc37c79202557af04f6274ff84361257337e2a89831ba1',
    'A':'b25c136d6825c7dfdc2b466ccbdad567942369d8c507b04a74e44c66452d26a5',
    'M':'24119d8acd264c228cd7cf9867932a3341c620d43417c70f97837317423f9362',
    'AUTO':'75361447248f0e71484082547bf5c85ca421d15fa1f68cc2d0a9d21fcedb43f5',
}


def shooting_signature(pixels):
    """排除无卡闪烁和 C4 提示框的 RGB/透明区域，其余稳定区域严格核对。"""
    if len(pixels)!=640*480*2:raise ValueError('拍摄页签名输入尺寸不符')
    digest=hashlib.sha256()
    for y in range(150,440):
        line=pixels[y*640*2:(y+1)*640*2]
        digest.update(line[:71*2]+line[569*2:] if 365<=y<419 else line)
    return digest.hexdigest()


def displayed_mode(pixels):
    if len(pixels)!=640*480*2:
        raise ValueError('模式识别输入尺寸不符')
    crop=b''.join(pixels[y*640*2:y*640*2+90*2] for y in range(80,135))
    digest=hashlib.sha256(crop).hexdigest()
    return next((mode for mode,value in MODE_ICONS.items() if value==digest),None)


def wait_mode_frame(capture, mode, after, timeout=8):
    """只采集新帧等待目标模式，不重发模式事件；超时不发布上一模式。"""
    if mode not in MODE_ICONS:raise ValueError('未知模式')
    deadline=time.monotonic()+timeout
    attempt=0
    while True:
        png,info=capture(attempt,after)
        if info.get('shooting_mode')==mode:return png,info,attempt
        if time.monotonic()>=deadline:raise TimeoutError('未取得目标模式 '+mode+' 的原厂画面')
        after=info['sequence'];attempt+=1
