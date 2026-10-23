/* SPDX-License-Identifier: GPL-2.0-or-later
 * 隔离 CP 实验的 DesignWare eDMA 子集。寄存器来源见 native-cp-pcie.md。
 * 不模拟链路训练，不产生 CP 消息；未知模式拒绝执行。
 */
#ifndef A7R5_CP_EDMA_H
#define A7R5_CP_EDMA_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

typedef bool (*CPEDMACopy)(void *, uint64_t, uint64_t, uint32_t);
typedef bool (*CPEDMARead)(void *, uint64_t, void *, uint32_t);
typedef struct CPEDMA {
    uint32_t enable[2], mask[2], status[2], error[2], ll_error_enable[2];
    uint32_t ch[2][8][9], power[2][8], side_enable;
    uint64_t copies, bytes, aborts;
    CPEDMACopy copy;
    CPEDMARead read;
    void *opaque;
} CPEDMA;

static inline void cp_edma_init(CPEDMA *s, CPEDMACopy copy, CPEDMARead read, void *opaque)
{
    memset(s, 0, sizeof(*s));
    s->copy = copy;
    s->read = read;
    s->opaque = opaque;
    /* 模拟板从无任务、无中断、使能关闭开始；不冒充实机 POR 测量值。 */
}

static inline uint32_t cp_edma_le32(const uint8_t *p)
{
    return p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}

static inline bool cp_edma_list(CPEDMA *s, unsigned dir, unsigned n)
{
    uint32_t *r = s->ch[dir][n];
    uint64_t pointer = r[7] | ((uint64_t)r[8] << 32);
    uint32_t cycle = (r[0] >> 8) & 1;
    uint32_t total = 0;
    for (unsigned count=0;count<256;count++) {
        uint8_t desc[24];
        if ((pointer & 3) || pointer > UINT64_MAX-sizeof(desc) || !s->read ||
            !s->read(s->opaque,pointer,desc,sizeof(desc))) {
            return false;
        }
        uint32_t control = cp_edma_le32(desc);
        if ((control & 1) != cycle) {
            /* 消费位不匹配表示等待生产者，不能产生完成通知。 */
            r[0] = (r[0] & ~0x160U) | (cycle<<8) | 0x20;
            r[7] = pointer;
            r[8] = pointer >> 32;
            return true;
        }
        uint64_t src = cp_edma_le32(desc+8) | ((uint64_t)cp_edma_le32(desc+12)<<32);
        if (control & 4) {
            if (control & ~7U) { return false; }
            if (control & 2) { cycle ^= 1; }
            pointer = src;
            continue;
        }
        uint32_t len = cp_edma_le32(desc+4);
        uint64_t dst = cp_edma_le32(desc+16) | ((uint64_t)cp_edma_le32(desc+20)<<32);
        if ((control & ~9U) || !len || len > 16U*1024*1024-total ||
            src > UINT64_MAX-len || dst > UINT64_MAX-len ||
            !s->copy || !s->copy(s->opaque,src,dst,len)) {
            return false;
        }
        s->copies++;
        s->bytes += len;
        total += len;
        if (control & 8) { s->status[dir] |= 1U<<n; }
        pointer += sizeof(desc);
    }
    return false; /* 有界执行；损坏的循环描述符不会无期限占用宿主。 */
}

static inline bool cp_edma_irq(CPEDMA *s)
{
    /* 已知原厂初始化开放全部 EDMA_INT；部分位的通道对应尚未证明。
     * 仅支持全开/全关，不猜测读写方向在侧带中的位序。 */
    return (s->side_enable & 0xffff) == 0xffff &&
        ((s->status[0] & ~s->mask[0]) || (s->status[1] & ~s->mask[1]));
}

static inline void cp_edma_doorbell(CPEDMA *s, unsigned dir, uint32_t value)
{
    unsigned n = value & 7;
    uint32_t *r = s->ch[dir][n];
    uint32_t bit = 1U << n;
    uint64_t src = r[3] | ((uint64_t)r[4] << 32);
    uint64_t dst = r[5] | ((uint64_t)r[6] << 32);
    if (s->enable[dir] && !(value & ~7U) &&
        (r[0] & ~0x160U) == 0x200 && r[1] == 0) {
        if (cp_edma_list(s,dir,n)) { return; }
        s->aborts++;
        r[0] = (r[0] & ~0x60U) | 0x40U;
        s->status[dir] |= bit<<16; /* 旧完成位保持 W1C，不能丢弃已搬运片段。 */
        s->error[dir] |= bit;
        return;
    }
    /* 远端 MSI/停止请求尚未支持；不支持时只报告 abort。
     * 直接模式 LIE=bit3，LLEN=bit9；CP 原厂直接模式正好写 8。 */
    bool ok = s->enable[dir] && !(value & ~7U) && r[0] == 8 &&
        r[1] == 0 && r[2] && r[2] <= 16U * 1024 * 1024 &&
        src <= UINT64_MAX - r[2] && dst <= UINT64_MAX - r[2] &&
        s->copy && s->copy(s->opaque, src, dst, r[2]);
    if (ok) {
        s->copies++;
        s->bytes += r[2];
        r[0] = (r[0] & ~0x60U) | 0x60U; /* stopped */
        r[2] = 0;
        s->status[dir] |= bit;
    } else {
        s->aborts++;
        r[0] = (r[0] & ~0x60U) | 0x40U; /* halted，不能用 complete 放行 */
        s->status[dir] |= bit << 16;
        s->error[dir] |= bit;
    }
}

