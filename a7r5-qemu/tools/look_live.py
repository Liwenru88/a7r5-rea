"""逐次原厂参数窗口及参考渲染；不提供完整 CP/ISP 或设备后端。"""
import bisect
import colorsys
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import tempfile
import time
import uuid
import warnings

from PIL import Image,ImageCms,ImageOps
from look_materials import load,regular,sha,NAMES
from look_native import execute,expected_bank
from look_reference import decode_srgb,encode_srgb,relative_matrix,unpack_bank,lut_delta,fixture,save_png
from runtime_manifest import LAB,digest
from look_chroma import relative as relative_chroma

# 原机十项顺序保持不变，候选 AP 菜单追加 FL2/FL3，再列六个 ST 自定义槽。
CAMERA_LOOKS=('ST','PT','NT','VV','VV2','FL','IN','SH','BW','SE','FL2','FL3')
LOOKS=(*CAMERA_LOOKS,*NAMES)
AP_MAP=(0,3,2,1,16,15,17,18,5,13,19,20)
BOUNDARY='软件参考渲染｜非原厂 ISP 输出｜未作 A7R5 实拍标定'


def selection(look,names=NAMES):
    if look in CAMERA_LOOKS:return (0,CAMERA_LOOKS.index(look),AP_MAP[CAMERA_LOOKS.index(look)])
    if look in names:return (10+names.index(look),0,249+names.index(look))
    raise ValueError('未知外观')


def gamma_axis(record):
    """解码当前照片记录的129点横轴；其他段数不猜测或截短。"""
    if len(record)!=576:raise ValueError('Gamma 记录长度不符')
    widths=(32,32,64,128,256,512,1024,2048,4096,8192,16384,32768)
    result=[0];start=0
    for width,shift in zip(widths,record[0x204:0x210]):
        if shift>15 or width>>shift==0:raise ValueError('Gamma 分段步长无效')
        step=width>>shift;count=width//step
        if len(result)+count>129:raise ValueError('Gamma 分段采样超限')
        result.extend(min(65535,start+i*step) for i in range(1,count+1));start+=width
    if len(result)!=129 or any(a>=b for a,b in zip(result,result[1:])):
        raise ValueError('Gamma 分段横轴不完整或非递增')
    return tuple(result)


def matrix_q10(raw,endpoint):
    if len(raw)!=54 or type(endpoint) is not int or not 0<=endpoint<3:
        raise ValueError('矩阵端点或长度不符')
    return tuple(v/1024 for v in struct.unpack_from('<9h',raw,endpoint*18))


