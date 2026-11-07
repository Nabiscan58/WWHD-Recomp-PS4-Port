#!/usr/bin/env bash
# Maintainers (Linux or WSL Ubuntu): builds the PS4 runtime of the Wind Waker HD port, the "sdk" the Windows Maker
# links the player's recompiled game code against. No game code: the game functions are placeholders here
# (upstream's tools/recomp/stubgen.py), the Maker compiles the real ones on the player's PC.
#
#   scripts/build-sdk.sh [work dir]          (default: ~/wwhd-ps4-build)
#
# Downloads (pinned, SHA-256 checked where the upstream publishes a fixed file): LLVM 21.1.8, the OpenOrbis PS4
# toolchain v0.5.2, SMW's sdk-1 (libc++ 21 sysroot with the libc overlay, RADV for the PS4 GPU), Wind Waker HD Recomp
# at patches/BASE.txt, SDL 3.4.18, glslang 16.0.0, LZ4 1.10.0, Vulkan-Headers 1.4.357.
# Result: <work>/out/wwhd-ps4-sdk-<version>.tar.xz (and <work>/sdk, what the archive holds) and a test eboot
# (<work>/build/wwhd/wwhd_eboot/eboot.bin) that starts but refuses to run (no game code in it).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="$(mkdir -p "${1:-$HOME/wwhd-ps4-build}" && cd "${1:-$HOME/wwhd-ps4-build}" && pwd)"
JOBS="${JOBS:-$(nproc)}"
VERSION="$(cat "$HERE/VERSION")"
BASE="$(cat "$HERE/patches/BASE.txt")"
DL="$W/downloads"
mkdir -p "$DL" "$W/src" "$W/build"

fetch() {  # url file sha256
    local url="$1" out="$DL/$2" sum="$3"
    if [ ! -f "$out" ] || ! echo "$sum  $out" | sha256sum -c --status; then
        echo "downloading $2"
        curl -fsSL --retry 3 -o "$out.part" "$url"
        mv "$out.part" "$out"
    fi
    echo "$sum  $out" | sha256sum -c --status || { echo "checksum mismatch: $out" >&2; exit 1; }
}
gitat() {  # url ref dir
    [ -d "$3/.git" ] || git clone -q "$1" "$3"
    git -C "$3" fetch -q --depth 1 origin "$2" 2>/dev/null || git -C "$3" fetch -q origin
    git -C "$3" checkout -q -f "$2" 2>/dev/null || git -C "$3" checkout -q -f FETCH_HEAD
}

# ---- toolchains -------------------------------------------------------------------------------------------------
fetch https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/LLVM-21.1.8-Linux-X64.tar.xz \
      llvm-21.1.8-linux.tar.xz "${LLVM_SHA256:-$(cat "$HERE/scripts/pins/llvm-21.1.8-linux.sha256")}"
if [ ! -x "$W/llvm/bin/clang" ]; then
    mkdir -p "$W/llvm"
    tar -xJf "$DL/llvm-21.1.8-linux.tar.xz" -C "$W/llvm" --strip-components=1 \
        --wildcards '*/bin/clang' '*/bin/clang-21' '*/bin/clang++' '*/bin/lld' '*/bin/ld.lld' '*/bin/llvm-ar' \
        '*/bin/llvm-nm' '*/bin/llvm-ranlib' '*/bin/llvm-readelf' '*/bin/llvm-readobj' '*/bin/llvm-objcopy' \
        '*/bin/llvm-symbolizer' '*/lib/clang/*'
fi
fetch https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain/releases/download/v0.5.2/v0.5.2.tar.gz \
      openorbis-v0.5.2.tar.gz "$(cat "$HERE/scripts/pins/openorbis-v0.5.2.sha256")"
[ -d "$W/openorbis" ] || { mkdir -p "$W/oo" && tar -xzf "$DL/openorbis-v0.5.2.tar.gz" -C "$W/oo" &&
                           mv "$W/oo/OpenOrbis/PS4Toolchain" "$W/openorbis" && rm -rf "$W/oo"; }
fetch https://github.com/iHaiDeeZ/SMW/releases/download/sdk-1/SMW-PS4-SDK-1.tar.xz smw-ps4-sdk-1.tar.xz \
      15e7927cb01fa877c04ef59beca33907cb7fe3d39b035e3e296661c3a0f2e026
[ -d "$W/smw-ps4-sdk" ] || tar -xJf "$DL/smw-ps4-sdk-1.tar.xz" -C "$W"
python3 "$HERE/scripts/patch-radv-paths.py" "$W/smw-ps4-sdk/build/mesa"

