"""在固定BIN刻度上联合学习CC1、矩阵、Gamma和网格的舍入方向。"""
import numpy as np
from apple_gpu import SmoothGPU


class RoundedGPU(SmoothGPU):
    override_gamma = None

    def gamma(self, vector):
        return super().gamma(vector) if self.override_gamma is None else self.override_gamma


class Rounding:
    def __init__(self, tools, vector, gamma, grid):
        self.tools = tools
        t = tools.torch
        self.vector = vector.detach()
        coefficients = vector[8:104]
        self.negative = coefficients < 0
        self.zero = coefficients.abs()*1024 < .5
        matrix_units = t.where(self.negative, (coefficients.abs()*1024-1)/2, coefficients*1024)
        self.units = t.cat((vector[:4]*256, vector[4:8]*64, matrix_units,
                            gamma[1:]*8, grid.reshape(-1))).detach()
        self.floor = self.units.floor()
        fraction = (self.units-self.floor).clamp(.001, .999)
        # 反解扩展sigmoid，使软舍入的初始值等于原浮点小数部分。
        probability = (fraction+.1)/1.2
        self.initial = (probability/(1-probability)).log().detach()
        self.ngamma = len(gamma)-1

    def values(self, logits, hard=False):
        t = self.tools.torch
        soft = (1.2*logits.sigmoid()-.1).clamp(0, 1)
        rounded = (soft >= .5).to(soft.dtype) if hard else soft
        values = self.floor + rounded
        cc = t.cat((values[:4]/256, values[4:8]/64))
        matrix = t.where(self.negative, -(2*values[8:104]+1)/1024, values[8:104]/1024)
        matrix = t.where(self.zero, 0, matrix)
        gamma = t.cat((values.new_zeros(1), values[104:104+self.ngamma]/8))
        # 相邻节点落在同一整数区间时仍保持Gamma单调。
        gamma = t.cummax(gamma, 0).values
        table = values[104+self.ngamma:].reshape(405, 3).clamp(-64, 63)
        vector = t.cat((cc, matrix, self.vector[104:]))
        return vector, gamma, table, soft

    def penalty(self, soft, progress):
        beta = 20 + (2-20)*progress
        return (1-(2*soft-1).abs().pow(beta)).mean()
