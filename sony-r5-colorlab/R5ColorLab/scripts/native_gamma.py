"""原生 129 点与 RAW 128 点的显式桥接；BIN 布局保持不变。"""
import hashlib
import struct

import numpy as np


POLICY = 'native-gamma129-fixed-axis/1'
SOURCE_CP_SHA256 = '8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32'
SOURCE_RECORD_SHA256 = 'f4e9f31bce38b4c705721a501c7597705852e671bc39baf60b02dac8b88f95ac'
AXIS_SHA256 = '67644a74c4c7c63095de900646f7f87e49bc7185bb40a4b880f7caf0ec6a1770'


def _axis():
    # 已绑定 CP 记录 +0x204 的分段指数，横坐标不均匀。
    spans = (32, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)
    starts = (0, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)
    exponents = (0, 0, 1, 2, 3, 4, 5, 4, 3, 4, 4, 3)
    result = [0]
    for width, start, exponent in zip(spans, starts, exponents):
        step = width >> exponent
        result.extend(min(65535, start+j*step) for j in range(1, width//step+1))
    encoded = struct.pack('<129I', *result)
    if hashlib.sha256(encoded).hexdigest() != AXIS_SHA256:
        raise ValueError('原生 Gamma 横坐标摘要不符')
    axis = np.asarray(result, dtype=np.int64)
    axis.setflags(write=False)
    return axis


CP_AXIS = _axis()
EDIT_AXIS = CP_AXIS * 32
RAW_INDICES = np.r_[np.arange(127), 128]
RAW_AXIS = EDIT_AXIS[RAW_INDICES]
for _value in (EDIT_AXIS, RAW_INDICES, RAW_AXIS):
    _value.setflags(write=False)


def validate(values):
    y = np.asarray(values)
    if (y.shape != (129,) or not np.isfinite(y).all() or np.any(y != np.trunc(y))
            or y[0] != 0 or np.any(y < 0) or np.any(y > 131071)
            or np.any(np.diff(y) < 0)):
        raise ValueError('原生 Gamma 需要零起点、单调的 129 个 17 位整数')
    return y.astype(np.int64)


def from_raw(values):
    """RAW 终点映射到 CP[128]，仅插值补出没有 RAW 节点的 CP[127]。"""
    raw = np.asarray(values)
    if (raw.shape != (128,) or not np.isfinite(raw).all()
            or np.any(raw != np.trunc(raw)) or raw[0] != 0
            or np.any(raw < 0) or np.any(raw > 262143) or np.any(np.diff(raw) < 0)):
        raise ValueError('RAW Gamma 需要单调的 128 个 18 位整数')
    q = (raw.astype(np.int64)+1)//2
    # 用桥接后的整数节点重建缺失值，不把 RAW 最后一点放到 61440。
    middle_raw = 2*q[126] + (2*(q[127]-q[126])*4096)//8191
    return validate(np.r_[q[:127], (middle_raw+1)//2, q[127]])


def raw_projection(values, *, require_exact=False):
    q = validate(values)
    raw = 2*q[RAW_INDICES]
    if require_exact and not np.array_equal(from_raw(raw), q):
        raise ValueError('完整 129 点 Gamma 不能无损写入 128 点 RAW；请使用 BIN 或工作台预览')
    if require_exact:
        from edit_native_model import expand_gamma
        from edit_color_pipeline import static_table
        neutral=static_table(0x100249e60+18*0x1004,1025,'<i4')
        for contrast in (None,neutral):
            if not np.array_equal(expand_gamma(EDIT_AXIS,2*q,contrast),
                                  expand_gamma(RAW_AXIS,raw,contrast)):
                raise ValueError('完整129点Gamma不能无损写入128点RAW：整数插值输出不一致')
    return raw


def parameter_fields(parameters, *, axis=None):
    """新配方显式保存 129 点；旧 RAW 字段仅保留可辨识的投影。"""
    y = np.asarray(parameters['gamma_y'])
    if not np.isfinite(y).all() or np.any(y != np.trunc(y)):
        raise ValueError('Gamma 参数必须为有限整数')
    y = y.astype(np.int64)
    fields = dict(matrix_780f_hex=parameters['matrix_payload'].hex(),
                  cc1_direct_raw=np.asarray(parameters['cc1']).astype(int).tolist())
    if y.shape == (129,):
        if np.any(y % 2):
            raise ValueError('原生 Gamma 的 Edit 单位必须为偶数')
        q = validate(y//2)
        fields.update(gamma_native_129=q.tolist(), gamma_7806_y=raw_projection(q).tolist(),
                      gamma_domain=POLICY)
        if axis is not None:
            if not np.array_equal(axis, EDIT_AXIS):
                raise ValueError('原生 Gamma 横坐标不符')
            fields['gamma_7805_x'] = RAW_AXIS.tolist()
    elif y.shape == (128,):
        fields['gamma_7806_y'] = y.tolist()
        if axis is not None:
            fields['gamma_7805_x'] = np.asarray(axis).tolist()
    else:
        raise ValueError('不支持的 Gamma 参数数量')
    return fields


def parameter_values(fields):
    if 'gamma_native_129' in fields:
        if fields.get('gamma_domain') != POLICY:
            raise ValueError('原生 Gamma 参数域不符')
        q = validate(fields['gamma_native_129'])
        if 'gamma_7806_y' in fields and not np.array_equal(fields['gamma_7806_y'], raw_projection(q)):
            raise ValueError('原生 Gamma 与 RAW 投影不符')
        y = 2*q
    else:
        y = np.asarray(fields['gamma_7806_y'])
    return dict(matrix_payload=bytes.fromhex(fields['matrix_780f_hex']),
                cc1=np.asarray(fields['cc1_direct_raw']), gamma_y=y)


def tensor_table(values, *, contrast=None, device='mps'):
    """完整整数 GPU 查表，限已验证中性对比度；梯度另用同轴连续模型。"""
    import torch
    q = validate(values)
    x = torch.as_tensor(EDIT_AXIS.copy(), device=device, dtype=torch.int32)
    y = torch.as_tensor(2*q, device=device, dtype=torch.float32)
    samples = torch.arange(1, 32768, device=device, dtype=torch.int32)*128
    right = torch.searchsorted(x, samples, right=True)
    left = (right-1).clamp(min=0)
    right = right.clamp(max=128)
    delta = x[right]-x[left]
    # 保留 Edit 的独立 float32 乘、除、加及向零截断顺序。
    v = y[left]-y[right]
    v = v*(x[right]-samples).to(torch.float32)
    v = v/torch.where(delta == 0, 1, delta).to(torch.float32)
    v = v+y[right]
    v = torch.where(delta == 0, y[left], v).trunc().to(torch.int32)
    shifted = v >> 2
    if contrast is not None:
        source = np.asarray(contrast)
        if (source.shape not in ((1024,), (1025,)) or not np.issubdtype(source.dtype,np.integer)
                or np.any(source < 0) or np.any(source > 2147483647)):
            raise ValueError('对比度表需要1024或1025个非负整数')
        from edit_color_pipeline import static_table
        neutral=static_table(0x100249e60+18*0x1004,1025,'<i4')
        if not np.array_equal(source,neutral[:len(source)]):
            raise ValueError('MPS Gamma 当前仅验证了绑定的中性对比度表')
        table = torch.as_tensor(source.copy(), device=device, dtype=torch.float32)
        index = (v >> 8).clamp(max=1023)
        upper = (index+1).clamp(max=1023)
        fraction = (shifted-(v >> 8)*64).to(torch.float32)*(1/64)
        mapped = (table[upper]-table[index])*fraction+table[index]
        shifted = mapped.trunc().to(torch.int32)
    positive = torch.cat((v.new_zeros(1), (shifted >> 2) & 65535))
    return torch.cat(((-positive.flip(0)) & 65535, positive))
