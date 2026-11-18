"""4.28 双次构建（runtime / rebuild）组件身份与模块回执门禁检查。"""
import json
import shutil
import container_package as p


def verify_evidence(out, *, runtime, rebuild, archive):
    for folder in (runtime, rebuild):
        current = json.loads((folder / 'build.json').read_text())
        p.require(
            current['camera_io'] is False and current['installable'] is False and current['DAT_generated'] is False,
            '构建状态不符',
        )
        p.require('raw_alternatives' in current and 'lens_AF' in current, '缺少 RAW 12 项或镜头 AF 构建回执')
        p.require('factory_six' not in current, '4.28 不应包含 C1-C6')
        p.require({k: v['sha256'] for k, v in current['components'].items()} == p.COMPONENTS, '组件摘要不符')
        for name, expected in p.COMPONENTS.items():
            p.require(p.digest(folder / name) == expected, '组件文件不符：' + name)
        shutil.copyfile(folder / 'build.json', out / ('runtime-build.json' if folder == runtime else 'rebuild-build.json'))
    p.save(
        out / 'candidate-428.json',
        {
            'base': '4.27',
            'version': '4.28',
            'components': p.COMPONENTS,
            'enhancements': ['lens-af-compat', 'unified-look-lightweight-debounce'],
            'excluded': ['look-factory-six', 'photo-aspect-ratios'],
            'camera_io': False,
        },
    )
