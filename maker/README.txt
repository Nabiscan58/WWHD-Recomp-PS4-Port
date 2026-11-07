WWHD-PS4 Maker - The Legend of Zelda: The Wind Waker HD (Wii U) on PS4 with GoldHEN
====================================================================================
(Version française : LISEZ-MOI.txt)

This program builds, on YOUR Windows PC, YOUR PS4 package (.pkg) of the game, from YOUR Wii U copy:
  - a .wud or .wux disc image with its disc key (.key) and the Wii U common key (common.key, or Cemu's keys.txt),
  - or a Cemu .wua archive (no key needed),
  - or an extracted folder (with code\, content\, meta\: dumpling, Cemu, or the PC port's data\game folder).
Version 0 of the game (USA 00050000-10143500 or Europe 00050000-10143600), without the update.

The Maker contains no game, no game code and no key. The package it builds contains the game (its recompiled code
and, by default, its files): it is yours alone, never share it.

The window is in French when Windows is in French, in English otherwise. The log is always in English.

What you need
-------------
  - Windows 10 or 11 64-bit, 8 GB of RAM (16 recommended), about 15 GB free.
  - An Internet connection on first launch: the Maker downloads LLVM 21 (~940 MB), the OpenOrbis toolchain
    (~160 MB) and SMW's PS4 SDK (~15 MB, the RADV Vulkan driver for the PS4 GPU) once, checked by SHA-256, into
    tools\. If no .NET is installed, it also fetches Microsoft's portable .NET 8 runtime (for PkgTool), checked
    against the SHA-512 published by Microsoft: at step 1, not at the end. Nothing is installed into Windows.
  - If the connection drops during a download, the Maker waits for it to come back (up to 45 min) and resumes the
    file where it was.
  - A jailbroken PS4 with GoldHEN (tested on: PS4 Slim CUH-2016A, firmware 10.01, GoldHEN 2.4b18.x).

How to use it
-------------
  1. Unzip the archive anywhere (a short path, e.g. C:\WWHD-PS4).
  2. Run WWHD-PS4-Maker.exe (SmartScreen: "More info" then "Run anyway").
  3. Choose your game, the keys if it is a disc image (a .key next to the image and a common.key or keys.txt in
     the same folder are found automatically), and the output folder.
  4. Optional: the PS4's FTP address (GoldHEN: Settings > FTP Server, port 2121), e.g. 192.168.1.20:2121.
  5. Start. Steps: tools, game files, translation of the PowerPC code to C (a few minutes), compilation for the
     PS4's Jaguar CPU (the longest: 15 to 60 min depending on the PC), package, FTP upload.
     Steps without a percentage (translation, linking, PkgTool) show a moving bar and the elapsed time: it is not
     frozen.
     If the Maker stops (error, network drop, window closed), press Start again with the same output folder: the
     extracted game, the translated code and the files already compiled are reused. "Start over" deletes that work.
  6. On the PS4: GoldHEN > Package Installer, install WWHD-PS4-<version>.pkg (in /data/pkg if sent over FTP, or
     from an exFAT USB drive), then start "The Wind Waker HD" from the home screen.

Icon and launch image
---------------------
  If the Maker's perso\ folder contains icon0.png (512x512, the icon) and pic1.png (1920x1080, the image shown at
  launch), they replace the Maker's images in the package. Use images you have the right to use.

On the PS4
----------
  - Everything the game writes is in /data/WWHD: save\ (saves), user\ (settings, gamepads, shader caches),
    captures\wwhd.log (log), boot-trace.log and crash.log (after a crash), gpu\radv-ps4.log (the graphics driver),
    samples.log (where the time goes, with WWHD_PS4_PROFILE=1), env.txt (settings).
  - DualShock 4: Cross = A, Circle = B, Square = X... ; touchpad click = "-" button;
    L3 + R3 together = Home button (opens the port's Settings, where the buttons can also be remapped).
    The DS4's gyroscope aims like the GamePad's.
  - The GamePad screen is drawn inside the TV image (picture-in-picture, adjustable in Settings > Display).

Status and limits (please read)
-------------------------------
  Test version. Up to 0.1.4, the package presented itself as an application (RetroArch's parameters, meant for
  OpenGL) and the Vulkan graphics driver stayed blocked at start-up, console frozen. Since 0.1.5 it presents itself
  as a game, like SMW, SSBU, BOTW and TOTK: UNINSTALL the old package before installing the new one. If the
  /data/WWHD folder does not exist, create it over FTP (the application is not always allowed to create it
  itself). If it hangs, wait 2 minutes before turning the console off, fetch /data/WWHD over FTP (except game\ and
  save\): boot-trace.log, hang.log, gpu\radv-ps4.log, captures\wwhd.log, and send them with wwhd-symbols.txt from
  the output folder.
  The PS4's CPU (Jaguar, 1.6 GHz) is much slower than a PC's: currently 14-16 fps in game on a PS4 Slim; the
  original game targets 30 fps, and the 60 fps mode (WWHD_INTERP=1 in env.txt) will likely be too heavy.
  The PC port's online features (mod catalogue, downloads) are not available on PS4.

Updating the Maker (from 0.1.1 on)
----------------------------------
  Copy ALL the contents of the new zip (folder WWHD-PS4-Maker-<version>) into your Maker folder, replacing the
  files: your tools\ keeps LLVM, OpenOrbis, the SDK and .NET. Press Start with the same output folder, without
  ticking "Start over": the extracted game, the translated code and the compiled files are reused, only the link
  and the package are redone (a few minutes). The final package must be named WWHD-PS4-<version>.pkg. Uninstall
  the old package before installing the new one.

Credits
-------
  Wind Waker HD Recomp (ZeldaWWHDRecomp, MPL-2.0): the recompilation, the runtime, GX2 on Vulkan.
  SMW / SSBU (iHaiDeeZ / ShiroKlein, MIT): the PS4 runtime (heap, crash log, threads), the VideoOut WSI, the PS4
  SDK (Mesa's RADV ported to the PS4 GPU by Crema / DolphinPS4). OpenOrbis (toolchain, PkgTool; PkgTool rebuilt
  from LibOrbisPkg, LGPL-3.0), LLVM, SDL (with this project's PS4 drivers), glslang, LZ4, zstd, Cemu (MPL-2.0).
  Licences: licenses\.
  Source code: https://github.com/Nabiscan58/WWHD-Recomp-PS4-Port
  A fan project, not affiliated with Nintendo or Sony.
