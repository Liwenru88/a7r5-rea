"""创意外观软件参考渲染：原厂参数窗口与像素近似严格分开。"""
import argparse
import bisect
import colorsys
import itertools
import json
import math
from pathlib import Path
import struct
import tempfile

from PIL import Image, ImageDraw, PngImagePlugin
from look_materials import load, regular, sha, NAMES
from look_native import parse_ap, parse_cp
from runtime_manifest import LAB, digest

LOOKS=('ST','FL2','FL3',*NAMES)
BOUNDARY='软件参考渲染｜虚拟测试图｜非原厂 ISP 输出｜未作 A7R5 实拍标定'


def decode_srgb(v):
    return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4


def encode_srgb(v):
    v=max(0,min(1,v))
    return 12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055


def native_matrix(raw, endpoint):
    if len(raw)!=54 or type(endpoint) is not int or not 0<=endpoint<3:
        raise ValueError('矩阵长度或光源端点不符')
    return tuple(v/256 for v in struct.unpack_from('<9h',raw,endpoint*18))


def relative_matrix(target, base):
    """以已渲染 ST 为输入：Mlook · inverse(Mst)，不重复施加绝对传感器矩阵。"""
    a,b,c,d,e,f,g,h,i=base
    det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    if not math.isfinite(det) or abs(det)<1e-8:raise ValueError('ST 矩阵不可逆，不能构造相对参考')
    inverse=tuple(v/det for v in (e*i-f*h,c*h-b*i,b*f-c*e,f*g-d*i,a*i-c*g,c*d-a*f,d*h-e*g,b*g-a*h,a*e-b*d))
    return tuple(sum(target[r*3+k]*inverse[k*3+c] for k in range(3)) for r in range(3) for c in range(3))


def relative_curve(v,target,base):
    if len(target)!=129 or len(base)!=129 or min(target[-1],base[-1])<=0:
        raise ValueError('Gamma 诊断记录不符')
    if any(a>b for values in (base,target) for a,b in zip(values,values[1:])):
        raise ValueError('Gamma 非单调，不能推测反函数')
    if target==base:return v
    y=[n/base[-1] for n in base]
    index=min(127,max(0,bisect.bisect_right(y,v)-1))
    f=0 if y[index+1]==y[index] else max(0,min(1,(v-y[index])/(y[index+1]-y[index])))
    return (target[index]*(1-f)+target[index+1]*f)/target[-1]


def unpack_bank(cp, bank):
    if len(bank)!=1620:raise ValueError('原生色表银行长度不符')
    order=struct.unpack_from('<405H',cp,0xd841d8)
    if sorted(order)!=list(range(405)):raise ValueError('硬件节点排列不符')
    values=[]
    for i in range(405):
        value=struct.unpack_from('<I',bank,order[i]*4)[0]
        if value & ~((127<<22)|(127<<12)|(127<<2)):raise ValueError('硬件银行保留位不为零')
        row=[]
        for shift in (22,12,2):
            v=value>>shift&127;row.append(v-128 if v&64 else v)
        values.append(tuple(row))
    return values


def lut_delta(rgb, grid):
    """沿用既有 BT.601 limited 坐标假设；不是已确认的 Sony ISP 坐标。"""
    r,g,b=rgb;y=.299*r+.587*g+.114*b
    c1=(b-y)/(2*(1-.114));c2=(r-y)/(2*(1-.299))
    at=[(y*255-16)/219*4,c1*255/224*8+4,c2*255/224*8+4]
    at=[max(0,min(v,limit)) for v,limit in zip(at,(4,8,8))]
    lo=[min(int(v),limit-1) for v,limit in zip(at,(4,8,8))];frac=[v-i for v,i in zip(at,lo)]
    result=[0.,0.,0.]
    for bits in itertools.product((0,1),repeat=3):
        weight=math.prod(f if bit else 1-f for bit,f in zip(bits,frac))
        i=(lo[0]+bits[0])*81+(lo[1]+bits[1])*9+lo[2]+bits[2]
        for c in range(3):result[c]+=grid[i][c]*weight/256
    return result


