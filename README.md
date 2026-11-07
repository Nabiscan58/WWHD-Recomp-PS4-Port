# wwhd-ps4 — The Wind Waker HD (Wii U) on PS4 (GoldHEN)

*[Version française](README.fr.md)*

A PS4 port of [Wind Waker HD Recomp](https://github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp) (the static recompilation
of the Wii U game: PowerPC code translated to C, GX2 reimplemented on Vulkan), modelled on the PS4 ports of
[SMW](https://github.com/iHaiDeeZ/SMW) and [SSBU](https://github.com/iHaiDeeZ/SSBU): no emulator, the game code is
compiled for the PS4's Jaguar CPU and drawn with Mesa's RADV Vulkan driver ported to the PS4 GPU.

**No game, no game code and no keys here.** The package is built on your PC from your own copy of the game.

> **Status (0.1.13, same engine as 0.1.12): the game boots and plays on a PS4 Slim (GoldHEN), but slowly: 14 to 16 fps in game.**
> The bottleneck is the Jaguar CPU (preparing the graphics commands on a single core), not the GPU. Everything that
> was found, measured and tried, and the leads for going further: [`docs/STATUS.md`](docs/STATUS.md).
> Contributions are welcome.

## Playing: WWHD-PS4 Maker (Windows)

The `WWHD-PS4-Maker-<version>.zip` file, from the
[Releases](https://github.com/Nabiscan58/WWHD-Recomp-PS4-Port/releases) page, contains a Windows program that does
everything (see `maker/README.txt`). Its window is in French when Windows is in French, in English otherwise.

1. **Tools** — on first launch it downloads (SHA-256 checked, into `tools\`) LLVM 21.1.8, the OpenOrbis v0.5.2
   toolchain and SMW's PS4 SDK (RADV + libc++ 21); and, if no .NET is installed, Microsoft's portable .NET 8 runtime
   for PkgTool, right at this step. Downloads resume after a drop (HTTP Range) and wait for the connection to come
   back (up to 45 min).
2. **Game files** — extracted from your `.wud`/`.wux` image (with its keys) or Cemu `.wua` archive by the upstream
   project's extractor (`wwhd-extract`), or your already extracted folder as is. Version 0, USA or Europe, checked by
   SHA-256 (upstream's setup code).
3. **Translation** — upstream's `tools/recomp/recomp.py`: PowerPC → C.
4. **PS4 compilation** — clang 21 `--target=x86_64-pc-freebsd12-elf -march=btver2`, same options as the runtime;
   linked with the prebuilt PS4 runtime (`sdk/`) and RADV, then `create-fself` → `eboot.bin`.
5. **Package** — `param.sfo`, icons (original art), system modules, and by default the game files in `/app0/game`;
   GP4 project written by the Maker, `PkgTool pkg_build` → `WWHD-PS4-<version>.pkg`.
6. **FTP (optional)** — the `.pkg` into `/data/pkg` (GoldHEN's FTP server), and in "game files over FTP" mode the
   game into `/data/WWHD/game`.

Equivalent command line: `tools\python\python.exe maker\wwhd_ps4_maker.py --game <image|archive|folder>
[--disc-key F] [--common-key F] --out <folder> [--data in-pkg|ftp] [--ftp IP:2121] [--fresh]`.

If the Maker stops (error, network drop, window closed), run it again with the same output folder: the extracted
game, the translated code and the compiled files are reused.

## How the port works

| | PC (upstream) | PS4 (this repository) |
|---|---|---|
| Game code | PowerPC → C, clang | same, clang 21 for Jaguar (`-march=btver2`, no FMA contraction) |
| Guest memory | 4 GiB window at `0x2000_0000_0000` | 4 GiB window at `0x30_0000_0000` (below the `0x40_0000_0000` range RADV reserves for the GPU), **reserved**; 64 KiB blocks of direct memory are mapped on first access (SIGSEGV handler, `port/ps4_memory.cpp`, after SMW); pre-mapped before kernel reads (`read()` into guest memory) and before write protection (texture tracking) |
| Guest thread stacks | 64 MiB | 64 MiB of address space, mapped on use (same mechanism), 1 MiB pre-mapped |
| Window, pads, sound | SDL3 | SDL 3.4.18 with **PS4 drivers written for this project** (`patches/sdl3-3.4.18-ps4.patch`): "ps4" video (1920×1080, Vulkan through `VK_EXT_headless_surface`), ScePad gamepads (DualShock 4 reported as such, gyro, accelerometer, touchpad, rumble, light bar, up to 4 players), sceAudioOut sound (48 kHz, float stereo) |
| Vulkan | system loader | RADV (Mesa, Crema's GNM winsys) linked statically + VideoOut WSI (`port/ps4_vk_wsi.cpp`, from SSBU/SMW; here with an sRGB format for the final image) |
| Heap, threads, crashes | system | SMW's PS4 runtime (`port/`): dlmalloc, crt1 with a malloc replacement table, pthreads on all cores, boot and crash logs |
| Data | game folder | `/data/WWHD` (saves, settings, caches, logs, `env.txt`); game in `/app0/game` or `/data/WWHD/game` |

Changes to the upstream project (`patches/wwhd-ps4.patch`, on the commit in `patches/BASE.txt`): guest window base,
lazy reservation, 16 KiB page size, pre-mapping for write tracking, lazy stacks, PS4 start-up (`wwhd_ps4_startup`),
crash report chained to the port's, crash addresses as ELF addresses, absolute save/crash paths, `PS4` CMake branch,
`PS4_LTO` option, cached upload arena option.

Controls: Cross/Circle/Square/Triangle = A/B/X/Y (configurable in the game's Settings), touchpad click = "−",
**L3 + R3 = Home** (opens the port's Settings: the PS4 does not give the PS button to applications).

### Things that matter on PS4 (learned the hard way)

- **Package identity:** Vulkan on GNM needs the "plain" homebrew `param.sfo` (`APP_TYPE 1`, `CATEGORY gd`,
  `ATTRIBUTE 2`, no `right.sprx`), as in SMW, SSBU, BOTW and TOTK. With RetroArch's identity (`CATEGORY gde`, an
  application, meant for OpenGL/Piglet), RADV's first GPU-visible `sceKernelMapDirectMemory` never returns and the
  console freezes.
- **No working directory:** `getcwd` fails on PS4, so every path (env.txt, logs, saves, shader cache) is absolute.
- **`--wrap`ped kernel calls run during libc start-up** (the heap initializes there): nothing like `getenv` in
  their fast path.
- **OpenOrbis' PkgTool** fails around 2.2 GB ("Playgo Chunk hash file was not allocated enough space"): the Maker
  ships PkgTool rebuilt from LibOrbisPkg with more room for the PlayGo hashes (`scripts/build-pkgtool.sh`).

### Link-time optimization (0.1.11)

The runtime's C++ (outside `port/`, the game code and the libraries) is compiled to ThinLTO bitcode (the patched
CMakeLists' `PS4_LTO` option). `scripts/make-sdk.py` turns it into a single native object, `sdk/obj/runtime-lto.o`,
with `ld.lld -r --lto-O3`: cross-file optimization (inlining between `gx2/` and `gfx/vulkan/`, where the render
thread spends its time) is done once when the SDK is built, and the Maker's link stays as fast as before. Checked:
every malloc/free/calloc, pthread_create, clock_gettime and mmap call of the runtime still goes through the `--wrap`
functions of `port/ps4_runtime.cpp`.

## For maintainers: building the SDK and the Maker (Linux or WSL)

```
scripts/build-sdk.sh ~/wwhd-ps4-build        # toolchains, SDL3/glslang/LZ4 for PS4, runtime + test eboot, sdk/
maker/build-bundle.sh ~/wwhd-ps4-build       # the Windows Maker zip (apt install mono-mcs mono-devel zip)
```

`toolchain/ps4.cmake` is a standalone CMake toolchain (LLVM 21 + OpenOrbis + SMW's libc++ 21 sysroot), usable from
Linux or Windows. Note: `--sysroot`, not `-isysroot` (otherwise clang reads the host's `/usr/include` headers), and
`-z nodynamic-undefined-weak` (otherwise `create-fself` rejects `thread_local` initialization functions).

Repository layout:

| Path | Contents |
| --- | --- |
| `maker/` | the Windows Maker: `WWHD-PS4-Maker.cs` (window), `wwhd_ps4_maker.py` (all the work), `build-bundle.sh`, `sce_sys/` (original icons) |
| `port/` | PS4 platform layer: memory, runtime wrappers, crash log, VideoOut WSI, sampler, kernel trace |
| `patches/` | changes to Wind Waker HD Recomp and to SDL 3.4.18 |
| `scripts/` | SDK build (`build-sdk.sh`, `make-sdk.py`), PkgTool rebuild, RADV path patch |
| `toolchain/` | CMake toolchain files for the PS4 |
| `docs/` | status, findings and performance notes (`STATUS.md` in English, `ETAT.md` in French) |

## Diagnostics on the console

- `/data/WWHD/boot-trace.log`: start-up steps (modules, memory, swapchain, first flips).
- `/data/WWHD/gpu/radv-ps4.log` (+ `gpu-hang.txt`, `gpu-fault.txt`): the RADV winsys; the `/data/Crema/` paths of
  `libamd_common.a` are replaced with `/data/WWHD//` (`scripts/patch-radv-paths.py`).
- `/data/WWHD/crash.log`: registers, code addresses on the stack (ELF addresses: `llvm-symbolizer --obj=wwhd.elf
  0x...`, `wwhd.elf` is in the Maker's output folder), state of every thread.
- `/data/WWHD/captures/wwhd.log` and `captures/crash-*.log`: the game's log and its crash report (guest registers,
  game call chain).
- `env.txt` accepts every `WWHD_*` setting of the upstream project, plus the port's own (see `docs/STATUS.md`).

## Contributing

The most useful thing now is performance (see [`docs/STATUS.md`](docs/STATUS.md), "Where help is needed"). Issues
and pull requests are welcome. For a console report, attach `boot-trace.log`, `captures/wwhd.log` (with
`WWHD_PROFILE=1`), a photo of the performance overlay (L3+R3) and, for `samples.log` or `hang.log`, the
`wwhd-symbols.txt` of the same build. Never attach game files, keys or a built `.pkg`.

## Licences and credits

The code in this repository is under the MIT licence (see `LICENSE`, and `NOTICE` for the third-party portions); the changes to the upstream project
(`patches/wwhd-ps4.patch`) stay under MPL-2.0 like it; the new SDL files are under the zlib licence. The Maker also
contains PkgTool rebuilt from LibOrbisPkg (maxton, LGPL-3.0), with a single change (the room for the PlayGo hashes,
as in BOTW and SMW): `scripts/build-pkgtool.sh`.

Thanks to ZeldaWWHDRecomp (the recompilation and the runtime), iHaiDeeZ / ShiroKlein and BelmanteGu (SMW, SSBU: PS4
runtime, WSI, SDK), Crema / DolphinPS4 (RADV on GNM), OpenOrbis, LLVM, SDL, glslang, LZ4, zstd, Cemu. A fan project,
not affiliated with Nintendo or Sony.
