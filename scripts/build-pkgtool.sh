#!/usr/bin/env bash
# PkgTool from LibOrbisPkg's source (LGPL-3.0, github.com/maxton/LibOrbisPkg) with one change, as BOTW and SMW build it
# (their scripts/build-pkgtool.sh): room to spare for the PlayGo chunk hashes. OpenOrbis' PkgTool sizes them from an
# estimate that falls short for some package sizes: "Playgo Chunk hash file was not allocated enough space" (WWHD-PS4
# 0.1.6 with the game files, 2.2 GB, reproduced here and fixed by this build). For .NET 8 (the runtime the Maker uses).
#
#   scripts/build-pkgtool.sh [work dir]   -> <work>/pkgtool-fixed   (needs the .NET 8 SDK, git)
set -euo pipefail
W="$(cd "${1:-$HOME/wwhd-ps4-build}" && pwd)"
REV=643477263b2644e0803e0f58b8726ea4e3f3b7d4
S="$W/src/LibOrbisPkg"
[ -d "$S" ] || git clone -q https://github.com/maxton/LibOrbisPkg.git "$S"
git -C "$S" checkout -q "$REV"
git -C "$S" checkout -q -- .
sed -i 's|e.DataSize = (uint)(pkgSize / 0x10000L) \* 4;|e.DataSize = (uint)(pkgSize / 0x10000L) * 4 + 0x10000;  // slack: the estimate fell short|' \
    "$S/LibOrbisPkg/PKG/PkgBuilder.cs"
grep -q "slack: the estimate" "$S/LibOrbisPkg/PKG/PkgBuilder.cs" || { echo "the PlayGo sizing line moved" >&2; exit 1; }
sed -i 's|<TargetFramework>netcoreapp3.0</TargetFramework>|<TargetFramework>net8.0</TargetFramework>|' \
    "$S/PkgTool.Core/PkgTool.Core.csproj" "$S/LibOrbisPkg.Core/LibOrbisPkg.Core.csproj"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
rm -rf "$W/pkgtool-fixed"
dotnet publish "$S/PkgTool.Core/PkgTool.Core.csproj" -c Release -o "$W/pkgtool-fixed" -p:UseAppHost=false -p:DebugType=none | tail -1
cp "$S/LICENSE.txt" "$W/pkgtool-fixed/LICENSE-LibOrbisPkg.txt"
