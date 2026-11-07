#!/usr/bin/env bash
# Maintainers (Linux / WSL): the Windows WWHD-PS4 Maker, as a zip, from a finished scripts/build-sdk.sh work folder.
#
#   maker/build-bundle.sh [work dir]          (default: ~/wwhd-ps4-build)  -> <work>/out/WWHD-PS4-Maker-<v>.zip
#
# The zip holds no game code, no game files and no keys: the Maker's GUI (compiled here with mono's C# compiler,
# C# 5 / .NET Framework 4, as maker/build-exe.cmd does with Windows' own), its Python pipeline, upstream's tools at
# patches/BASE.txt (setup's extraction and the recompiler, MPL-2.0) with wwhd-extract.exe built here with llvm-mingw,
# a Python for Windows (python-build-standalone), and the PS4 runtime (sdk/). The Maker downloads LLVM, OpenOrbis and
# SMW's sdk-1 itself on first use (maker/pins.json).
# Needs: mono-mcs (apt install mono-mcs mono-devel), curl, xz, zip, python3.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="$(cd "${1:-$HOME/wwhd-ps4-build}" && pwd)"
VERSION="$(cat "$HERE/VERSION")"
DL="$W/downloads"
B="$W/bundle/WWHD-PS4-Maker-$VERSION"
mkdir -p "$DL"
[ -f "$W/sdk/manifest.json" ] || { echo "no $W/sdk: run scripts/build-sdk.sh first" >&2; exit 1; }

fetch() {  # url file sha256
    local out="$DL/$2"
    if [ ! -f "$out" ] || ! echo "$3  $out" | sha256sum -c --status; then
        curl -fsSL --retry 3 -o "$out.part" "$1" && mv "$out.part" "$out"
    fi
    echo "$3  $out" | sha256sum -c --status || { echo "checksum mismatch: $out" >&2; exit 1; }
}

rm -rf "$B"
mkdir -p "$B/maker" "$B/wwhd" "$B/tools" "$B/licenses"

# ---- upstream's tools (setup.py: extraction, version checks; tools/recomp: the recompiler)
cp -a "$W/src/wwhd/tools" "$B/wwhd/tools"
rm -rf "$B/wwhd/tools/release" "$B/wwhd/tools/android" "$B/wwhd/tools/installer/gui"
find "$B/wwhd/tools" -name "test_*.py" -delete
find "$B/wwhd/tools" -name "__pycache__" -prune -exec rm -rf {} +
cp "$W/src/wwhd/LICENSE" "$B/wwhd/LICENSE"
cp "$W/src/wwhd/LICENSE" "$B/licenses/WindWakerHDRecomp-MPL-2.0.txt"
echo "github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp $(cat "$HERE/patches/BASE.txt") (unmodified tools/)" > "$B/wwhd/SOURCE.txt"

# ---- wwhd-extract.exe (disc images and Cemu archives), with llvm-mingw and zstd 1.5.7
fetch https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz \
      llvm-mingw-20260922-ubuntu.tar.xz "$(cat "$HERE/scripts/pins/llvm-mingw-20260922-ubuntu.sha256")"
fetch https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz zstd-1.5.7.tar.gz \
      eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3