export PS4_LLVM="$W/llvm/bin" OPENORBIS="$W/openorbis" PS4_SYSROOT="$W/smw-ps4-sdk/sysroot" PS4_PREFIX="$W/prefix"
export OO_PS4_TOOLCHAIN="$OPENORBIS"
TC="$HERE/toolchain/ps4.cmake"
MESA="$W/smw-ps4-sdk/build/mesa"
ps4_cmake() { cmake -G Ninja -DCMAKE_TOOLCHAIN_FILE="$TC" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PS4_PREFIX" "$@"; }

# ---- sources ----------------------------------------------------------------------------------------------------
gitat https://github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp "$BASE" "$W/src/wwhd"
git -C "$W/src/wwhd" apply --check "$HERE/patches/wwhd-ps4.patch" 2>/dev/null &&
    git -C "$W/src/wwhd" apply "$HERE/patches/wwhd-ps4.patch" || echo "(wwhd-ps4.patch already applied)"
fetch https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-3.4.18.tar.gz SDL3-3.4.18.tar.gz \
      9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3
if [ ! -d "$W/src/SDL3-3.4.18" ]; then
    tar -xzf "$DL/SDL3-3.4.18.tar.gz" -C "$W/src"
    patch -d "$W/src/SDL3-3.4.18" -p1 < "$HERE/patches/sdl3-3.4.18-ps4.patch"
fi
gitat https://github.com/KhronosGroup/glslang 16.0.0 "$W/src/glslang"
gitat https://github.com/lz4/lz4 v1.10.0 "$W/src/lz4"
gitat https://github.com/KhronosGroup/Vulkan-Headers v1.4.357 "$W/src/Vulkan-Headers"

# ---- libraries --------------------------------------------------------------------------------------------------
ps4_cmake -S "$W/src/SDL3-3.4.18" -B "$W/build/sdl3" \
    -DSDL_SHARED=OFF -DSDL_STATIC=ON -DSDL_TEST_LIBRARY=OFF -DSDL_TESTS=OFF -DSDL_EXAMPLES=OFF \
    -DSDL_UNIX_CONSOLE_BUILD=ON -DSDL_X11=OFF -DSDL_WAYLAND=OFF -DSDL_KMSDRM=OFF -DSDL_OFFSCREEN=OFF \
    -DSDL_DUMMYVIDEO=OFF -DSDL_AUDIO=ON -DSDL_JOYSTICK=ON -DSDL_HAPTIC=OFF -DSDL_SENSOR=ON -DSDL_HIDAPI=OFF \
    -DSDL_VIRTUAL_JOYSTICK=ON -DSDL_DUMMYAUDIO=OFF -DSDL_DISKAUDIO=OFF -DSDL_CAMERA=OFF -DSDL_DIALOG=OFF \
    -DSDL_TRAY=OFF -DSDL_GPU=OFF -DSDL_RENDER=ON -DSDL_RENDER_GPU=OFF -DSDL_RENDER_VULKAN=OFF -DSDL_VULKAN=OFF \
    -DSDL_OPENGL=OFF -DSDL_OPENGLES=OFF -DSDL_PULSEAUDIO=OFF -DSDL_ALSA=OFF -DSDL_JACK=OFF -DSDL_PIPEWIRE=OFF \
    -DSDL_SNDIO=OFF -DSDL_OSS=OFF -DSDL_LIBUDEV=OFF -DSDL_DBUS=OFF -DSDL_IBUS=OFF -DSDL_LIBURING=OFF \
    -DSDL_DLOPEN_NOTES=OFF -DLIBC_HAS_WCSNLEN=OFF -DLIBC_HAS_WCSLCPY=OFF -DLIBC_HAS_WCSLCAT=OFF
cmake --build "$W/build/sdl3" -j "$JOBS" && cmake --install "$W/build/sdl3" > /dev/null
ps4_cmake -S "$W/src/lz4/build/cmake" -B "$W/build/lz4" -DBUILD_SHARED_LIBS=OFF -DBUILD_STATIC_LIBS=ON \
    -DLZ4_BUILD_CLI=OFF -DLZ4_BUILD_LEGACY_LZ4C=OFF
cmake --build "$W/build/lz4" -j "$JOBS" --target lz4_static
mkdir -p "$PS4_PREFIX/lib" "$PS4_PREFIX/include"
cp "$W/build/lz4/liblz4.a" "$PS4_PREFIX/lib/"
cp "$W/src/lz4/lib/lz4.h" "$W/src/lz4/lib/lz4hc.h" "$W/src/lz4/lib/lz4frame.h" "$PS4_PREFIX/include/"
ps4_cmake -S "$W/src/glslang" -B "$W/build/glslang" -DBUILD_SHARED_LIBS=OFF -DENABLE_OPT=OFF -DGLSLANG_TESTS=OFF \
    -DENABLE_GLSLANG_BINARIES=OFF -DGLSLANG_ENABLE_INSTALL=ON -DENABLE_HLSL=OFF -DENABLE_SPIRV=ON
cmake --build "$W/build/glslang" -j "$JOBS" && cmake --install "$W/build/glslang" > /dev/null

# ---- the runtime, linked once with placeholder game code (a link check and the Maker's link recipe) ------------
python3 "$W/src/wwhd/tools/recomp/stubgen.py" "$W/build/stubgen" > /dev/null
ps4_cmake -S "$W/src/wwhd" -B "$W/build/wwhd" -DWWHD_PS4_DIR="$HERE" -DPS4_MESA_BUILD="$MESA" \
    -DGEN_DIR="$W/build/stubgen" -DWWHD_VERSION="v0.5.0-ps4-$VERSION" \
    -DVulkan_INCLUDE_DIR="$W/src/Vulkan-Headers/include" -DVulkan_LIBRARY="$MESA/src/amd/vulkan/libvulkan_radeon.a" \
    -DLZ4_INCLUDE_DIR="$PS4_PREFIX/include" -DLZ4_LIBRARY="$PS4_PREFIX/lib/liblz4.a" \
    -DZLIB_INCLUDE_DIR="$PS4_SYSROOT/include" -DZLIB_LIBRARY="$PS4_SYSROOT/lib/libz.a"
cmake --build "$W/build/wwhd" -j "$JOBS" --target wwhd_eboot

# ---- the Maker's sdk: runtime archives, link recipe, game code headers and flags --------------------------------
python3 "$HERE/scripts/make-sdk.py" --build "$W/build/wwhd" --wwhd "$W/src/wwhd" --port "$HERE" \
    --openorbis "$OPENORBIS" --sysroot "$PS4_SYSROOT" --mesa "$MESA" --version "$VERSION" --out "$W/sdk"
mkdir -p "$W/out"
tar -C "$W" -cf - sdk | xz -T0 -9 > "$W/out/wwhd-ps4-sdk-$VERSION.tar.xz"
sha256sum "$W/out/wwhd-ps4-sdk-$VERSION.tar.xz"