/* false 表示未知偏移/非法访问，QEMU 包装层必须返回总线错误。 */
static inline bool cp_edma_access(CPEDMA *s, uint32_t off, bool write, uint32_t *v)
{
    unsigned dir, n, word;
    uint32_t *reg = NULL;
    if (off & 3) {
        return false;
    }
    if (off >= 0x200 && off <= 0x1120) {
        dir = ((off - 0x200) >> 8) & 1;
        n = (off - 0x200) >> 9;
        word = (off & 0xff) >> 2;
        if (n >= 8 || word >= 9) {
            return false;
        }
        reg = &s->ch[dir][n][word];
    } else if ((off >= 0x128 && off <= 0x144) ||
               (off >= 0x168 && off <= 0x184)) {
        dir = off >= 0x168;
        n = (off - (dir ? 0x168 : 0x128)) / 4;
        reg = &s->power[dir][n];
    } else {
        switch (off) {
        case 0xc: case 0x2c:
            dir = off == 0x2c;
            if (write && (*v & ~1U)) {
                return false;
            }
            reg = &s->enable[dir];
            break;
        case 0x10: case 0x30:
            if (!write) {
                return false;
            }
            cp_edma_doorbell(s, off == 0x30, *v);
            return true;
        case 0x4c: case 0xa0:
            if (write) {
                return false;
            }
            *v = s->status[off == 0xa0];
            return true;
        case 0x54: case 0xa8:
            reg = &s->mask[off == 0xa8];
            break;
        case 0x58: case 0xac:
            if (!write) {
                return false;
            }
            dir = off == 0xac;
            s->status[dir] &= ~*v; /* W1C，不能因读状态而完成任务 */
            s->error[dir] &= ~(*v >> 16);
            return true;
        case 0x5c: case 0xb4:
            if (write) {
                return false;
            }
            *v = s->error[off == 0xb4];
            return true;
        case 0x90: case 0xc4:
            reg = &s->ll_error_enable[off == 0xc4];
            break;
        default:
            return false;
        }
    }
    if (write) {
        *reg = *v;
    } else {
        *v = *reg;
    }
    return true;
}

static inline bool cp_edma_side_access(CPEDMA *s, uint32_t off, bool write, uint32_t *v)
{
    if (off != 0x20274) {
        return false;
    }
    if (write) {
        uint32_t low = *v & 0xffff;
        if (low && low != 0xffff) {
            return false;
        }
        s->side_enable = *v;
    } else {
        *v = s->side_enable;
    }
    return true;
}

/* 原 CP PCIe 通知使用 GPIO18 bit2/3；没有连接 AP 时输入明确保持低。
 * 只实现 DIR/INEN/FUNC/WDATA 的 RW/SET/CLR 和引脚 RDATA，不合成对端边沿。 */
typedef struct CPGPIO {
    uint32_t dir, input, inen, func, output;
} CPGPIO;

/* PLL0 仅建模原厂使用的配置/请求/等待协议，不模拟模拟电路或频率。
 * 100us是显式虚拟稳定时间，不是Sony芯片参数；未配置初态也不是实测POR。 */
#define CP_PLL0_DELAY_NS UINT64_C(100000)
typedef struct CPSCU {
    uint32_t i2c_clock, i2c_reset, dfs_control, clksel[5], logic_clock, media_clock;
    uint32_t pll0;
    uint64_t pll0_now, pll0_deadline;
    bool pll0_reference_present;
    uint32_t pll_other[4], pll_div[2];
    uint64_t pll_other_deadline[4];
} CPSCU;

static inline bool cp_pll_known(unsigned channel, uint32_t value)
{
    static const uint32_t profiles[5][6]={
        {0x16b00,0x16b00,0x16b02,0x16b02,0x15f00,0x15f00},
        {0x36200,0xc5900,0x36202,0xc5902,0x35f02,0x35f02},
        {0x36f1b,0x36306,0x36f1b,0x36306,0x36f1b,0x36f1b},
        {0x1d7f00,0x1d7f00,0x1d7f02,0x1d7f02,0x175f00,0x175f00},
        {0x1d8f04,0x1d8f04,0x1d8f04,0x1d8f04,0x1d7703,0x1d7703}};
    if (channel>=5) { return false; }
    for (unsigned i=0;i<6;i++) {
        if ((value&~0x19000000U)==profiles[channel][i]) { return true; }
    }
    return false;
}

