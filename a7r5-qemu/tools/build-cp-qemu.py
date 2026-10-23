"""独立构建 CP 实验板；不修改交付模拟器、默认清单或原厂固件。"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

LAB=Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',type=Path,help='仅重建本工具创建的候选，保留旧源码、二进制和收据')
    args=parser.parse_args()
    manifest=json.loads((LAB/'source/qemu/manifest.json').read_text())
    archive=LAB/'source/qemu/vendor/qemu-11.1.2.tar.xz'
    patch=LAB/'source/qemu/qemu-sony-native.patch'
    if digest(archive)!=manifest['base_sha256'] or digest(patch)!=manifest['patch_sha256']:
        raise ValueError('QEMU 基础源码身份不符')
    board=LAB/'source/qemu/a7r5-cp-boot.c'
    extra=LAB/'source/qemu/a7r5-cp-edma.h'
    out=args.resume.absolute() if args.resume else Path(tempfile.mkdtemp(prefix='cp-qemu-',dir=LAB/'build'))
    if out.parent!=LAB/'build' or out.is_symlink() or not out.name.startswith('cp-qemu-'):
        raise ValueError('CP 构建目录越界')
    print('CP_QEMU_BUILD',out,flush=True)
    source_parent=out/'source'
    def safe(member,destination):
        if member.issym() and member.name.endswith('/EmulatorPkg/Unix/Host/X11IncludeHack') and member.linkname=='/opt/X11/include':return None
        return tarfile.data_filter(member,destination)
    source=source_parent/'qemu-11.1.2'
    if not args.resume:
        source_parent.mkdir()
        with tarfile.open(archive) as stream:stream.extractall(source_parent,filter=safe)
        subprocess.run(['patch','--batch','-p1','-d',str(source),'-i',str(patch)],check=True)
    for name,row in manifest['source_files'].items():
        if digest(source/name)!=row['after']:raise ValueError('QEMU 基础补丁不符：'+name)
    for name,want in manifest['dtc_source_files'].items():
        if digest(LAB/'source/qemu/dtc'/name)!=want:raise ValueError('DTC 源码变化')
    meson=source/'hw/arm/meson.build'
    if args.resume:
        old=json.loads((out/'receipt.json').read_text())
        if (old['source_sha256']!=digest(archive) or old['base_patch_sha256']!=digest(patch) or
                digest(meson)!=old['meson_after_sha256']):raise ValueError('旧 CP 构建收据不符')
        relative=Path(old['binary'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('旧二进制路径越界')
        old_binary=out/relative
        if old_binary.is_symlink() or digest(old_binary)!=old['binary_sha256']:raise ValueError('旧二进制身份变化')
        extra_identity=hashlib.sha256(json.dumps(old.get('model_sources',{}),sort_keys=True).encode()).hexdigest()[:12]
        history=out/('history-'+old['board_sha256'][:16]+'-'+extra_identity)
        generated=source/'hw/arm/a7r5-cp-boot.c'
        if not history.exists():
            if digest(generated)!=old['board_sha256']:raise ValueError('旧实验板源码变化')
            history.mkdir()
            shutil.copy2(generated,history/'a7r5-cp-boot.c')
            shutil.copy2(old_binary,history/'qemu-system-aarch64')
            shutil.copy2(out/'receipt.json',history/'receipt-original.json')
            for name,want in old.get('model_sources',{}).items():
                generated_extra=source/'hw/arm'/name
                if digest(generated_extra)!=want:raise ValueError('旧 DMA 模型身份变化')
                shutil.copy2(generated_extra,history/name)
        elif (digest(history/'a7r5-cp-boot.c')!=old['board_sha256'] or
                digest(history/'qemu-system-aarch64')!=old['binary_sha256'] or
                digest(generated) not in (old['board_sha256'],digest(board))):
            raise ValueError('旧实验板历史绑定变化')
        for name,want in old.get('model_sources',{}).items():
            if (digest(history/name)!=want or
                    digest(source/'hw/arm'/name) not in (want,digest(LAB/'source/qemu'/name))):
                raise ValueError('旧 DMA 历史绑定变化')
        before=old['meson_before_sha256']
    else:
        shutil.copytree(LAB/'source/qemu/dtc',source/'subprojects/dtc',dirs_exist_ok=True)
        before=digest(meson)
        with meson.open('a') as stream:
            stream.write("\narm_common_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('a7r5-cp-boot.c'))\n")
    shutil.copy2(board,source/'hw/arm/a7r5-cp-boot.c')
    shutil.copy2(extra,source/'hw/arm'/extra.name)
    support=['hw/i2c/designware_i2c.c','include/hw/i2c/designware_i2c.h']
    with tarfile.open(archive) as stream:
        support_hashes={name:hashlib.sha256(stream.extractfile('qemu-11.1.2/'+name).read()).hexdigest()
                        for name in support}
    for name,want in support_hashes.items():
        if digest(source/name)!=want:raise ValueError('上游 I2C 模型身份不符：'+name)
    addition="arm_common_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('../i2c/designware_i2c.c'))"
    if addition not in meson.read_text():
        if args.resume:shutil.copy2(meson,history/'meson-before-i2c.build')
        with meson.open('a') as stream:stream.write('\n'+addition+'\n')
    build=out/'build';build.mkdir(exist_ok=True)
    env=os.environ.copy();env.update(PIP_NO_INDEX='1',PYTHONDONTWRITEBYTECODE='1')
    configure=[str(source/'configure'),'--target-list=aarch64-softmmu',
        '--without-default-features','--enable-tcg','--enable-pixman','--enable-fdt=internal',
        '--disable-opengl','--disable-download','--disable-docs','--disable-containers',
        '--disable-werror','--disable-tools','--python='+sys.executable]
    if not args.resume:subprocess.run(configure,cwd=build,env=env,check=True)
    subprocess.run(['ninja','-j8','qemu-system-aarch64'],cwd=build,env=env,check=True)
    binary=build/'qemu-system-aarch64'
    help_result=subprocess.run([str(binary),'-machine','help'],capture_output=True,text=True,check=True)
    (out/'machines.txt').write_text(help_result.stdout)
    if 'a7r5-cp-boot' not in help_result.stdout:raise ValueError('新实验板未注册')
    immutable=out/'bin'/('qemu-system-aarch64-'+digest(binary))
    immutable.parent.mkdir(exist_ok=True)
    if immutable.exists():
        if digest(immutable)!=digest(binary):raise ValueError('不可变二进制身份冲突')
    else:shutil.copy2(binary,immutable)
    receipt={'source_sha256':digest(archive),'base_patch_sha256':digest(patch),'board_sha256':digest(board),
        'binary':str(immutable.relative_to(out)),'binary_sha256':digest(immutable),'binary_bytes':immutable.stat().st_size,
        'model_sources':{extra.name:digest(extra)},
        'vendor_support_sources':support_hashes,
        'meson_before_sha256':before,'meson_after_sha256':digest(meson),
        'configure':configure,'default_binary_changed':False,'default_manifest_changed':False,
        'peripherals_implemented':['ARM GICv2; 480 IRQ capacity covers original config 0x1d2 and TOMCO IRQ 307; topology incomplete; 0xf13a1000/0xf13a2000',
                                   'PLL0 opaque ROM-profile/request/status protocol; virtual reference and 100us latency, zero unconfigured initial state; not measured POR/frequency/analog lock',
                                   'TOMCO work RAM 0x09000000..0x1fffffff; no MMIO fallback',
                                   'I2C clock/reset SCU subset; 5 upstream DesignWare I2C controllers, IRQ429..433; no attached slaves, no ACK synthesis',
                                   'DFS control DATA/SET/CLR subset 0xf1388f48..0xf1388f50; request bits retained, no transition completion/status synthesis',
                                   'PL011 polling UART 0xf1000000; RX IRQ not wired',
                                   '9 existing sony-hwtimer models; experimental IRQ input 200+n; clock/IRQ equivalence unverified',
                                   'PCIe INTERRUPT0_ENABLE RW 0xf11e0274; only all EDMA bits enabled/disabled supported; POR unmeasured',
                                   'GPIO17/18 RW/SET/CLR at 0xf102e000/0xf102f000; input disconnected low; no peer ACK/interrupt synthesis',
                                   'eDMA unroll 0xf6780000; direct/local CB-TCB linked-list RAM copy, W1C/error/mask; IRQ403; no AP peer/MSI/PHY link; bounded descriptors, no timing equivalence'],
        'physical_hardware_identity_proven':False}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('CP_QEMU_READY',out,flush=True)


if __name__=='__main__':main()
