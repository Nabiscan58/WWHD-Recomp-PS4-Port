#!/usr/bin/env python3
"""Maintainers: the Maker's sdk/ from a PS4 build of the runtime (scripts/build-sdk.sh runs this).

The Maker compiles the player's recompiled game code and links it against what is here, exactly as the build linked
the placeholder game code. Everything is open source; there is no game code (the build's libgamecode.a, made from
upstream's placeholder stubs, becomes {gamecode}).

    make-sdk.py --build <wwhd build dir> --wwhd <upstream source> --port <wwhd-ps4 folder> --openorbis <dir>
                --sysroot <SMW sdk-1 sysroot> --mesa <SMW sdk-1 build/mesa> --version <v> --out <sdk dir>

sdk/
  manifest.json   gamecode_cflags and the link line, with placeholders the Maker fills in:
                  {sdk} this folder, {gen} the translated game code, {gamecode} its archive, {out} the ELF,
                  {openorbis} the OpenOrbis toolchain, {sysroot} / {mesa} SMW's sdk-1 (downloaded by the Maker),
                  {linkx} OpenOrbis' link.x as the Maker patches it (toolchain/ps4-app.cmake's changes)
  obj/            the runtime's objects, lib/ its libraries (SDL3, glslang, LZ4, ImGui, Cemu's Latte pieces, ...);
                  the runtime's ThinLTO bitcode (PS4_LTO) as one native object, runtime-lto.o, made here with
                  ld.lld -r (the link-time optimization done once, not on every player's PC)
  include/        what the game code includes (upstream runtime/include)
  licenses/       the licenses of everything in obj/ and lib/
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys


def norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def under(p, root):
    p, root = norm(p), norm(root)
    return p == root or p.startswith(root + os.sep)


def rel(p, root):
    return os.path.relpath(norm(p), norm(root)).replace(os.sep, "/")


def link_command(build):
    lines = subprocess.check_output(["ninja", "-C", build, "-t", "commands", "wwhd"], text=True).splitlines()
    cmd = lines[-1].strip()
    parts = [p.strip() for p in cmd.split(" && ")]
    links = [p for p in parts if re.search(r"(^|\s)-o\s+\"?wwhd(\.elf)?\"?(\s|$)", p)]
    if len(links) != 1:
        sys.exit("cannot find the link step in: " + cmd[:400])
    args = shlex.split(links[0])
    out = []
    for a in args:
        if a.startswith("@") and os.path.isfile(os.path.join(build, a[1:])):
            with open(os.path.join(build, a[1:])) as f:
                out += shlex.split(f.read())
        else:
            out.append(a)
    return out


def is_bitcode(path):
    with open(path, "rb") as f:
        magic = f.read(4)
    return magic in (b"BC\xc0\xde", b"\xde\xc0\x17\x0b")


def lto_prelink(lld, bitcode, out, jobs):
    """The ThinLTO bitcode objects as one native relocatable object (ld.lld -r runs the LTO backends)."""
    cmd = [lld, "-r", "-m", "elf_x86_64", "--lto-O3", "--thinlto-jobs=%d" % jobs, "-o", out] + bitcode
    print("sdk: link-time optimization of %d runtime objects (ld.lld -r)..." % len(bitcode), flush=True)
    subprocess.check_call(cmd)
    if is_bitcode(out):
        sys.exit("ld.lld -r left bitcode in " + out)


def main():
    ap = argparse.ArgumentParser()
    for opt in ("build", "wwhd", "port", "openorbis", "sysroot", "mesa", "version", "out"):
        ap.add_argument("--" + opt, required=True)
    a = ap.parse_args()
    build = os.path.abspath(a.build)
    sdk = os.path.abspath(a.out)
    if os.path.exists(sdk):
        shutil.rmtree(sdk)
    for d in ("obj", "lib", "include", "licenses"):
        os.makedirs(os.path.join(sdk, d))

    places = [(a.openorbis, "{openorbis}"), (a.sysroot, "{sysroot}"), (a.mesa, "{mesa}")]

    def placeholder(p):
        for root, name in places:
            if under(p, root):
                r = rel(p, root)
                return name if r == "." else name + "/" + r
        return None

    # ---- the link line
    args = link_command(build)
    recipe, objs, libs, seen = [], 0, 0, {}
    bitcode = []  # ThinLTO objects: one prelinked object at the first one's place
    it = iter(range(1, len(args)))
    skip = False
    for i in it:
        x = args[i]
        if skip:
            skip = False
            continue
        if x == "-o":
            recipe += ["-o", "{out}"]
            skip = True
            continue
        if x == "--script":
            recipe += ["--script", "{linkx}"]  # ps4-link.x: the Maker patches OpenOrbis' link.x the same way
            skip = True
            continue
        if x.startswith("-L"):
            p = placeholder(x[2:])
            if not p:
                sys.exit("unexpected library folder on the link line: " + x)
            recipe.append("-L" + p)
            continue
        path = x if os.path.isabs(x) else os.path.join(build, x)
        if not x.startswith("-") and os.path.isfile(path):
            name = os.path.basename(x)
            if name == "libgamecode.a":
                recipe.append("{gamecode}")
                continue
            p = placeholder(path)
            if p:
                recipe.append(p)  # a library of the downloaded toolchain or of SMW's sdk-1
                continue
            if name.endswith(".o") and is_bitcode(path):
                if not bitcode:
                    recipe.append("{sdk}/obj/runtime-lto.o")
                    objs += 1
                bitcode.append(path)
                continue
            if name.endswith(".o"):
                r = re.sub(r"^CMakeFiles/[^/]+\.dir/", "", rel(path, build))
                flat = re.sub(r"[^A-Za-z0-9_.+-]", "_", r)
                shutil.copy2(path, os.path.join(sdk, "obj", flat))
                recipe.append("{sdk}/obj/" + flat)
                objs += 1
                continue
            if name.endswith(".a"):
                real = os.path.realpath(path)
                if seen.get(name, real) != real:
                    sys.exit("two different libraries named %s on the link line" % name)
                if name not in seen:
                    seen[name] = real
                    shutil.copy2(real, os.path.join(sdk, "lib", name))
                    libs += 1
                recipe.append("{sdk}/lib/" + name)
                continue
            sys.exit("unexpected file on the link line: " + x)
        if os.path.isabs(x) and not x.startswith("-"):
            sys.exit("unexpected path on the link line: " + x)
        recipe.append(x)
    if not objs or "{gamecode}" not in recipe:
        sys.exit("link line not understood: " + " ".join(args)[:400])
    if bitcode:
        lto_prelink(args[0], bitcode, os.path.join(sdk, "obj", "runtime-lto.o"), os.cpu_count() or 2)

    # ---- the game code's compile options (those of the placeholder code_000.c)
    with open(os.path.join(build, "compile_commands.json")) as f:
        db = json.load(f)
    e = next(e for e in db if re.search(r"[\\/]code_000\.c$", e["file"]))
    cargs = e.get("arguments") or shlex.split(e["command"])
    gen = os.path.dirname(e["file"])
    inc = os.path.join(a.wwhd, "runtime", "include")
    cflags, i = [], 1
    while i < len(cargs):
        x = cargs[i]
        i += 1
        if x in ("-o", "-MF", "-MT", "-MQ"):
            i += 1
            continue
        if x in ("-c", "-MD", "-MMD") or norm(x) == norm(e["file"]):
            continue
        val = None
        for opt in ("-I", "-isystem", "--sysroot="):
            if x == opt.rstrip("=") and opt != "--sysroot=":
                val, x = cargs[i], opt
                i += 1
                break
            if x.startswith(opt) and len(x) > len(opt):
                val, x = x[len(opt):], opt
                break
        if val is None:
            cflags.append(x)
            continue
        if under(val, inc):
            p = "{sdk}/include"
        elif norm(val) == norm(gen):
            p = "{gen}"
        else:
            p = placeholder(val)
        if not p:
            sys.exit("unexpected include folder in the game code's compile command: %s %s" % (x, val))
        cflags.append(x + p)
    shutil.copytree(inc, os.path.join(sdk, "include"), dirs_exist_ok=True)

    # ---- licenses
    lic = os.path.join(sdk, "licenses")
    for src, name in [(os.path.join(a.wwhd, "LICENSE"), "WindWakerHDRecomp-MPL-2.0.txt"),
                      (os.path.join(a.wwhd, "runtime", "third_party", "cemu", "LICENSE.txt"), "Cemu-MPL-2.0.txt"),
                      (os.path.join(a.port, "LICENSE"), "wwhd-ps4-MIT.txt"),
                      (os.path.join(a.port, "docs", "LICENSE-SMW.txt"), "SMW-MIT.txt")]:
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(lic, name))
    with open(os.path.join(lic, "README.txt"), "w") as f:
        f.write("obj/: Wind Waker HD Recomp's runtime (MPL-2.0, source: github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp)\n"
                "with wwhd-ps4's patch, and wwhd-ps4's port/ (MIT; parts from SMW and SSBU, MIT).\n"
                "lib/: SDL 3.4.18 with wwhd-ps4's PS4 drivers (zlib), glslang 16.0.0 (BSD-3-Clause and others),\n"
                "LZ4 1.10.0 (BSD-2-Clause), Dear ImGui and ImGuizmo (MIT), fmt (MIT), Cemu's Latte decompiler\n"
                "and address library (MPL-2.0), zstd (BSD-3-Clause), as built from source by scripts/build-sdk.sh.\n"
                "No game code, no game files, no keys.\n")

    manifest = {
        "format": 1,
        "name": "wwhd-ps4",
        "version": a.version,
        "wwhd_base": open(os.path.join(a.port, "patches", "BASE.txt")).read().strip(),
        "gamecode_cflags": cflags,
        "link": recipe,
    }
    cache = open(os.path.join(build, "CMakeCache.txt"), encoding="utf-8", errors="replace").read()
    for key, name in (("PS4_PAID", "paid"), ("PS4_AUTH_INFO", "authinfo")):
        m = re.search(r"^%s:[A-Z]+=(.*)$" % key, cache, re.M)
        if not m:
            sys.exit("no %s in the build's CMakeCache.txt" % key)
        manifest[name] = m.group(1).strip()
    with open(os.path.join(sdk, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("sdk: %d objects (%d runtime objects optimized together), %d libraries, link line of %d arguments, "
          "%d game code options -> %s" % (objs, len(bitcode), libs, len(recipe), len(cflags), sdk))


if __name__ == "__main__":
    main()