static inline void cp_pll0_advance(CPSCU *s, uint64_t now)
{
    s->pll0_now=now;
    for (unsigned channel=0;channel<5;channel++) {
        uint32_t *reg=channel?&s->pll_other[channel-1]:&s->pll0;
        uint64_t *deadline=channel?&s->pll_other_deadline[channel-1]:&s->pll0_deadline;
        if (!s->pll0_reference_present) {
            *reg&=~0x01000000U; *deadline=0;
        } else if (*deadline && now>=*deadline) {
            *reg|=0x01000000U; *deadline=0;
        }
    }
}

static inline bool cp_scu_access(CPSCU *s, uint32_t off, bool write, uint32_t *v)
{
    if (off>=0x100 && off<=0x110 && !(off&3)) {
        unsigned channel=(off-0x100)/4;
        uint32_t *reg=channel?&s->pll_other[channel-1]:&s->pll0;
        uint64_t *deadline=channel?&s->pll_other_deadline[channel-1]:&s->pll0_deadline;
        if (!write) { *v=*reg; return true; }
        /* bit24由设备状态产生，软件不能直接置位；其他位保留读改写。 */
        uint32_t next=*v&~0x01000000U;
        if (next==(*reg&~0x01000000U)) { return true; }
        *reg=next; *deadline=0;
        /* 原0x5023d4先置bit28，再由0xb3d49e置bit27并轮询bit24。 */
        if ((next&0x18000000)==0x18000000 && cp_pll_known(channel,next) && s->pll0_reference_present) {
            *deadline=s->pll0_now+CP_PLL0_DELAY_NS;
        }
        return true;
    }
    if (off==0x150 || off==0x158) {
        uint32_t *reg=&s->pll_div[(off-0x150)/8];
        /* 原0xb3d304/0xb3d3c2只写bit1..10；仅保存该控制，不合成频率。 */
        if (write) { if (*v&~0x7feU) { return false; } *reg=*v; }
        else { *v=*reg; }
        return true;
    }
    uint32_t *reg, mask;
    unsigned op=off&0xf;
    bool posted_read=false;
    if (off>=0xf48 && off<=0xf50) {
        /* 原 bcabb4 / bcac2e 的控制与 SET/CLR 别名。
         * 只保持写入的请求位；没有转换引擎，不自动清 bit8 或合成完成。 */
        reg=&s->dfs_control; mask=0x101; op=off-0xf48;
    } else if ((off&~0xfU)==0x50) {
        reg=&s->i2c_clock; mask=0x1fU<<18;
    } else if ((off&~0xfU)==0x350) {
        reg=&s->i2c_reset; mask=0x1fU<<24;
    } else if ((off&~0xfU)==0x70) {
        /* 原PLL切换例程的门控，未知位拒绝，未实现实际时钟分配。 */
        reg=&s->logic_clock; mask=0x400160; posted_read=true;
    } else if ((off&~0xfU)==0) {
        reg=&s->media_clock; mask=0x100; posted_read=true;
    } else if (off>=0x200 && off<0x250) {
        /* 公开 CLKSEL_PLL/UART/MEDIA/SPI/DDR 控制银行；别名读只作写入排空。
         * 只保持软件选择，不能把值当作 PLL 锁定、实际频率或设备就绪。 */
        reg=&s->clksel[(off-0x200)/16]; mask=UINT32_MAX; posted_read=true;
    } else { return false; }
    if (op!=0 && op!=4 && op!=8) { return false; }
    if (!write) {
        if (op && !posted_read) { return false; }
        *v=*reg;
    } else {
        if (*v&~mask) { return false; }
        if (!op) { *reg=*v; }
        else if (op==4) { *reg|=*v; }
        else { *reg&=~*v; }
    }
    return true;
}

static inline bool cp_scu_i2c_enabled(const CPSCU *s, unsigned n)
{
    return n<5 && (s->i2c_clock&(1U<<(18+n))) && !(s->i2c_reset&(1U<<(24+n)));
}

static inline bool cp_gpio_access(CPGPIO *s, uint32_t off, bool write, uint32_t *v)
{
    uint32_t *reg;
    unsigned base = off & ~0xfU, op = off & 0xf;
    if (off & 3 || (op != 0 && op != 4 && op != 8)) {
        return false;
    }
    switch (base) {
    case 0: reg = &s->dir; break;
    case 0x10:
        if (write || op) { return false; }
        *v = (s->output & s->dir) | (s->input & ~s->dir);
        return true;
    case 0x20: reg = &s->inen; break;
    case 0x30: reg = &s->func; break;
    case 0x40: reg = &s->output; break;
    default: return false;
    }
    if (!write) {
        if (op) { return false; }
        *v = *reg;
    } else if (!op) {
        *reg = *v;
    } else if (op == 4) {
        *reg |= *v;
    } else {
        *reg &= ~*v;
    }
    return true;
}
#endif