def pixel(rgb, matrix, grid=None, response=None, curve=None, base_curve=None):
    # 输入是已编码 sRGB；矩阵用于线性 RGB 是显式参考假设。
    linear=[decode_srgb(v) for v in rgb]
    mapped=[encode_srgb(sum(matrix[c*3+j]*linear[j] for j in range(3))) for c in range(3)]
    if grid is not None:
        delta=lut_delta(mapped,grid)
        mapped=[max(0,min(1,mapped[c]+sum(delta[j]*response[j][c] for j in range(3)))) for c in range(3)]
    if curve is not None:
        # 仅供显式开启的 Gamma 诊断；等距横轴不是原厂分段横轴。
        mapped=[relative_curve(v,curve,base_curve) for v in mapped]
    return tuple(max(0,min(255,round(v*255))) for v in mapped)


class Dataset:
    def __init__(self, parameters):
        self.path=Path(parameters).absolute()
        self.record=json.loads(regular(self.path,2_000_000))
        if self.record.get('schema')!=1 or self.record.get('ISP_pixels_verified') is not False:
            raise ValueError('参数回执边界不符')
        self.files,self.material_receipt=load(self.record['materials'])
        if self.record.get('material_files')!={k:sha(v) for k,v in self.files.items()}:
            raise ValueError('参数回执与材料不一致')
        for which in ('AP','CP'):
            run=Path(self.record[which+'_run'])
            if run.parent!=LAB/'runs' or run.is_symlink():raise ValueError('运行证据路径越界')
            outcome=json.loads(regular(run/'result.json',100000))
            raw=regular(run/'console.log',1024*1024)
            if outcome['status']!='instruction_window_finished' or outcome['exit']['exit_code']!=0 or sha(raw)!=outcome['console_sha256']:
                raise ValueError('指令证据未完整退出或已变化')
            actual=parse_ap(raw) if which=='AP' else parse_cp(raw,self.files)
            if actual!=self.record['AP_mapping' if which=='AP' else 'CP_records']:
                raise ValueError('参数缓存与原始指令输出不符')
        self.cp=self.files['cpapp-b.bin'];self.native=self.record['CP_records']
        self.response=json.loads(self.files['rendering-model.json'])['response_matrix']

    def parameters(self, look, *, fixed=True, endpoint=0, slot=0, level=8, movie=False):
        if look not in LOOKS or type(slot) is not int or not 0<=slot<16 or type(level) is not int or not 1<=level<=8:
            raise ValueError('外观、矩阵子槽或等级不符')
        custom=look in NAMES
        profile=(56 if movie else 54)+(look=='FL3') if look in ('FL2','FL3') else 0
        absolute=native_matrix(bytes.fromhex(self.native[f'M:{profile}:{(16 if fixed else 0)+slot}']),endpoint)
        base=native_matrix(bytes.fromhex(self.native[f'M:0:{(16 if fixed else 0)+slot}']),endpoint)
        matrix=relative_matrix(absolute,base)
        color=19 if look=='FL2' else 20 if look=='FL3' else 0
        gamma_id=struct.unpack_from('<I',self.cp,0xf76efc+color*8+int(movie)*4)[0]
        # still 用0，movie 用6，仅作为各已存在记录的明确代表，不猜测空指针回退。
        gamma_slot=6 if movie else 0
        pointer=struct.unpack_from('<I',self.cp,0xf76968+gamma_id*28+gamma_slot*4)[0]
        if not 0x108000<=pointer<=0x108000+len(self.cp)-576:raise ValueError('Gamma 指针未支持')
        gamma=self.cp[pointer-0x108000:pointer-0x108000+576]
        grid=None;marker=color;bank=None
        if custom:
            marker=self.record['AP_mapping'][f'{10+NAMES.index(look)}:0']
            bank=bytes.fromhex(self.native[f'L:{marker}:{level}'])
            grid=unpack_bank(self.cp,bank)
        return {'look':look,'matrix':matrix,'grid':grid,'gamma':gamma,'curve':struct.unpack_from('<129I',gamma),
                'audit':{'look':look,'AP_marker':marker,'CP_profile':profile,'matrix_bank':self.files['matrix-fixed.bin' if fixed else 'matrix-before.bin'][0x196+profile],
                'matrix_slot':slot,'light_endpoint':endpoint,'level':level,'movie':movie,'gamma_id':gamma_id,
                'gamma_slot':gamma_slot,'gamma_pointer':hex(pointer),'gamma_sha256':sha(gamma),
                'native_packed_bank_sha256':sha(bank) if bank else None,
                'native_matrix_Q8':absolute,'reference_matrix_relative_to_ST':matrix,
                'synthetic_calibration_vector':[256,256,256],
                'pixel_interpretation':'matrix stress diagnostic; coordinate/calibration unverified' if look in ('FL2','FL3') else 'provisional A7C II LUT response on ST-like sRGB',
                'matrix_fixed_in_fixture':fixed,'native_parameters_verified':True,
                'native_pixel_pipeline_verified':False}}

    def render(self, image, look, *, gamma_diagnostic=False, **options):
        if image.mode!='RGB':raise ValueError('参考输入必须为 RGB')
        if image.width*image.height>1_000_000:raise ValueError('参考输入像素数超过限制')
        p=self.parameters(look,**options)
        baseline=self.parameters('ST',**options)['curve'] if gamma_diagnostic else None
        pixels=[pixel(tuple(v/255 for v in rgb),p['matrix'],p['grid'],self.response,
                      p['curve'] if gamma_diagnostic else None,baseline) for rgb in image.get_flattened_data()]
        out=Image.new('RGB',image.size);out.putdata(pixels)
        source=image.tobytes();actual=out.tobytes()
        return out,p['audit']|{'Gamma_curve_applied':gamma_diagnostic,
            'Gamma_coordinate_assumption':'relative to ST; uniform index diagnostic only' if gamma_diagnostic else 'not applied; native route/bytes audited separately',
            'mean_abs_sRGB_difference':sum(abs(a-b) for a,b in zip(source,actual))/(255*len(source)),
            'boundary_channel_fraction':sum(v in (0,255) for v in actual)/len(actual),
            'reference_rendering':True,'boundary':BOUNDARY}


