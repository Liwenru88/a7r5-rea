/*
 * 原厂 CP 启动的隔离实验板：四核、低地址 RAM 和标准 GICv2。
 * 不冒充真实 Sony SoC；只建模已核对的寄存器/本地 DMA 子集，没有 ISP。
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qemu/units.h"
#include "qapi/error.h"
#include "hw/core/boards.h"
#include "hw/core/cpu.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/arm/machines-qom.h"
#include "system/address-spaces.h"
#include "system/system.h"
#include "hw/char/pl011.h"
#include "target/arm/cpu.h"
#include "hw/core/irq.h"
#include "qemu/log.h"
#include "qemu/timer.h"
#include "a7r5-cp-edma.h"
#include "hw/i2c/designware_i2c.h"

typedef struct CPPCIeState {
    CPEDMA dma;
    MemoryRegion regs, side, gpio_notify;
    CPGPIO gpio[2];
    CPSCU scu;
    MemoryRegion scu_regs;
    DeviceState *i2c[5];
    qemu_irq irq;
    uint64_t ram_size;
    unsigned logs;
} CPPCIeState;

static bool cp_pcie_copy(void *opaque, uint64_t src, uint64_t dst, uint32_t len)
{
    CPPCIeState *s = opaque;
    /* AP 尚未接入，只有 CP 本地物理 RAM 可搬运；拒绝 MMIO 和高地址别名。 */
    if (src > s->ram_size || dst > s->ram_size ||
        len > s->ram_size - src || len > s->ram_size - dst) {
        return false;
    }
    uint8_t *buf = g_try_malloc(len);
    if (!buf) {
        return false;
    }
    MemTxResult rc = address_space_read(&address_space_memory, src,
                                        MEMTXATTRS_UNSPECIFIED, buf, len);
    if (rc == MEMTX_OK) {
        rc = address_space_write(&address_space_memory, dst,
                                 MEMTXATTRS_UNSPECIFIED, buf, len);
    }
    g_free(buf);
    return rc == MEMTX_OK;
}

static bool cp_pcie_read(void *opaque, uint64_t src, void *buf, uint32_t len)
{
    CPPCIeState *s = opaque;
    if (src > s->ram_size || len > s->ram_size - src) { return false; }
    return address_space_read(&address_space_memory, src, MEMTXATTRS_UNSPECIFIED,
                              buf, len) == MEMTX_OK;
}

static MemTxResult cp_pcie_access(CPPCIeState *s, hwaddr addr,
                                 uint64_t *value, unsigned size,
                                 bool write, bool side)
{
    uint32_t v = *value;
    bool ok = size == 4 && !(addr & 3) &&
        (side ? cp_edma_side_access(&s->dma, 0x20274 + addr, write, &v) :
                cp_edma_access(&s->dma, addr, write, &v));
    if (s->logs++ < 4096) {
        qemu_log_mask(LOG_GUEST_ERROR,
            "CP_PCIE %s %s off=0x%" HWADDR_PRIx " value=0x%08x ok=%u copies=%" PRIu64 " aborts=%" PRIu64 "\n",
            side ? "side" : "edma", write ? "write" : "read", addr,
            v, ok, s->dma.copies, s->dma.aborts);
    }
    if (!ok) {
        return MEMTX_DECODE_ERROR;
    }
    *value = v;
    qemu_set_irq(s->irq, cp_edma_irq(&s->dma));
    return MEMTX_OK;
}

static MemTxResult cp_edma_read(void *opaque, hwaddr addr, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    *value = 0;
    return cp_pcie_access(opaque, addr, value, size, false, false);
}

static MemTxResult cp_edma_write(void *opaque, hwaddr addr, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    return cp_pcie_access(opaque, addr, &value, size, true, false);
}

static MemTxResult cp_side_read(void *opaque, hwaddr addr, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    *value = 0;
    return cp_pcie_access(opaque, addr, value, size, false, true);
}

static MemTxResult cp_side_write(void *opaque, hwaddr addr, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    return cp_pcie_access(opaque, addr, &value, size, true, true);
}

static const MemoryRegionOps cp_edma_ops = {
    .read_with_attrs = cp_edma_read, .write_with_attrs = cp_edma_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};