def native_rows(raw,files,marker,level,fixed,movie,*,require_chroma=False):
    lines=raw.decode('ascii').splitlines()
    if not lines or lines[0]!='LOOK_LIVE_BEGIN' or lines[-1]!='LOOK_LIVE_END':
        raise ValueError('CP 本次输出不完整')
    rows={}
    for line in lines[1:-1]:
        m=re.fullmatch(r'([SBHMGIXYTLCPND]) ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]+)',line)
        if not m:raise ValueError('CP 本次输出格式不符')
        tag,a,b,value=m.groups();key=(tag,int(a,16),int(b,16))
        if key in rows:raise ValueError('CP 本次输出重复')
        rows[key]=bytes.fromhex(value)
    expected={};result=[];cp=files['cpapp-b.bin']
    joint=json.loads(files['joint-layout.json']) if 'joint-layout.json' in files else None
    from look_joint import memory,curve,GAMMA_VA
    prop=files['matrix-fixed.bin' if fixed else 'matrix-before.bin']
    for which,color in enumerate((0,marker)):
        sizes={'S':400,'B':6,'H':66,'G':96,'I':96,'X':516,'Y':516}
        for tag,size in sizes.items():expected[tag,which,color]=size
        state=rows.get(('S',which,color),b'')
        if len(state)!=400:raise ValueError('CP 完整选择器没有返回')
        profile=state[1]
        if not 0<=profile<=57:raise ValueError('不支持的原厂矩阵 profile')
        if color in (19,20) and profile!=(56 if movie else 54)+(color==20):
            raise ValueError('FL2/FL3 原厂 profile 不符')
        has_chroma=require_chroma or any((tag,which,color) in rows for tag in ('C','P','N'))
        cc1=None;applied=None;mono=None
        basis=joint['basis'][color-249] if joint and 249<=color<=254 else None
        if has_chroma:
            for tag,size in {'C':48,'P':16,'N':2}.items():expected[tag,which,color]=size
            if profile in (52,53):source=bytes(48)
            elif profile>=54:
                offset=0xbef3ec-0x108000+(profile-54)*48;source=cp[offset:offset+48]
            else:
                style=files['style-property.bin'];bank_id=style[0x1200+profile]
                if bank_id>39:bank_id=0
                offset=0x1250+bank_id*64;source=style[offset:offset+48]
            coefficients=struct.unpack('<24h',source)
            absolute=coefficients[:8]+tuple(coefficients[i]+coefficients[i%8] for i in range(8,24))
            if basis:absolute=tuple(a+d for a,d in zip(absolute,sum(basis['chroma_planes'],[])))
            cc1=rows.get(('C',which,color),b'')
            if cc1!=struct.pack('<24H',*(v&65535 for v in absolute)):
                raise ValueError('CC1 原厂读取与差分展开不符')
            applied=rows.get(('P',which,color),b'');mono=rows.get(('N',which,color))
            if applied!=cc1[:16]:raise ValueError('当前零调整条件的 CC1 应用结果不符')
            if joint or ('D',which,color) in rows:
                expected['D',which,color]=32
                second=rows.get(('D',which,color),b'')
                expected_second=bytes(32) if profile==52 or profile>=54 else cc1[:16]+files['style-property.bin'][0xf00:0xf10]
                if second!=expected_second:
                    raise ValueError('CC1第二域原厂读取或增量不符')
            expected_mode=2 if color==5 else 1 if color==13 else 0
            if state[8]!=expected_mode or mono!=bytes((expected_mode==1,expected_mode==2)):
                raise ValueError('原厂 BW／SE 模式与应用标志不符')
        base=rows.get(('B',which,color))
        if base!=struct.pack('<3H',1024,1024,1024):
            raise ValueError('原厂标准条件对角基准发生变化，拒绝猜测校准')
        embedded='cp-matrix-source.bin' in files and profile in (54,55,56,57)
        matrix_prop=files['matrix-fixed.bin'] if embedded else prop
        matrices=[];bank=matrix_prop[0x196+profile]
        for slot in range(16):
            key=('M',which,slot);expected[key]=54
            values=[]
            for group in range(3):
                a,b,c,d,e,f=struct.unpack_from('<6H',matrix_prop,0x1e0+bank*768+group*192+slot*12)
                values.extend((1024+a+b,-a,-b,-c,1024+c+d,-d,-e,-f,1024+e+f))
            if basis:
                extra=[]
                for a,b,c,d,e,f in basis['matrix_planes']:extra.extend((a+b,-a,-b,-c,c+d,-d,-e,-f,e+f))
                values=[a+b for a,b in zip(values,extra)]
            matrix=rows.get(key)
            if matrix!=struct.pack('<27H',*(v&65535 for v in values)):
                raise ValueError('原厂矩阵与独立 Q10 算术不符')
            matrices.append(matrix)
        src=bytearray(96);struct.pack_into('<I',src,0x10,color);src[8]=movie;src[0xb]=1
        if rows.get(('I',which,color))!=src:raise ValueError('Gamma 原始标记被改写')
        gamma=rows.get(('G',which,color),b'')
        if len(gamma)!=96:raise ValueError('Gamma 参数缺失')
        gamma_id=struct.unpack_from('<I',gamma,0x30)[0];gamma_slot=gamma[0x38]
        if gamma_id>(62 if joint else 50) or gamma_slot>6:raise ValueError('不支持的 Gamma 路线')
        normalized_color=0 if color>=249 else color
        expected_gamma=struct.unpack_from('<I',cp,0xf76efc+normalized_color*8)[0]
        if basis:expected_gamma=51+2*(color-249)+int(expected_gamma==10)
        if gamma_id!=expected_gamma or gamma_slot!=6:
            raise ValueError('照片 Gamma 映射与原厂选择表不符')
        # 使用实际 Gamma 函数输出的 ID 和槽号；不再手选 slot0/6。
        ptr=struct.unpack('<I',memory(files,(GAMMA_VA if joint else 0x107e968)+gamma_id*28+gamma_slot*4,4))[0]
        record=memory(files,ptr,576)
        if basis:record=curve(record,basis['tone_q10'])
        x=struct.unpack('<129I',rows[('X',which,color)])
        y=struct.unpack('<129I',rows[('Y',which,color)])
        if x!=gamma_axis(record) or y!=struct.unpack_from('<129I',record):
            raise ValueError('原厂 Gamma 消费输出与分段记录不符，不能回退缓存')
        if color>=249:
            expected['T',which,color]=8;expected['L',which,color]=1620
            table=rows.get(('T',which,color),b'')
            pointer=0x108000+0x108d080+576+32+(color-249)*1215
            if len(table)!=8 or struct.unpack_from('<I',table)[0]!=pointer or table[4:6]!=b'\x01\x02':
                raise ValueError('自定义表选择不符')
            packed=rows.get(('L',which,color))
            if packed!=expected_bank(cp,files[f'slot{color-248}.raw-s8.bin'],level):
                raise ValueError('自定义表本次打包不符')
        else:packed=None
        result.append(dict(profile=profile,bank=bank,matrix_source='CP-joint' if basis else 'CP-embedded' if embedded else 'settings',diagonal=struct.unpack('<3H',base),matrices=matrices,x=x,y=y,gamma=record,
            gamma_id=gamma_id,gamma_slot=gamma_slot,gamma_pointer=hex(ptr),
            sectors=struct.unpack_from('<16H',rows['H',which,color]),packed=packed,
            cc1_coefficients=cc1,cc1_applied=applied,monochrome_flags=mono))
    if set(rows)!=set(expected) or any(len(rows[k])!=n for k,n in expected.items()):
        raise ValueError('CP 本次输出数量或长度不符')
    return result