def fixture():
    """确定性虚拟 sRGB 图；不使用真实照片、DCP 原图或相机资料。"""
    im=Image.new('RGB',(240,160));pixels=im.load()
    patches=[(115,82,68),(194,150,130),(98,122,157),(87,108,67),(133,128,177),(103,189,170),
             (214,126,44),(80,91,166),(193,90,99),(94,60,108),(157,188,64),(224,163,46),
             (56,61,150),(70,148,73),(175,54,60),(231,199,31),(187,86,149),(8,133,161)]
    for y in range(160):
        for x in range(240):
            if y<60:rgb=patches[(y//20)*6+x//40]
            elif y<85:rgb=(round(x/239*255),)*3
            elif y<120:rgb=tuple(round(v*255) for v in colorsys.hsv_to_rgb(x/240,1,(y-85)/34*.8+.2))
            else:
                base=(194,150,130) if x<120 else (98,122,157)
                shade=.2+.8*(y-120)/39;rgb=tuple(round(v*shade) for v in base)
            pixels[x,y]=rgb
    return im


def save_png(image,path,description):
    info=PngImagePlugin.PngInfo();info.add(b'sRGB',b'\0');info.add_text('Description',description)
    image.save(path,pnginfo=info)


def gamma_plot(data):
    im=Image.new('RGB',(640,280),'#20232b');d=ImageDraw.Draw(im)
    d.text((12,8),'GAMMA RECORD SAMPLES - index axis, not verified Sony input axis',fill='white')
    for look,color in [('ST','#dddddd'),('FL2','#ffba69'),('FL3','#6bbfff')]:
        values=data.parameters(look)['curve'];last=max(values)
        points=[(30+i/128*570,245-v/last*200) for i,v in enumerate(values)]
        d.line(points,fill=color,width=2);d.text((50+LOOKS.index(look)*90,258),look,fill=color)
    return im


def generate(parameters):
    data=Dataset(parameters);out=Path(tempfile.mkdtemp(prefix='look-reference-',dir=LAB/'runs'))
    original=fixture();save_png(original,out/'virtual-input.png',BOUNDARY)
    gallery=Image.new('RGB',(3*320,3*255),'#20232b');draw=ImageDraw.Draw(gallery)
    audits={};images={}
    for index,look in enumerate(LOOKS):
        rendered,audit=data.render(original,look);audits[look]=audit;images[look]=rendered
        save_png(rendered,out/f'look-{index}.png',BOUNDARY+' | '+look)
        x=index%3*320;y=index//3*255
        draw.text((x+12,y+8),look,fill='white')
        note='MATRIX STRESS TEST / AXIS UNVERIFIED' if look in ('FL2','FL3') else 'SOFTWARE REFERENCE / NOT SONY ISP'
        draw.text((x+12,y+27),note,fill='#ffba69')
        gallery.paste(rendered.resize((300,200)),(x+10,y+46))
    # 基线复现只比较矩阵，避免 Gamma 差异掩盖“共用矩阵”问题。
    baseline={}
    for look in ('FL2','FL3'):
        image,audit=data.render(original,look,fixed=False)
        save_png(image,out/(look+'-missing-matrix.png'),BOUNDARY+' | baseline missing matrix')
        baseline[look]=sha(image.tobytes())
    if baseline['FL2']!=baseline['FL3']:raise ValueError('缺失矩阵的相同画面未复现')
    if images['FL2'].tobytes()==images['FL3'].tobytes():raise ValueError('修复后 FL2/FL3 参考画面仍相同')
    if len({im.tobytes() for look,im in images.items() if look in NAMES})!=6:
        raise ValueError('六款参考画面存在重复映射')
    save_png(gallery,out/'comparison.png',BOUNDARY)
    save_png(gamma_plot(data),out/'gamma-records.png',BOUNDARY+' | native sample values, unverified x axis')
    summary={'scope':BOUNDARY,'parameters':str(data.path),'audits':audits,'missing_matrix_reproduced':True,
        'fixed_FL2_FL3_reference_pixels_differ':True,'six_reference_outputs_distinct':True,
        'Gamma_default':'native route and record audit only; software curve application off',
        'reference_assumptions':['Mlook * inverse(Mst) in linear sRGB; input is ST-like sRGB, not RAW','BT.601 limited LUT coordinates',
                                 'A7C II one-scene response matrix; not A7R5 calibration'],
        'ISP_pixels_verified':False,'camera_io':False,'original_images_modified':False,
        'files':{p.name:digest(p) for p in out.glob('*.png')}}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--research-root',type=Path,
        help='已有项目内材料目录；省略时使用固定本地基线，兼容旧工程根参数')
    a=sub.add_parser('capture');a.add_argument('--materials',required=True,type=Path)
    a=sub.add_parser('render');a.add_argument('--parameters',required=True,type=Path)
    a=sub.add_parser('ui');a.add_argument('--parameters',required=True,type=Path)
    args=p.parse_args()
    if args.action=='prepare':
        from look_materials import prepare
        print(prepare(args.research_root))
    elif args.action=='capture':
        from look_native import capture
        print(capture(args.materials))
    elif args.action=='render':print(generate(args.parameters))
    else:
        from look_reference_ui import launch
        launch(args.parameters)


if __name__=='__main__':main()