static const MemoryRegionOps cp_side_ops = {
    .read_with_attrs = cp_side_read, .write_with_attrs = cp_side_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static MemTxResult cp_gpio_read(void *opaque, hwaddr addr, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    CPPCIeState *s = opaque;
    uint32_t v = 0;
    bool ok = size == 4 && cp_gpio_access(&s->gpio[addr >> 12], addr & 0xfff, false, &v);
    *value = v;
    return ok ? MEMTX_OK : MEMTX_DECODE_ERROR;
}

static MemTxResult cp_gpio_write(void *opaque, hwaddr addr, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    CPPCIeState *s = opaque;
    uint32_t v = value;
    bool ok = size == 4 && cp_gpio_access(&s->gpio[addr >> 12], addr & 0xfff, true, &v);
    if (s->logs++ < 4096) {
        qemu_log_mask(LOG_GUEST_ERROR, "CP_GPIO%u write off=0x%" HWADDR_PRIx
                      " value=0x%08x ok=%u AP_peer_connected=0\n", 17 + (unsigned)(addr >> 12), addr & 0xfff, v, ok);
    }
    return ok ? MEMTX_OK : MEMTX_DECODE_ERROR;
}

static const MemoryRegionOps cp_gpio_ops = {
    .read_with_attrs = cp_gpio_read, .write_with_attrs = cp_gpio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static MemTxResult cp_scu_read(void *opaque, hwaddr addr, uint64_t *value,
                             unsigned size, MemTxAttrs attrs)
{
    CPPCIeState *s=opaque;
    uint32_t v=0;
    cp_pll0_advance(&s->scu,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    bool ok=size==4 && cp_scu_access(&s->scu,addr,false,&v);
    if (addr==0x100 && s->logs++<4096) {
        qemu_log_mask(LOG_GUEST_ERROR,"CP_PLL0 read value=0x%08x ok=%u time=%" PRIu64 "\n",
                      v,ok,s->scu.pll0_now);
    }
    *value=v;
    return ok?MEMTX_OK:MEMTX_DECODE_ERROR;
}

static MemTxResult cp_scu_write(void *opaque, hwaddr addr, uint64_t value,
                              unsigned size, MemTxAttrs attrs)
{
    CPPCIeState *s=opaque;
    uint32_t v=value, old_reset=s->scu.i2c_reset;
    cp_pll0_advance(&s->scu,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    bool ok=size==4 && cp_scu_access(&s->scu,addr,true,&v);
    if (!ok) { return MEMTX_DECODE_ERROR; }
    for (unsigned n=0;n<5;n++) {
        if ((old_reset^s->scu.i2c_reset)&(1U<<(24+n))) {
            device_cold_reset(s->i2c[n]);
        }
        memory_region_set_enabled(sysbus_mmio_get_region(SYS_BUS_DEVICE(s->i2c[n]),0),
                                  cp_scu_i2c_enabled(&s->scu,n));
    }
    if (s->logs++<4096) {
        qemu_log_mask(LOG_GUEST_ERROR,"CP_SCU write off=0x%" HWADDR_PRIx
                      " value=0x%08x clock=0x%08x reset=0x%08x\n",
                      addr,v,s->scu.i2c_clock,s->scu.i2c_reset);
    }
    return MEMTX_OK;
}

static const MemoryRegionOps cp_scu_ops = {
    .read_with_attrs=cp_scu_read, .write_with_attrs=cp_scu_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={ .min_access_size=4, .max_access_size=4 },
};

static void a7r5_cp_boot_init(MachineState *machine)
{
    DeviceState *cpus[4];
    memory_region_add_subregion(get_system_memory(), 0, machine->ram);
    /* 原 TOMCO memcfg=0x17000000@0x09000000:uc，包含 OSAL 消息日志。
     * 这是有原厂配置来源的独立 RAM，不能拿它覆盖未知 MMIO。 */
    MemoryRegion *work_ram = g_new0(MemoryRegion, 1);
    memory_region_init_ram(work_ram, NULL, "cp.tomco.work-ram",
                           0x17000000, &error_fatal);
    memory_region_add_subregion(get_system_memory(), 0x09000000, work_ram);
    for (unsigned n = 0; n < 4; n++) {
        Object *object = object_new(machine->cpu_type);
        object_property_set_bool(object, "aarch64", false, &error_fatal);
        object_property_set_bool(object, "has_el2", false, &error_fatal);
        object_property_set_bool(object, "has_el3", false, &error_fatal);
        object_property_set_int(object, "mp-affinity", n, &error_fatal);
        qdev_realize(DEVICE(object), NULL, &error_fatal);
        cpus[n] = DEVICE(object);
    }
    /* 原厂 ARM_GICD 配置上限 0x1d2，TOMCO 用到 IRQ 296/307。
     * GIC 按 32 个中断取整为 480；仍不冒称整个实机中断拓扑已还原。 */
    DeviceState *gic = qdev_new("arm_gic");
    qdev_prop_set_uint32(gic, "num-cpu", 4);
    qdev_prop_set_uint32(gic, "num-irq", 480);
    qdev_prop_set_uint32(gic, "revision", 2);
    qdev_prop_set_bit(gic, "has-security-extensions", false);
    sysbus_realize_and_unref(SYS_BUS_DEVICE(gic), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(gic), 0, 0xf13a1000);
    sysbus_mmio_map(SYS_BUS_DEVICE(gic), 1, 0xf13a2000);
    CPPCIeState *pcie = g_new0(CPPCIeState, 1);
    pcie->ram_size = machine->ram_size;
    /* 虚拟初态明确关时钟、保持复位；不作为实机上电值。
     * 原厂会写 bit18..22 时钟和 bit24..28 复位，控制实际 MMIO 可达性。 */
    pcie->scu.i2c_reset=0x1fU<<24;
    /* 实验板显式提供虚拟参考时钟；PLL0初值未配置，不能读即锁定。 */
    pcie->scu.pll0_reference_present=true;
    for (unsigned n=0;n<5;n++) {
        DeviceState *i2c=qdev_new(TYPE_DESIGNWARE_I2C);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(i2c),&error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(i2c),0,0xf1012000+n*0x1000);
        sysbus_connect_irq(SYS_BUS_DEVICE(i2c),0,qdev_get_gpio_in(gic,429+n-32));
        memory_region_set_enabled(sysbus_mmio_get_region(SYS_BUS_DEVICE(i2c),0),false);
        pcie->i2c[n]=i2c;
    }
    memory_region_init_io(&pcie->scu_regs,OBJECT(machine),&cp_scu_ops,
                          pcie,"cp-clock-reset-control-subset",0xf54);
    memory_region_add_subregion(get_system_memory(),0xf1388000,&pcie->scu_regs);
    /* 原厂 PCIDMA_INIT 参数中的 GIC INTID=403；QEMU 外部输入从 INTID32 开始。 */
    pcie->irq = qdev_get_gpio_in(gic, 403 - 32);
    cp_edma_init(&pcie->dma, cp_pcie_copy, cp_pcie_read, pcie);
    memory_region_init_io(&pcie->regs, OBJECT(machine), &cp_edma_ops,
                          pcie, "cp-edma-subset", 0x2000);
    memory_region_add_subregion(get_system_memory(), 0xf6780000, &pcie->regs);
    /* 只映射已证实的一个 RW 使能寄存器，未知 PHY 寄存器仍产生异常。 */
    memory_region_init_io(&pcie->side, OBJECT(machine), &cp_side_ops,
                          pcie, "cp-pcie-interrupt-enable", 4);
    memory_region_add_subregion(get_system_memory(), 0xf11e0274, &pcie->side);
    memory_region_init_io(&pcie->gpio_notify, OBJECT(machine), &cp_gpio_ops,
                          pcie, "cp-pcie-gpio17-18", 0x2000);
    memory_region_add_subregion(get_system_memory(), 0xf102e000, &pcie->gpio_notify);
    for (unsigned n = 0; n < 4; n++) {
        sysbus_connect_irq(SYS_BUS_DEVICE(gic), n,
                           qdev_get_gpio_in(cpus[n], ARM_CPU_IRQ));
        sysbus_connect_irq(SYS_BUS_DEVICE(gic), n + 4,
                           qdev_get_gpio_in(cpus[n], ARM_CPU_FIQ));
    }
    /* 原 CP 轮询 UARTFR；仅提供标准 PL011 轮询输出，RX IRQ 尚未接线。 */
    DeviceState *uart = qdev_new(TYPE_PL011);
    qdev_prop_set_chr(uart, "chardev", serial_hd(0));
    sysbus_realize_and_unref(SYS_BUS_DEVICE(uart), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(uart), 0, 0xf1000000);
    /* 原 CP 接受通道 0..8。计数/控制语义沿用现有模型，IRQ 接线仍为实验配置。 */
    for (unsigned n = 0; n < 9; n++) {
        DeviceState *timer = qdev_new("sony-hwtimer");
        sysbus_realize_and_unref(SYS_BUS_DEVICE(timer), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(timer), 0, 0xf1042000 + n * 0x1000);
        sysbus_connect_irq(SYS_BUS_DEVICE(timer), 0, qdev_get_gpio_in(gic, 200 + n));
    }
}

static void a7r5_cp_boot_class(MachineClass *machine)
{
    machine->desc = "A7R5 CP boot research (four CPUs/local eDMA subset, no AP link/ISP)";
    machine->init = a7r5_cp_boot_init;
    machine->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-a35");
    machine->min_cpus = 4;
    machine->max_cpus = 4;
    machine->default_cpus = 4;
    machine->default_ram_size = 128 * MiB;
    machine->default_ram_id = "a7r5.cp.ram";
    machine->no_serial = true;
    machine->no_parallel = true;
    machine->no_floppy = true;
    machine->no_cdrom = true;
}

DEFINE_MACHINE_WITH_INTERFACES("a7r5-cp-boot", a7r5_cp_boot_class,
                             { TYPE_TARGET_AARCH64_MACHINE }, { })
