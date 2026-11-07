# Port status and log book

*[Version française](ETAT.md)*

This document sums up where the port stands, what was found and fixed during the console tests, and what is left to
do. It is meant to let others pick up the work without walking the same road again.

Test console: PS4 Slim CUH-2016A, firmware 10.01, GoldHEN 2.4b18.10. Game: The Wind Waker HD, EU version (title
0005000010143600).

## In short

- **The game boots and plays** (since 0.1.5): correct sound, DualShock 4, saves in `/data/WWHD/save`.
- **It is slow**: 25 to 30 fps on the title screen, **14 to 16 fps in game** (Outset Island, facing the village).
  The bottleneck is the **CPU**, not the GPU (see "Performance").

## What was found on the console (in order)

| Version | Problem | Cause | Fix |
| --- | --- | --- | --- |
| 0.1.0 | Freeze at launch, PS button does nothing | Assumed: guest memory overlapped the GPU address range RADV reserves (`0x40_0000_0000`) | Guest memory at `0x30_0000_0000`, stacks at `0x34–0x3C` (kept, but it was not the cause) |
| 0.1.2–0.1.4 | Still the freeze | Diagnosis: the main thread stays blocked in `sceKernelMapDirectMemory` with GPU access (`prot 0x33`), on the driver's very first memory block | See 0.1.5 |
| 0.1.5 | **The game boots** | The package used RetroArch's identity (`CATEGORY gde`, an application), meant for OpenGL/Piglet. Vulkan on GNM needs the "plain" homebrew identity (`APP_TYPE 1`, `CATEGORY gd`, `ATTRIBUTE 2`, no `right.sprx`), like SMW, SSBU, BOTW, TOTK | "Plain" `param.sfo`. Bonus: the PS4 grants the 7th core and 332 MB of flexible memory instead of 255 |
| 0.1.3 | Immediate freeze, no log | The `--wrap` wrappers of kernel calls called `getenv` during libc start-up (the heap initializes from inside libc) | 0.1.4: nothing but a direct pass-through while tracing is off |
| 0.1.5 | 1 fps | The diagnostic tools (RADV flight recorder, `fsync` every second) | Off by default (0.1.6) |
| 0.1.5 | `env.txt` ignored, no `wwhd.log` | No working directory on PS4 (`getcwd` fails): relative paths lead nowhere. Saves would have failed too | Absolute paths everywhere (0.1.6) |
| 0.1.6 | 100 MB package without the game | OpenOrbis' PkgTool crashes on some package sizes: "Playgo Chunk hash file was not allocated enough space" (reproduced at 2.2 GB) | PkgTool rebuilt with some slack, like BOTW/SMW: `scripts/build-pkgtool.sh` (0.1.7) |
| — | `/data/WWHD` missing after a forced shutdown | The folder entry had not been written to disk; on some consoles the application cannot create a folder in `/data` | `fsync` of the folder (0.1.5); otherwise create it over FTP |
| 0.1.8 | SDL main thread at ~45 % of a core | Gamepad read ~1000 times a second, SDL clock (`CLOCK_MONOTONIC_PRECISE`) through a system call per read | Gamepad read every 4 ms, clock on the TSC (0.1.9) |

## Performance

Measured in game, Outset Island facing the village, 1x (1280×720), 30 fps mode, Vulkan recording on a second
thread, GamePad screen in "automatic picture-in-picture", graphics enhancements off:

| | ms per frame |
| --- | --- |
| Render thread (command preparation) | 61–66 |
| Game (translated code) | ~34 |
| GPU | ~5.5 |

Report of the engine's built-in profiler (`WWHD_PROFILE=1`, 0.1.11):

- **~3,560 draws per frame**, 17.5 µs each; ~42,000 GX2 register writes (10 ms).
- Per draw phase (ms/frame): shader constants 15.4 · vertex copies 9.1 · shader lookup 7.8 · textures 6.2 ·
  recording 4.5 · submission 4.7 · indices 4.4 · descriptors 3.8 · targets 3.4 · pipeline 1.7.
- Uploads to the GPU: ~11 MiB/frame, 8.8 MiB of it vertices (2.1 MiB unique: the game rewrites these areas every
  frame).
- The game waits for the renderer ~33 ms per frame (`DrawDone`).

For comparison: the engine's documentation (upstream `docs/vulkan.md`) measures **~5 ms** for the render thread on
this same scene on an Apple M3 Max. A Jaguar core is about 13 times slower. The engine is already heavily optimized
(15 fast paths on by default): the problem is the amount of work on a single slow core.

What was tried:

| Attempt | Effect |
| --- | --- |
| Vulkan recording on a second thread + GamePad in automatic PiP | Render CPU 74 → 61.5 ms, 13 → 16 fps |
| Graphics enhancements off (AO, full-size depth, torches, clouds) | Little effect on the CPU side |
| ThinLTO of the runtime (0.1.11) | Not measurable: the profiler active that day cost a few ms itself |
| Upload arena in cached "onion" memory (0.1.12, `WWHD_VK_UPLOAD_CACHED`) | To be measured |

## Where help is needed

1. **Spreading draw preparation over several cores.** It is the only lever capable of a real jump: the Jaguar has 6
   to 7 cores, the renderer really uses one. A major rework of the engine (`gx2/`, `gfx/vulkan/`).
2. **The game code** (~34 ms) caps the game near 28 fps even with instant rendering: compile options of the
   translated code, PGO, the game's hot functions (sampler `WWHD_PS4_PROFILE=1`).
3. **Targeted engine gains**, measured with `WWHD_PROFILE=1`: shader constants (15 ms), shader lookup (8 ms),
   register writes (10 ms).

A user on Reddit (Orpheuseyes) reported running WWHD smoothly on a PS4 with the same recompiler, walking around
Windfall, before deleting the videos without sharing the project: there is likely more to gain than the numbers
above suggest.

## Collecting measurements

On the console, in `/data/WWHD/env.txt` (one `NAME=value` line per setting):

- `WWHD_PROFILE=1`: the engine's detailed report every 120 frames in `captures/wwhd.log`;
- `WWHD_PS4_PROFILE=1`: sampler, one minute starting at 45 s, into `samples.log`; the addresses are read with
  `wwhd-symbols.txt` (Maker output folder);
- `WWHD_GPU_TRACE=1`: RADV flight recorder (`gpu/flight`), very costly;
- `WWHD_KTRACE=1`: trace of the driver's kernel calls at start-up.

The game's performance overlay (L3+R3 menu) shows Game CPU, Render CPU and GPU.