[ -d "$W/llvm-mingw" ] || { mkdir -p "$W/llvm-mingw" && tar -xJf "$DL/llvm-mingw-20260922-ubuntu.tar.xz" -C "$W/llvm-mingw" --strip-components=1; }
[ -d "$W/src/zstd-1.5.7" ] || tar -xzf "$DL/zstd-1.5.7.tar.gz" -C "$W/src"
X="$W/build/wwhd-extract"
mkdir -p "$X" "$B/wwhd/tools/bin"
for f in "$W"/src/zstd-1.5.7/lib/common/*.c "$W"/src/zstd-1.5.7/lib/decompress/*.c; do
    "$W/llvm-mingw/bin/x86_64-w64-mingw32-clang" -O2 -w -DZSTD_DISABLE_ASM -DXXH_NAMESPACE=ZSTD_ \
        -I"$W/src/zstd-1.5.7/lib" -c "$f" -o "$X/$(basename "$f").o"
done
"$W/llvm-mingw/bin/x86_64-w64-mingw32-clang++" -O2 -std=c++17 -static -s -I"$W/src/wwhd/tools/wudextract" \
    -I"$W/src/zstd-1.5.7/lib" "$W/src/wwhd/tools/wudextract/wwhd_extract.cpp" "$W/src/wwhd/tools/wudextract/zarchive.cpp" \
    "$W/src/wwhd/tools/wudextract/crypto.cpp" "$X"/*.o -lshell32 -o "$B/wwhd/tools/bin/wwhd-extract.exe"
cp "$W/src/zstd-1.5.7/LICENSE" "$B/licenses/zstd-BSD-3-Clause.txt"

# ---- Python for Windows (python-build-standalone, the install_only build), without what the Maker never uses
fetch "https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-x86_64-pc-windows-msvc-install_only.tar.gz" \
      cpython-3.14.8-windows.tar.gz "$(cat "$HERE/scripts/pins/cpython-3.14.8-windows.sha256")"
tar -xzf "$DL/cpython-3.14.8-windows.tar.gz" -C "$B/tools"
rm -rf "$B/tools/python/Lib/test" "$B/tools/python/Lib/idlelib" "$B/tools/python/Lib/tkinter" "$B/tools/python/tcl" \
       "$B/tools/python/Lib/turtledemo" "$B/tools/python/Lib/ensurepip" "$B/tools/python/include" \
       "$B/tools/python/Lib/site-packages/pip"* "$B/tools/python/Scripts"
find "$B/tools/python" -name "__pycache__" -prune -exec rm -rf {} +

# ---- the Maker
cp "$HERE/maker/wwhd_ps4_maker.py" "$HERE/maker/pins.json" "$HERE/maker/WWHD-PS4-Maker.cs" "$HERE/maker/build-exe.cmd" \
   "$HERE/maker/wwhd-ps4-maker.ico" "$B/maker/"
cp -a "$HERE/maker/sce_sys" "$B/maker/sce_sys"
mcs -langversion:5 -target:winexe -optimize+ -sdk:4.5 -win32icon:"$HERE/maker/wwhd-ps4-maker.ico" \
    -r:System.dll -r:System.Drawing.dll -r:System.Windows.Forms.dll -out:"$B/WWHD-PS4-Maker.exe" "$HERE/maker/WWHD-PS4-Maker.cs"
cp -a "$W/sdk" "$B/sdk"
cp "$HERE/maker/LISEZ-MOI.txt" "$B/"
cp "$HERE/LICENSE" "$B/licenses/wwhd-ps4-MIT.txt"
cp "$HERE/docs/LICENSE-SMW.txt" "$B/licenses/SMW-MIT.txt"
cp "$W/src/SDL3-3.4.18/LICENSE.txt" "$B/licenses/SDL3-zlib.txt"
cp "$W/src/glslang/LICENSE.txt" "$B/licenses/glslang.txt"
cp "$W/src/lz4/LICENSE" "$B/licenses/lz4.txt"

mkdir -p "$W/out"
Z="$W/out/WWHD-PS4-Maker-$VERSION.zip"
rm -f "$Z"
# PkgTool rebuilt with room for the PlayGo chunk hashes (scripts/build-pkgtool.sh), LGPL-3.0 (its licence goes along)
[ -f "$W/pkgtool-fixed/PkgTool.Core.dll" ] || { echo "no $W/pkgtool-fixed: run scripts/build-pkgtool.sh" >&2; exit 1; }
mkdir -p "$B/maker/pkgtool"
cp "$W/pkgtool-fixed/"{PkgTool.Core.dll,LibOrbisPkg.Core.dll,PkgTool.Core.runtimeconfig.json,PkgTool.Core.deps.json} "$B/maker/pkgtool/"
cp "$W/pkgtool-fixed/LICENSE-LibOrbisPkg.txt" "$B/licenses/LibOrbisPkg-LGPL-3.0.txt"
# PERSO=<folder>: icon0.png and pic1.png of one player's own (perso\ in the Maker's folder, see the Maker)
if [ -n "${PERSO:-}" ]; then mkdir -p "$B/perso" && cp "$PERSO/icon0.png" "$PERSO/pic1.png" "$B/perso/"; fi
(cd "$W/bundle" && zip -qr -9 "$Z" "WWHD-PS4-Maker-$VERSION")
ls -la "$Z"
sha256sum "$Z"
