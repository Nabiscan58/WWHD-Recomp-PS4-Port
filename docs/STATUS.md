# Status (English summary)

The full notes are in French in [`ETAT.md`](ETAT.md); this is the short version.

Test console: PS4 Slim CUH-2016A, firmware 10.01, GoldHEN 2.4b18.10. Game: Wind Waker HD EU.

## Where it stands (0.1.12)

- Boots and plays: sound, DualShock 4, saves in `/data/WWHD/save`.
- 25-30 fps on the title screen, **14-16 fps in game** (Outset Island, facing the village).
- Render thread 61-66 ms/frame, game code ~34 ms, GPU ~5.5 ms: **CPU-bound**.

## What was found on the console

- **The freeze at launch** was the package identity: RetroArch-style `param.sfo` (`CATEGORY gde`, meant for
  OpenGL/Piglet) makes RADV's first GPU-visible `sceKernelMapDirectMemory` (`prot 0x33`) never return. The "plain"
  homebrew identity (`APP_TYPE 1`, `CATEGORY gd`, `ATTRIBUTE 2`, no `right.sprx`), as used by the SMW, SSBU, BOTW and
  TOTK ports, fixes it, and also grants the 7th core and more flexible memory.
- **No working directory on PS4** (`getcwd` fails): every path must be absolute (env.txt, logs, saves).
- **OpenOrbis' PkgTool** fails around 2.2 GB ("Playgo Chunk hash file was not allocated enough space"): rebuilt with
  slack, `scripts/build-pkgtool.sh`.
- `--wrap`ped kernel calls run during libc start-up (the heap initializes there): no `getenv` or anything else in
  their fast path.
- SDL polled the pad ~1000 times a second and read its clock through a system call: fixed in `patches/`.

## Performance

The engine's own profiler (`WWHD_PROFILE=1`) at Outset: ~3,560 draws a frame at 17.5 µs each, ~42,000 GX2 register
writes (10 ms). Per draw phase (ms/frame): uniforms 15.4, vertex copies 9.1, shader lookup 7.8, textures 6.2,
record 4.5, submit 4.7, indices 4.4, descriptors 3.8. Upstream measured ~5 ms for this render thread on an Apple
M3 Max: a Jaguar core is about 13 times slower, and the engine is already heavily optimized.

Tried: Vulkan recording on a second thread plus GamePad PiP on demand (74 → 61.5 ms), graphics enhancements off
(little CPU effect), ThinLTO of the runtime (0.1.11, not measured cleanly yet), cached "onion" memory for the upload
arena (0.1.12, to be measured).

## Where help is needed

1. Spreading draw preparation over several cores (the Jaguar has 6-7; the renderer really uses one).
2. The translated game code (~34 ms): caps the game near 28 fps even with instant rendering.
3. Targeted engine work, measured with `WWHD_PROFILE=1`: uniforms, shader lookup, register writes.

Collecting data on the console: see the end of [`ETAT.md`](ETAT.md) (`WWHD_PROFILE`, `WWHD_PS4_PROFILE`,
`WWHD_GPU_TRACE`, `WWHD_KTRACE` in `/data/WWHD/env.txt`).
