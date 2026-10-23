"""在 Mac 离线构建 A7R5 载荷与待批准材料，不安装依赖、不枚举设备。"""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

from .core import validate_run
from .environment import FW, ROOT, PMCA, static_payload_check
from .restricted import layout128, save_json
from .tasks import scripts

SOURCE = Path(__file__).with_name("payload") / "a7r5_worker.c"
CLANG = Path("/usr/bin/clang")
LINKER = Path.home() / ".rustup/toolchains/1.95-aarch64-apple-darwin/lib/rustlib/aarch64-apple-darwin/bin/gcc-ld/ld.lld"
LIBC = FW / "nflasha7_unpacked/lib/libc-2.25.so"


def config(run_id, card_uuid, card_bytes, marker, *, root="/tmp/jiritsu", preload="/etc/ld.so.preload",
           gate="/proc/self/cmdline", test_prelude="", test_card=None, wait_polls=3000, dump_seconds=7200,
           expected_card=None, views='both'):
    validate_run(run_id)
    ident = uuid.UUID(card_uuid)
    prepare, dump = scripts(run_id, marker, root=root, test_prelude=test_prelude, views=views)
    prefix = f"{root}/a7r5-{run_id}"
    values = {"RUN_ID": run_id, "STATE_PATH": prefix+".state", "GO_PATH": prefix+".go",
              "GO_BYTES": f"A7R5_GO {run_id} {marker}\n", "ARM_BYTES": prefix+".so\n",
              "ABORT_BYTES": f"A7R5_ABORT {run_id} {marker}\n",
              "PRELOAD_PATH": preload, "GATE_PATH": gate, "PREPARE_SCRIPT": prepare,
              "DUMP_SCRIPT": dump, "CARD_MARKER": marker+"\n", "PARTS_SOURCE": "/proc/partitions",
              "SOURCE_ROOT": "/dev", "SOURCES_PATH": prefix+".sources", "MOUNT_PATH": prefix+".sd"}
    values["CLEANUP_SCRIPT"] = (
        'set -eu\n' + test_prelude + f'cd /\ncard=$1\n'
        f'found=0\nwhile read -r src target fs rest; do\n'
        f' if [ "$target" = "{prefix}.sd" ]; then\n'
        f'  [ "$src" = "$card" ] && [ "$fs" = ext2 ] || exit 95\n  found=$((found+1))\n fi\n'
        f'done < /proc/mounts\n[ "$found" != 0 ] || exit 0\n[ "$found" = 1 ] || exit 95\numount {prefix}.sd\n')
    if test_card:
        values.update(TEST_CARD_PATH=str(test_card), TEST_CARD_DEVICE="/dev/mmca2")
    if expected_card is not None:
        from .core import CARD_PARTITION
        if not expected_card.startswith('/dev/') or not CARD_PARTITION.fullmatch(expected_card[5:]):
            raise ValueError('绑定的卡路径不在有限白名单内')
        values['EXPECTED_CARD_DEVICE'] = expected_card
    result = "/* 本次构建的固定材料；不可在运行中替换任务。 */\n"
    result += "\n".join("#define " + k + " " + json.dumps(v, ensure_ascii=True) for k, v in values.items())
    result += '\n#define CARD_UUID "' + "".join(f"\\x{b:02x}" for b in ident.bytes) + '"\n'
    result += f"#define CARD_BYTES {card_bytes}ULL\n#define WAIT_POLLS {wait_polls}U\n#define DUMP_SECONDS {dump_seconds}U\n"
    result += f"#define DUMP_PLAINTEXT_ONLY {1 if views == 'plaintext' else 0}\n"
    return result, prepare, dump


