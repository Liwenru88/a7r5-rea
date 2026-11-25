"""A7R5 (ILCE-7RM5) 4.00 共享设备基线配置（内嵌于 scripts，不依赖 a7r5-desktop/engine/profile.json）。"""
import copy

# 与 a7r5-desktop/engine/profile.json 中 4.00 机身协议与校验常量保持一致；
# interfaces 中的 bus/ports 在运行时由实时 USB 枚举结果覆盖。
BASELINE_400_PROFILE = {
    'interfaces': {
        'interface-1.json': {
            'pid': 0x0E0A,
            'bus': 0,
            'ports': [1],
            'number': 0,
            'alternate': 0,
            'interface_class': 8,
            'subclass': 6,
            'protocol': 80,
            'endpoints': [
                {'address': 129, 'attributes': 2, 'max_packet': 512, 'interval': 0},
                {'address': 2, 'attributes': 2, 'max_packet': 512, 'interval': 0},
            ],
        },
        'interface-2.json': {
            'pid': 0x0336,
            'bus': 0,
            'ports': [1],
            'number': 0,
            'alternate': 0,
            'interface_class': 255,
            'subclass': 0,
            'protocol': 0,
            'endpoints': [
                {'address': 129, 'attributes': 2, 'max_packet': 512, 'interval': 0},
                {'address': 2, 'attributes': 2, 'max_packet': 512, 'interval': 0},
                {'address': 131, 'attributes': 2, 'max_packet': 512, 'interval': 0},
                {'address': 4, 'attributes': 2, 'max_packet': 512, 'interval': 0},
            ],
        },
    },
    'version_sha256': '34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b',
    'loader_sha256': 'ea2d9ba9dbeb56fc11ad88be7b5c30b6b237f8ccc55ce9f24c02546eb0ba07b1',
    'loader_bytes': 233416,
    'preload_baselines': [
        ['blank-512', '0a' * 512],
        [
            'installed-boot-hook',
            '2f6574632f613772352d6175746f73746172742d38653934626461663062643434653563383263383031616437346133343932392f626f6f742e736f0a',
        ],
    ],
}


def load_profile():
    """返回 4.00 共享设备基线的独立副本，避免调用方修改全局常量。"""
    return copy.deepcopy(BASELINE_400_PROFILE)
