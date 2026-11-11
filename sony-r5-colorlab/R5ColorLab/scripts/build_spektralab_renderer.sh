#!/bin/bash
# 编译 SpektraLab 的宿主引擎和独立渲染器，Metal 资源在运行时指定。
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
source_dir=$(cd -- "${1:-$script_dir/../../../../SpektraLab}" && pwd)
engine="$source_dir/engine"
build="$engine/build/colorlab"
mkdir -p "$build"
objects=$(mktemp -d "$build/objects.XXXXXX")
export engine objects
find "$engine/src/core" "$engine/src/gpu" "$engine/src/pipeline" -maxdepth 1 -name '*.cpp' -print0 |
    xargs -0 -P 6 -I % bash -c '
        unit=$1
        clang++ -std=c++20 -O2 -mmacos-version-min=15.0 \
            -I"$engine/include" -I"$engine/src" -I"$engine/src/core" -I"$engine/third_party/metal-cpp" \
            -c "$unit" -o "$objects/$(basename "$unit" .cpp).o"
    ' _ %
clang++ -dynamiclib -install_name @rpath/libspektralab_engine.dylib "$objects/"*.o \
    -framework Metal -framework Foundation -framework QuartzCore -framework CoreText \
    -framework CoreGraphics -framework Accelerate -o "$objects/libspektralab_engine.dylib"
xcrun swiftc -O -import-objc-header "$engine/include/spektralab/spk_engine.h" \
    -L "$objects" -lspektralab_engine -Xlinker -rpath -Xlinker @executable_path \
    "$script_dir/spektralab_render_raw.swift" -o "$objects/spektralab-render-raw"
git -C "$source_dir" rev-parse HEAD > "$objects/SOURCE-COMMIT"
for file in libspektralab_engine.dylib spektralab-render-raw SOURCE-COMMIT; do
    mv "$objects/$file" "$build/$file"
done
find "$objects" -type f -name '*.o' -delete
rmdir "$objects"
printf '%s\n' "$build/spektralab-render-raw"
