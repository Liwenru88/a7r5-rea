"""原CP八项系数的参考像素模型；格式有本机证据，像素公式参考桌面Sony引擎研究。

依据：https://github.com/Jannchie/llr/blob/main/sony_repro/PIPELINE.md §7.1/7.2。
独立实现相对ST的符号耦合；并未在A7R5硬件像素上验证，不引入外部拟合染色资产。
"""
import math


def validate(p):
    if len(p)!=8 or any(not math.isfinite(v) for v in p):raise ValueError('CC1 需要八个有限参数')


def forward(u,v,p):
    """CP顺序与RAW顺序不同；将本机实际应用的八项送入参考耦合。"""
    validate(p)
    u2=u+p[3 if v>=0 else 1]/1024*v
    v2=v+p[0 if u>=0 else 2]/1024*u
    return (p[4 if u2>=0 else 6]/512*u2,
            p[7 if v2>=0 else 5]/512*v2)


def inverse(cr,cb,p):
    validate(p)
    g1=p[4 if cr>=0 else 6]/512;g2=p[7 if cb>=0 else 5]/512
    if g1<=0 or g2<=0:raise ValueError('ST 色度增益不可逆')
    u2=cr/g1;v2=cb/g2
    for up in (True,False):
        for vp in (True,False):
            a=p[3 if vp else 1]/1024;b=p[0 if up else 2]/1024;det=1-a*b
            if abs(det)<1e-9:continue
            u=(u2-a*v2)/det;v=(v2-b*u2)/det
            if (u>=-1e-12 if up else u<=1e-12) and (v>=-1e-12 if vp else v<=1e-12):return u,v
    raise ValueError('ST 符号分支没有一致逆解，拒绝猜测颜色')


def relative(rgb,base,target):
    validate(base);validate(target)
    if base==target:return rgb
    r,g,b=rgb;y=.299*r+.587*g+.114*b
    # JPG已经经过ST的色度处理；逆解基底后再应用目标，避免重复增加饱和度。
    u,v=inverse((r-y)/1.402,(b-y)/1.772,base)
    cr,cb=forward(u,v,target)
    return (y+1.402*cr,y-.7141*cr-.3441*cb,y+1.772*cb)