def prepare_bundle(output, capacity_bytes, run_id=None, *, prepared_card=None, expected_card=None, views='both'):
    run_id = validate_run(run_id or uuid.uuid4().hex)
    layout = layout128(capacity_bytes)
    output = Path(output).absolute()
    if output.resolve().is_relative_to("/dev"): raise ValueError("构建输出不能是设备目录")
    output.mkdir(parents=True, exist_ok=False)
    if prepared_card is None:
        card_uuid, marker = str(uuid.uuid4()), uuid.uuid4().hex
    else:
        if prepared_card['capacity_bytes'] != capacity_bytes:
            raise ValueError('卡收据与构建容量不符')
        card_uuid, marker = prepared_card['ext2_uuid'], prepared_card['card_marker']
    card_bytes = layout["partitions"][1]["bytes"]
    header, prepare, dump = config(run_id, card_uuid, card_bytes, marker, expected_card=expected_card, views=views)
    for name, data in (("config.h", header), ("prepare-task.sh", prepare), ("dump-task.sh", dump),
                       ("A7R5_CARD_ID", marker+"\n")):
        (output/name).write_text(data)
    cleanup = next(json.loads(line.split(' ',2)[2]) for line in header.splitlines() if line.startswith('#define CLEANUP_SCRIPT '))
    (output/'cleanup-task.sh').write_text(cleanup)
    prefix=f'/tmp/jiritsu/a7r5-{run_id}'
    for name,data in (('preload-arm.bin',(prefix+'.so\n').encode()), ('preload-neutral.bin',b'\n'*512),
                      ('go-token.bin',f'A7R5_GO {run_id} {marker}\n'.encode()),
                      ('abort-token.bin',f'A7R5_ABORT {run_id} {marker}\n'.encode())):
        (output/name).write_bytes(data)
    from .card import mbr_bytes
    (output/"candidate-mbr.bin").write_bytes(mbr_bytes(layout, card_uuid))
    payload = output / "a7r5_worker.arm64.so"
    commands = [[str(CLANG), "--target=aarch64-linux-gnu", "-ffreestanding", "-fPIC", "-fno-builtin",
                 "-fno-stack-protector", "-fvisibility=hidden", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-I", str(output), "-c", str(SOURCE), "-o", str(output/"worker.o")],
                [str(LINKER), "-shared", "-z", "now", "-z", "max-page-size=65536", "--no-undefined",
                 "--build-id=sha1", str(output/"worker.o"), str(LIBC), "-o", str(payload)]]
    results = []
    for command in commands:
        process = subprocess.run(command, capture_output=True, text=True, timeout=90)
        results.append({"argv": command, "exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        save_json(output/"build-log.json", results)
        if process.returncode: raise RuntimeError("交叉构建失败；参见 build-log.json")
    payload_sha = hashlib.sha256(payload.read_bytes()).hexdigest()
    checked = static_payload_check(payload, payload_sha)
    sources = [SOURCE, ROOT/"mac/a7r5_dump.py", *sorted(Path(__file__).parent.glob("*.py")),
               *[PMCA/"pmca/usb"/n for n in ("sony.py", "constants.py", "crypto.py")]]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}
    manifest = {"schema": "a7r5-dump-bundle-1", "run_id": run_id, "card_uuid": card_uuid, "dump_views": views,
                "card_marker": marker, "card_partition_bytes": card_bytes, "layout": layout,
                "capacity_source": "nominal_candidate_only", "card_geometry_verified": False,
                "payload": checked, "sources": source_hashes, "artifacts": artifacts,
                "tools": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (CLANG, LINKER, LIBC)},
                "camera_execution_verified": False, "execution_enabled": False,
                "pending": ["实际卡及布局核对", "相机写入、未知预加载覆盖、一次 DEBUG 和残留恢复风险的明确批准"]}
    save_json(output/"bundle.json", manifest)
    save_json(output/"approval-template.json", {
        "schema": "a7r5-dump-approval-1", "bundle_sha256": hashlib.sha256((output/"bundle.json").read_bytes()).hexdigest(),
        "camera_writes": False, "debug_once": False, "unknown_preload_overwrite": False,
        "neutral_file_residue": False, "card_dump_writes": False, "failure_recovery_limits": False,
        "card_verified_uuid": None, "card_verified_partition_bytes": None, "card_verified_capacity_bytes": None})
    return manifest


def load_bundle(path):
    from .images import regular_file
    path = Path(path).absolute()
    raw = regular_file(path/"bundle.json").read_bytes()
    value = json.loads(raw)
    if value.get("schema") != "a7r5-dump-bundle-1": raise ValueError("候选材料版本不符")
    validate_run(value["run_id"])
    if value.get('dump_views') not in ('both', 'plaintext'):
        raise ValueError('缺少明确的转存视图；拒绝旧版或未知范围材料')
    uuid.UUID(value["card_uuid"])
    from .tasks import scripts
    scripts(value["run_id"], value["card_marker"], views=value['dump_views'])
    expected_layout = layout128(value["layout"]["capacity_bytes"])
    if value["layout"] != expected_layout or value["card_partition_bytes"] != expected_layout["partitions"][1]["bytes"]:
        raise ValueError("候选卡几何不一致")
    required = {"a7r5_worker.arm64.so", "config.h", "prepare-task.sh", "dump-task.sh", "A7R5_CARD_ID", "candidate-mbr.bin"}
    if not required.issubset(value["artifacts"]): raise ValueError("缺少关键材料摘要")
    needed_sources = {str(p.relative_to(ROOT)) for p in Path(__file__).parent.glob("*.py")} | {str(SOURCE.relative_to(ROOT))}
    if not needed_sources.issubset(value["sources"]): raise ValueError("缺少实现源码摘要")
    for name, expected in value["artifacts"].items():
        if Path(name).name != name: raise ValueError("材料名称不安全")
        if hashlib.sha256(regular_file(path/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"本次材料已变化：{name}")
    for name, expected in value["sources"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts: raise ValueError("源码路径越界")
        source = regular_file(ROOT/name)
        if not source.resolve().is_relative_to(ROOT): raise ValueError("源码路径越界")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected: raise ValueError(f"实现已变化，须重新准备：{name}")
    static_payload_check(path/"a7r5_worker.arm64.so", value["payload"]["sha256"])
    return value, hashlib.sha256(raw).hexdigest()