def interpolate(at,x,y):
    i=min(len(x)-2,max(0,bisect.bisect_right(x,at)-1))
    f=0 if x[i+1]==x[i] else max(0,min(1,(at-x[i])/(x[i+1]-x[i])))
    return y[i]*(1-f)+y[i+1]*f


def gamma_relative(at,base,target,*,common_scale=False):
    if base['x']==target['x'] and base['y']==target['y']:return at
    # 原厂输入坐标由指令确认；sRGB 与该域的联系仍是软件参考假设。
    by=tuple(v/base['y'][-1] for v in base['y'])
    if any(a>b for a,b in zip(by,by[1:])):raise ValueError('ST Gamma 非单调，不能构造相对曲线')
    x=interpolate(at,by,base['x'])
    return max(0,min(1,interpolate(x,target['x'],target['y'])/(base['y'][-1] if common_scale else target['y'][-1])))


def read_image(path,maximum_size=(384,256)):
    """仅从普通照片文件导入缩略副本，不写源文件；ICC、EXIF在缩略前处理。"""
    raw=regular(path,100_000_000)
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as source:
            container=source.format;frames=getattr(source,'n_frames',1)
            if container not in ('JPEG','MPO','PNG','TIFF','WEBP'):
                raise ValueError('仅支持 JPEG／PNG／TIFF／WebP 参考图；不解码 RAW')
            if container=='MPO':
                # Sony 的 JPG 可包含 MPF 主照片及大型缩略图。只接受明确的基线主照片。
                entries=getattr(source,'mpinfo',{}).get(0xb002,[])
                primary=[i for i,row in enumerate(entries)
                    if row.get('Attribute',{}).get('MPType')=='Baseline MP Primary Image']
                if primary!=[0] or len(entries)!=frames or not 1<=frames<=16:
                    raise ValueError('MPF 没有唯一的首帧主照片，拒绝猜测选择')
                source.seek(0)
            elif frames!=1:raise ValueError('只接受单帧图片或带明确主照片的相机 MPF JPEG')
            if source.width*source.height>80_000_000:
                raise ValueError('只接受单帧、最多8000万像素参考图')
            source.load();original=source.size;icc=source.info.get('icc_profile')
            color_space=source.getexif().get_ifd(34665).get(0xa001)
            image=ImageOps.exif_transpose(source)
            image.thumbnail(maximum_size,Image.Resampling.LANCZOS)
            if image.mode not in ('RGB','RGBA','L','LA','P','CMYK'):
                raise ValueError('不支持的照片像素格式')
            alpha=image.convert('RGBA').getchannel('A') if image.mode in ('RGBA','LA','P') else None
            if icc:
                try:
                    profile=ImageCms.ImageCmsProfile(BytesIO(icc))
                    image=ImageCms.profileToProfile(image if image.mode in ('CMYK','L') else image.convert('RGB'),
                        profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
                except Exception as error:raise ValueError('ICC 无法转换，拒绝猜测颜色空间') from error
                color='embedded ICC converted to sRGB'
            else:
                if image.mode=='CMYK':raise ValueError('无 ICC 的 CMYK 无法作为 sRGB 参考')
                if color_space not in (None,1):
                    raise ValueError('图片 EXIF 声明非sRGB且无ICC，不能擅自按sRGB解释')
                image=image.convert('RGB');color='EXIF declares sRGB; no ICC' if color_space==1 else 'no ICC; explicitly assumed sRGB'
            if alpha is not None:
                background=Image.new('RGB',image.size,'white');background.paste(image,mask=alpha);image=background
            return image.copy(),{'source_name':Path(path).name,'source_sha256':sha(raw),
                'source_bytes':len(raw),'original_dimensions':original,'preview_dimensions':image.size,
                'container_format':container,'container_frames':frames,'selected_frame':0,
                'EXIF_color_space':color_space,
                'color_management':color,'EXIF_orientation_applied':True,
                'source_modified':False,'input_is_RAW':False,
                'ST_like_input_assumed':True,'input_warning':'已渲染照片可能已有外观，不能等同传感器 RAW'}


class LiveEngine:
    def __init__(self,materials):
        self.folder=Path(materials).absolute();self.files,self.receipt=load(self.folder)
        self.names=tuple(s['name'] for s in json.loads(self.files['six-looks.json'])['slots'])
        self.looks=(*CAMERA_LOOKS,*self.names)
        if 'style-property.bin' not in self.files:raise ValueError('实时选择需要第二版隔离风格属性材料')
        self.response=json.loads(self.files['rendering-model.json'])['response_matrix']

    def capture(self,look,*,fixed=None,level=8,movie=False):
        selector,base,expected=selection(look,self.names)
        if fixed is None:fixed='cp-matrix-source.bin' not in self.files
        if type(level) is not int or not 1<=level<=8 or type(fixed) is not bool or type(movie) is not bool:
            raise ValueError('实时参数范围不符')
        if movie:raise ValueError('逐次参考仅支持照片上下文；视频 Gamma 与上下文尚未适配，不回退参数')
        started=time.monotonic();nonce=uuid.uuid4().hex
        folder=Path(tempfile.mkdtemp(prefix='look-selection-',dir=LAB/'runs'))
        receipt={'schema':2,'request':nonce,'look':look,'materials':str(self.folder),
            'camera_io':False,'AP_CP_transport_verified':False,'ISP_pixels_verified':False,
            'synthetic_context':True,'result_cache_used':False,'matrix_fixed_in_fixture':fixed,
            'CP_embedded_candidate':'cp-matrix-source.bin' in self.files,
            'device_deployment_ready':False,
            'level':level,'movie':movie}
        if self.receipt['schema']==7:
            receipt['joint_parameter_candidate']=True
            receipt['physical_A7R5_color_accuracy_verified']=False
            if look in self.names:
                receipt['joint_parameter_basis']=json.loads(self.files['joint-layout.json'])['basis'][self.names.index(look)]
        try:
            ap=execute('ap',self.folder,request=[selector,base]);receipt['AP_run']=str(ap)
            raw=regular(ap/'console.log',1024)
            m=re.fullmatch(rb'A ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8})\n',raw)
            if not m or tuple(int(v,16) for v in m.groups())!=(selector,base,expected):
                raise ValueError('本次 AP 原生选择结果不符')
            marker=int(m[3],16);receipt['AP_marker']=marker
            cp=execute('cp',self.folder,request=[marker,level,int(fixed),int(movie)]);receipt['CP_run']=str(cp)
            files,_=load(self.folder)
            result=native_rows(regular(cp/'console.log',100000),files,marker,level,fixed,movie,require_chroma=True)
            receipt.update(status='passed',native_parameter_ms=round((time.monotonic()-started)*1000,2),
                raw_outputs={which:digest(Path(receipt[which+'_run'])/'console.log') for which in ('AP','CP')},
                native_parameters=[{k:([v.hex() for v in val] if k=='matrices' else val.hex() if isinstance(val,bytes) else val)
                    for k,val in p.items()} for p in result])
        except Exception as error:
            receipt.update(status='failed',error=str(error));raise
        finally:(folder/'result.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        return result,receipt|{'selection_receipt':str(folder/'result.json')}

    def render(self,image,look,*,endpoint=0,slot=-1,gamma_diagnostic=True,input_audit=None,**options):
        if image.mode!='RGB' or image.width*image.height>150_000:
            raise ValueError('参考输入必须是受限 RGB 缩略图')
        if type(slot) is not int or not -1<=slot<16 or type(endpoint) is not int or not 0<=endpoint<3:
            raise ValueError('矩阵子槽或端点不符')
        native,audit=self.capture(look,**options);base,target=native
        base_cc1=struct.unpack('<8h',base['cc1_applied']);target_cc1=struct.unpack('<8h',target['cc1_applied'])
        matrices=[relative_matrix(matrix_q10(t,endpoint),matrix_q10(b,endpoint))
            for t,b in zip(target['matrices'],base['matrices'])]
        sectors=tuple(v/1024 for v in target['sectors'])
        if sectors!=tuple(i/16 for i in range(16)):raise ValueError('参考模型尚未支持非均匀色相分区')
        grid=unpack_bank(self.files['cpapp-b.bin'],target['packed']) if target['packed'] else None
        start=time.monotonic();pixels=[]
        # 曲线只依赖本次参数；256级内插表仅在本次渲染内使用，不跨请求缓存参数。
        common_scale='joint_parameter_basis' in audit
        gamma_table=[gamma_relative(v/1024,base,target,common_scale=common_scale) for v in range(1025)] if gamma_diagnostic else None
        for rgb8 in image.get_flattened_data():
            rgb=tuple(v/255 for v in rgb8);linear=tuple(decode_srgb(v) for v in rgb)
            if slot==-1:
                hue=colorsys.rgb_to_hsv(*rgb)[0]*16;low=int(hue)%16;f=hue-int(hue)
                matrix=tuple((1-f)*a+f*b for a,b in zip(matrices[low],matrices[(low+1)%16]))
            else:matrix=matrices[slot]
            mapped=[encode_srgb(sum(matrix[c*3+j]*linear[j] for j in range(3))) for c in range(3)]
            if gamma_table is not None:
                corrected=[]
                for v in mapped:
                    at=v*1024;i=min(1023,int(at));f=at-i
                    corrected.append(gamma_table[i]*(1-f)+gamma_table[i+1]*f)
                mapped=corrected
            mapped=relative_chroma(mapped,base_cc1,target_cc1)
            mapped=[max(0,min(1,v)) for v in mapped]
            if grid is not None:
                delta=lut_delta(mapped,grid)
                mapped=[max(0,min(1,mapped[c]+sum(delta[j]*self.response[j][c] for j in range(3)))) for c in range(3)]
            pixels.append(tuple(max(0,min(255,round(v*255))) for v in mapped))
        out=Image.new('RGB',image.size);out.putdata(pixels)
        audit.update(CP_profile=target['profile'],matrix_bank=target['bank'],matrix_slot=slot,light_endpoint=endpoint,
            matrix_source=target['matrix_source'],
            matrix_divisor=1024,native_diagonal_reference=target['diagonal'],
            matrix_coordinate='relative Mlook * inverse(Mst) in linear sRGB; ISP space unverified',
            hue_coordinate='16 native boundaries; HSV phase and interpolation are reference assumptions' if slot==-1 else 'manual diagnostic sector',
            Gamma_curve_applied=gamma_diagnostic,Gamma_axis='native CP constructor; 129 nonuniform points, last=65535',
            gamma_id=target['gamma_id'],gamma_slot=target['gamma_slot'],gamma_pointer=target['gamma_pointer'],
            cc1_native_application_verified=True,cc1_applied_coefficients=target_cc1,
            cc1_native_function='0x71e670 lookup -> 0x231eb8 parameter application',
            cc1_reference_model='signed cross coupling and gain; relative to ST in encoded chroma space',
            cc1_pixel_formula_verified_on_A7R5=False,
            monochrome_flags=list(target['monochrome_flags']),
            SE_tint_verified=False,SE_preview='native zero-gain monochrome base only; sepia hardware tint unresolved' if target['monochrome_flags'][0] else None,
            Gamma_pixel_domain='normalized relative-to-ST reference; ISP encoding and order unverified',
            Gamma_normalization='common ST ordinate scale; joint tone gain retained' if common_scale else 'separate endpoints; legacy reference behavior',
            rendering_ms=round((time.monotonic()-start)*1000,2),
            input=input_audit or {'source':'deterministic virtual sRGB chart'},
            partial_original_look_rendering=look in CAMERA_LOOKS and look!='ST',
            unsupported_pixel_stages='A7R5 pixel-exact CC1, sepia tint, runtime calibration, sharpness and full ISP not reproduced',
            reference_rendering=True,native_pixel_pipeline_verified=False,boundary=BOUNDARY)
        audit['output_pixels_sha256']=sha(out.tobytes())
        audit['boundary_channel_fraction']=sum(v in (0,255) for v in out.tobytes())/len(out.tobytes())
        path=Path(audit['selection_receipt']).parent
        save_png(out,path/'reference.png',BOUNDARY+' | '+look)
        (path/'render.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
        return out,audit


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials',required=True,type=Path)
    parser.add_argument('--look',default='ST')
    parser.add_argument('--image',type=Path)
    parser.add_argument('--all',action='store_true',help='对18项分别执行新的AP/CP参数窗口并渲染')
    args=parser.parse_args();engine=LiveEngine(args.materials)
    image,audit=read_image(args.image) if args.image else (fixture(),None)
    folder=Path(tempfile.mkdtemp(prefix='look-live-gallery-',dir=LAB/'runs'));rows=[]
    for index,look in enumerate(engine.looks if args.all else (args.look,)):
        result,record=engine.render(image,look,input_audit=audit)
        save_png(result,folder/f'{index:02}-{look.replace("/","-")}.png',BOUNDARY+' | '+look)
        rows.append(record)
        print(look,record['selection_receipt'],flush=True)
    (folder/'summary.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print(folder,flush=True)


if __name__=='__main__':main()
