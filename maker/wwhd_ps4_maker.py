#!/usr/bin/env python3
"""WWHD-PS4 Maker: your own PS4 package (.pkg, for GoldHEN) of The Legend of Zelda: The Wind Waker HD, built on your
PC from YOUR Wii U game (disc image .wud/.wux with its keys, Cemu archive .wua, or an extracted game folder).

    python wwhd_ps4_maker.py --game <image|archive|folder> [--disc-key FILE] [--common-key FILE|--common-key-hex HEX]
                             --out <folder> [--work <folder>] [--data in-pkg|ftp] [--ftp IP:PORT] [--jobs N]
    python wwhd_ps4_maker.py --upload-only --ftp IP:PORT --out <folder>        (send what an earlier run made)
    python wwhd_ps4_maker.py --check                                            (only download and check the tools)

The steps, as Wind Waker HD Recomp's own setup does them for the PC, then the PS4's:
  1. tools: LLVM 21 (clang, ld.lld), the OpenOrbis PS4 toolchain, SMW's PS4 SDK (RADV, libc++), downloaded once into
     tools/ and checked against their SHA-256 (nothing to install, no administrator rights)
  2. the game files: extracted from your image or archive (upstream's wwhd-extract), or your folder as it is
  3. the game's PowerPC code translated to C (upstream's tools/recomp/recomp.py)
  4. that C compiled for the PS4's CPU (AMD Jaguar, -march=btver2), linked with the PS4 runtime (sdk/) into
     eboot.bin (create-fself)
  5. the package: param.sfo, icons, eboot.bin, the system modules and (--data in-pkg, the default) the game files,
     built with PkgTool into <out>/WWHD-PS4-<version>.pkg
  6. optional (--ftp): the package to /data/pkg on the PS4 (GoldHEN's FTP server), and with --data ftp the game files
     to /data/WWHD/game

The package holds the game's code (recompiled) and, by default, its files: it is yours alone, never share it.
Output lines: "== n/N title" steps, "progress <done> <total> <label>", everything else is the log.
"""
import argparse
import ftplib
import glob
import hashlib
import http.client
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # the Maker's folder
WWHD = os.path.join(ROOT, "wwhd")                 # upstream's tools (patches/BASE.txt), as in its PC release
SDK = os.path.join(ROOT, "sdk")                   # the PS4 runtime (scripts/make-sdk.py)
TOOLS = os.path.join(ROOT, "tools")
IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""
TITLE = "The Wind Waker HD"
TITLE_ID = "WWHD00064"
CONTENT_LABEL = "WINDWAKERHDPS400"
ENV_TXT = """# Wind Waker HD on PS4: settings read at every start, one NAME=value per line ('#' comments).
# Any WWHD_ setting of the PC version works here (its README), for example:
# WWHD_INTERP=1          60 fps by frame interpolation (heavy for the PS4's CPU; default: the game's 30 fps)
# WWHD_GAME_DIR=/data/WWHD/game   where the game files are (default: inside the package, else this folder's game/)
# WWHD_LOG_FILE=0        no captures/wwhd.log
# WWHD_GPU_TRACE=0       no GPU flight recorder in gpu/flight (on in the test versions)
# WWHD_WATCHDOG=0        no startup watchdog (hang.log, "watchdog:" lines in boot-trace.log)
"""


class MakerError(Exception):
    pass


_SAY = threading.Lock()


def say(text=""):
    with _SAY:  # the heartbeat thread and the compilers' progress share stdout
        print(text, flush=True)


# The window passes WWHD_LANG=fr when Windows is in French; the detail lines and step titles follow it. The log
# itself stays in English (easier to share in bug reports).
FR = os.environ.get("WWHD_LANG", "") == "fr"


def T(french, english):
    return french if FR else english


def step(n, total, title):
    say("")
    say("== %d/%d %s" % (n, total, title))


def progress(done, total, label):
    say("progress %d %d %s" % (done, total, label))


def status(text):
    """A one-line state for the window's detail line (elapsed time of silent work)."""
    say("status %s" % text)


class Busy:
    """While a long step prints nothing (the translation, the link, PkgTool): every 5 s a status line with the elapsed
    time, so a slow PC does not look frozen."""

    def __init__(self, label, hint=""):
        self.label, self.hint = label, hint
        self.stop = threading.Event()

    def _beat(self):
        t0 = time.time()
        while not self.stop.wait(5):
            e = int(time.time() - t0)
            status("%s : %d min %02d s%s" % (self.label, e // 60, e % 60, (" (" + self.hint + ")") if self.hint else ""))

    def __enter__(self):
        status("%s..." % self.label)
        self.t = threading.Thread(target=self._beat, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.t.join()
        status("")


def fwd(p):
    return os.path.abspath(p).replace("\\", "/")


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else "%d B" % n
        n /= 1024.0


def free_space(path):
    while not os.path.exists(path):
        path = os.path.dirname(path)
    return shutil.disk_usage(path).free


def run(cmd, cwd=None, env=None, quiet=False, what=None):
    """Runs a command; its output goes to the log. Raises MakerError when it fails."""
    cmd = [str(c) for c in cmd]
    if not quiet:
        say("> " + " ".join([os.path.basename(cmd[0])] + cmd[1:])[:400])
    flags = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0:
        raise MakerError("%s failed (exit %d):\n%s" % (what or os.path.basename(cmd[0]), p.returncode,
                                                         "\n".join(out.strip().splitlines()[-25:])))
    if out.strip() and not quiet:
        say("\n".join("  " + l for l in out.strip().splitlines()[-8:]))
    return out


# ---------------------------------------------------------------------------------------------------------------
# tools: pinned downloads


def pins():
    with open(os.path.join(HERE, "pins.json")) as f:
        return json.load(f)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


WAIT_FOR_NETWORK = 45 * 60  # how long a download waits for the connection to come back, in seconds


def fetch(url, dst, label, check):
    """Downloads url to dst, resuming a partial download, and waiting (up to WAIT_FOR_NETWORK) for the connection to
    come back instead of stopping. check(path) -> error text or None (a checksum)."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    deadline = None
    while True:
        try:
            have = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
            headers = {"User-Agent": "WWHD-PS4-Maker"}
            if have:
                headers["Range"] = "bytes=%d-" % have
            say("  downloading %s%s" % (label, " (resuming at %s)" % human(have) if have else ""))
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                if have and r.status != 206:
                    have = 0  # the server ignored the range: from the start
                total = have + int(r.headers.get("Content-Length") or 0)
                with open(tmp, "ab" if have else "wb") as f:
                    done, last = have, 0.0
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        done += len(b)
                        deadline = None  # data flows again
                        if time.time() - last > 0.5:
                            progress(done, total or done, T("téléchargement de ", "downloading ") + label)
                            last = time.time()
                if total and done < total:  # the connection ended early without an error
                    raise ConnectionError("cut at %s of %s" % (human(done), human(total)))
            break
        except urllib.error.HTTPError as e:
            if e.code == 416 and os.path.isfile(tmp):  # the partial file is already whole
                break
            raise MakerError("cannot download %s: %s" % (label, e))
        except (OSError, http.client.HTTPException) as e:
            if deadline is None:
                deadline = time.time() + WAIT_FOR_NETWORK
            if time.time() > deadline:
                raise MakerError("cannot download %s (%s): no connection for %d minutes. Start again when the "
                                 "connection is back: the work already done is kept." % (label, e, WAIT_FOR_NETWORK // 60))
            say("  connection problem (%s): waiting for it to come back, trying again in 20 s" % e)
            status(T("En attente de la connexion Internet (%s) : le travail fait est gardé", "Waiting for the Internet connection (%s): the work done is kept") % label)
            time.sleep(20)
    problem = check(tmp)
    if problem:
        os.remove(tmp)
        raise MakerError("%s: %s" % (label, problem))
    os.replace(tmp, dst)
    return dst


def download(url, dst, sha256, label):
    if os.path.isfile(dst) and sha256_of(dst) == sha256:
        return dst

    def check(path):
        got = sha256_of(path)
        return None if got == sha256 else "the download does not match its SHA-256 (got %s)" % got

    return fetch(url, dst, label, check)


def extract_tar(archive, dst, strip, keep=None):
    """Extracts a .tar.gz / .tar.xz in one pass (no seeking), the first `strip` path components dropped; keep:
    a function of the stripped name, False to skip a member."""
    tmp = dst + ".partial"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    mode = "r|xz" if archive.endswith(".xz") else "r|gz"
    links = []
    with tarfile.open(archive, mode) as t:
        for m in t:
            parts = m.name.split("/")[strip:]
            if not parts or not parts[0]:
                continue
            name = "/".join(parts)
            if keep and not keep(name):
                continue
            if ".." in parts or name.startswith("/"):
                continue
            out = os.path.join(tmp, *parts)
            if m.isdir():
                os.makedirs(out, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with t.extractfile(m) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)
                if m.mode & 0o111:
                    os.chmod(out, 0o755)
            elif m.issym() or m.islnk():
                links.append((out, m.linkname, m.issym()))
    for out, target, sym in links:  # (Windows has no symbolic links to speak of: copies)
        src = os.path.join(os.path.dirname(out), target) if sym else os.path.join(tmp, *target.split("/")[strip:])
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
    shutil.rmtree(dst, ignore_errors=True)
    os.replace(tmp, dst)


class Tools:
    def __init__(self):
        p = pins()
        host = "windows" if IS_WIN else "linux"
        self.llvm = os.path.join(TOOLS, "llvm")
        self.openorbis = os.path.join(TOOLS, "openorbis")
        self.smw = os.path.join(TOOLS, "smw-ps4-sdk")
        self.pins, self.host = p, host
        self.clang = os.path.join(self.llvm, "bin", "clang" + EXE)
        self.lld = os.path.join(self.llvm, "bin", "ld.lld" + EXE)
        self.ar = os.path.join(self.llvm, "bin", "llvm-ar" + EXE)
        oob = os.path.join(self.openorbis, "bin", host)
        self.create_fself = os.path.join(oob, "create-fself" + EXE)
        self.pkgtool = os.path.join(oob, "PkgTool.Core" + EXE)
        self.dotnet = None

    def ensure(self):
        dl = os.path.join(TOOLS, "downloads")
        llvm = self.pins["llvm-" + self.host]
        if not os.path.isfile(self.clang) or not os.path.isfile(self.lld):
            a = download(llvm["url"], os.path.join(dl, llvm["file"]), llvm["sha256"], "LLVM %s" % llvm["version"])
            say("  unpacking LLVM (the compiler and linker only)")
            wanted = tuple(llvm["keep"])
            extract_tar(a, self.llvm, 1, lambda n: n.startswith(wanted))
            if IS_WIN and not os.path.isfile(self.lld) and os.path.isfile(os.path.join(self.llvm, "bin", "lld.exe")):
                shutil.copy2(os.path.join(self.llvm, "bin", "lld.exe"), self.lld)
        oo = self.pins["openorbis"]
        if not os.path.isfile(os.path.join(self.openorbis, "link.x")):
            a = download(oo["url"], os.path.join(dl, oo["file"]), oo["sha256"], "OpenOrbis PS4 toolchain")
            say("  unpacking the OpenOrbis toolchain")
            extract_tar(a, self.openorbis, 2, lambda n: n.split("/")[0] in ("bin", "include", "lib", "link.x",
                                                                              "samples", "LICENSE"))
        smw = self.pins["smw-sdk"]
        if not os.path.isdir(os.path.join(self.smw, "build", "mesa")):
            a = download(smw["url"], os.path.join(dl, smw["file"]), smw["sha256"], "SMW PS4 SDK (RADV, libc++)")
            say("  unpacking the PS4 SDK")
            extract_tar(a, self.smw, 1)
        for f in (self.clang, self.lld, self.ar, self.create_fself):
            if not os.path.isfile(f):
                raise MakerError("missing after the download: %s (delete the tools folder and start again)" % f)
        # RADV's reports into /data/WWHD/gpu, not the Crema emulator's folder (scripts/patch-radv-paths.py)
        lib = os.path.join(self.smw, "build", "mesa", "src", "amd", "common", "libamd_common.a")
        with open(lib, "rb") as f:
            data = f.read()
        if b"/data/Crema/" in data:
            with open(lib + ".tmp", "wb") as f:
                f.write(data.replace(b"/data/Crema/", b"/data/WWHD//"))
            os.replace(lib + ".tmp", lib)
        if IS_WIN and not self.dotnet:  # now, not after an hour of compiling (PkgTool needs it at the end)
            self.dotnet = os.environ.get("WWHD_MAKER_DOTNET") or find_or_get_dotnet(dl)
            say("  .NET for PkgTool: %s" % self.dotnet)
        say("  tools ready: LLVM %s, OpenOrbis %s, SMW sdk-%s" % (llvm["version"], oo["version"], smw["version"]))

    def pkgtool_cmd(self):
        """PkgTool.Core (LibOrbisPkg): the .NET Core 3 program of OpenOrbis' bin/windows, run by whatever .NET is
        there (DOTNET_ROLL_FORWARD=Major) or by the runtime the Maker downloaded. Elsewhere without a .NET, the
        self-contained Linux build (which needs OpenSSL 1.x)."""
        # maker/pkgtool: PkgTool rebuilt with room for the PlayGo chunk hashes (scripts/build-pkgtool.sh); OpenOrbis'
        # stopped on WWHD's 2.2 GB package with "Playgo Chunk hash file was not allocated enough space" (0.1.6)
        dll = os.path.join(HERE, "pkgtool", "PkgTool.Core.dll")
        if not os.path.isfile(dll):
            dll = os.path.join(self.openorbis, "bin", "windows", "PkgTool.Core.dll")
        if IS_WIN and not self.dotnet:
            self.dotnet = os.environ.get("WWHD_MAKER_DOTNET") or find_or_get_dotnet(os.path.join(TOOLS, "downloads"))
        dotnet = self.dotnet or (None if IS_WIN else shutil.which("dotnet"))
        env = dict(os.environ, DOTNET_ROLL_FORWARD="Major", DOTNET_SYSTEM_GLOBALIZATION_INVARIANT="1",
                   DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
        if not dotnet:
            return [self.pkgtool], env
        if os.path.dirname(os.path.abspath(dotnet)).startswith(TOOLS):
            env["DOTNET_ROOT"] = os.path.dirname(dotnet)
        return [dotnet, dll], env


def find_or_get_dotnet(dl):
    """A .NET runtime for PkgTool.Core (Windows): an installed one (any version from 3), else Microsoft's portable
    runtime zip, found in Microsoft's release list with its SHA-512 and unpacked into tools/dotnet."""
    local = os.path.join(TOOLS, "dotnet", "dotnet.exe")
    candidates = [local, os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "dotnet", "dotnet.exe")]
    for c in candidates:
        if os.path.isfile(c):
            try:
                out = subprocess.run([c, "--list-runtimes"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     creationflags=0x08000000).stdout.decode("utf-8", "replace")
                if re.search(r"Microsoft\.NETCore\.App ([89]|\d\d)\.", out):  # the fixed PkgTool is for .NET 8
                    return c
            except OSError:
                pass
    channel = pins()["dotnet"]["channel"]
    meta_url = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/%s/releases.json" % channel
    say("  no .NET runtime found: getting Microsoft's portable .NET %s runtime (for PkgTool, into tools\\dotnet; "
        "nothing is installed in Windows)" % channel)
    os.makedirs(dl, exist_ok=True)
    meta_file = os.path.join(dl, "dotnet-releases-%s.json" % channel)
    if os.path.exists(meta_file):
        os.remove(meta_file)
    fetch(meta_url, meta_file, ".NET release list", lambda p: None)
    try:
        with open(meta_file, encoding="utf-8") as m:
            meta = json.load(m)
        files = meta["releases"][0]["runtime"]["files"]
        f = next(x for x in files if x.get("rid") == "win-x64" and x["name"].endswith(".zip"))
    except (OSError, ValueError, KeyError, StopIteration) as e:
        raise MakerError("Microsoft's .NET release list could not be read (%s). Install the \".NET Runtime\" 8 (x64) "
                         "from Microsoft's site and start again." % e)
    zpath = os.path.join(dl, os.path.basename(f["url"]))

    def sha512_ok(path):
        h = hashlib.sha512()
        with open(path, "rb") as z:
            for b in iter(lambda: z.read(1 << 20), b""):
                h.update(b)
        return None if h.hexdigest().lower() == f["hash"].lower() else "does not match Microsoft's SHA-512"

    if not (os.path.isfile(zpath) and not sha512_ok(zpath)):
        fetch(f["url"], zpath, ".NET runtime", sha512_ok)
    shutil.rmtree(os.path.join(TOOLS, "dotnet"), ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(os.path.join(TOOLS, "dotnet"))
    return local


# ---------------------------------------------------------------------------------------------------------------
# the game files and the translated code: upstream's setup (tools/installer/setup.py) does it


def upstream_setup():
    sys.path.insert(0, os.path.join(WWHD, "tools", "installer"))
    sys.path.insert(0, os.path.join(WWHD, "tools", "recomp"))
    import setup as ws  # noqa: E402  (Wind Waker HD Recomp's setup, MPL-2.0)
    return ws


def prepare_game(ws, args, work):
    """The game folder (code/, content/, meta/) to build from: extracted into <work>/game, or the given folder."""
    src = os.path.abspath(args.game)
    if os.path.isdir(src):
        if not ws.valid_game_folder(src):
            raise MakerError("%s is not an extracted game folder (it needs code/cking.rpx, content/, meta/meta.xml)" % src)
        tid = ws.game_folder_title(src)
        if tid:
            ws.check_title(tid)
        build = ws.check_game_version(src)
        say("  %s: %s, version 0" % (src, build.name))
        return src
    if not os.path.isfile(src):
        raise MakerError("not found: %s" % src)
    ext = os.path.splitext(src)[1].lower()
    mark = os.path.join(work, "game.source")
    me = "%s|%d|%d" % (src, os.path.getsize(src), int(os.path.getmtime(src)))
    done = os.path.join(work, "game")
    if ws.valid_game_folder(done):
        # upstream's extract_game only puts a complete, checked extraction there (staging folder, then a rename);
        # without game.source it was made by 0.1.0, which wrote no mark
        same = True
        if os.path.isfile(mark):
            with open(mark, encoding="utf-8") as f:
                same = f.read().strip() == me
        if same:
            try:
                build = ws.check_game_version(done)
                say("  the game files extracted by an earlier run are reused (%s)" % build.name)
                with open(mark, "w", encoding="utf-8") as f:
                    f.write(me)
                return done
            except Exception:
                pass
    if os.path.isfile(mark):
        os.remove(mark)
    if ext == ".wua":
        problem, err, info = ws.archive_info(src)
        if problem and problem != "wrong_title":
            raise MakerError("cannot read the Cemu archive: %s" % err)
        title, notes = ws.archive_choice(info)
        for n in notes:
            say("  " + n)
        say("  %s from the archive (no keys needed)" % ws.title_desc(info["title_id"], int(info["version"])))
        ws.extract_game(src, None, info, work, title)
    elif ext in (".wud", ".wux"):
        req = {}
        if args.disc_key:
            req["disc_key_file"] = args.disc_key
        if args.common_key:
            req["common_key_file"] = args.common_key
        if args.common_key_hex:
            req["common_key_hex"] = args.common_key_hex
        keys, info, why, notices = ws.resolve_disc_keys(src, req)
        if why:
            raise MakerError(why[1])
        for n in notices:
            say("  " + n)
        ws.check_title(info.get("title_id", ""))
        say("  %s, %s files, %s" % (ws.title_desc(info.get("title_id", "")), info.get("files"),
                                     human(int(info.get("bytes", 0)))))
        ws.extract_game(src, keys, info, work, None)
    else:
        raise MakerError("%s: give a disc image (.wud, .wux), a Cemu archive (.wua) or an extracted game folder" % src)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(me)
    return done


# ---------------------------------------------------------------------------------------------------------------
# compile, link, eboot


def recomp_digest(ws):
    """SHA-256 of upstream's recompiler (tools/recomp): the translated code is reused while it and the game match."""
    root = os.path.join(ws.PKG, "tools", "recomp")
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for fn in sorted(fns):
            if fn.endswith((".pyc", ".pyo")):
                continue
            p = os.path.join(dp, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode() + b"\0")
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


# The game code's compiled files depend on its options and the runtime headers it includes (sdk/include), not on the
# rest of the runtime: a new runtime with the same headers only needs a new link (minutes, not the 30-60 min compile).
SAME_HEADERS_AS_0_1_1 = ("1c6e1d570c3c921235d6a7334f39f847d70596e1048e5f6ccf8b923190b034bc",)


def gamecode_headers_digest():
    root = os.path.join(SDK, "include")
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode() + b"\0")
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def folder_size(path):
    total = 0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def manifest():
    p = os.path.join(SDK, "manifest.json")
    if not os.path.isfile(p):
        raise MakerError("sdk/manifest.json is missing: unpack the Maker again")
    with open(p) as f:
        return json.load(f)


def placeholders(tools, extra=None):
    m = {"sdk": fwd(SDK), "openorbis": fwd(tools.openorbis), "sysroot": fwd(os.path.join(tools.smw, "sysroot")),
         "mesa": fwd(os.path.join(tools.smw, "build", "mesa"))}
    m.update(extra or {})
    return m


def sub(arg, m):
    for k, v in m.items():
        arg = arg.replace("{%s}" % k, v)
    return arg


def default_jobs():
    n = os.cpu_count() or 2
    try:
        if IS_WIN:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("a", ctypes.c_ulonglong * 5)]
            ms = MS()
            ms.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            avail = ms.ullAvailPhys
        else:
            avail = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        n = min(n, max(1, int((avail - (2 << 30)) / (1.5 * (1 << 30)))))  # ~1.5 GB per compiler, 2 GB for Windows
    except Exception:
        pass
    return max(1, n)


def compile_gamecode(tools, man, gen, obj_dir, jobs):
    os.makedirs(obj_dir, exist_ok=True)
    srcs = sorted(glob.glob(os.path.join(glob.escape(gen), "code_*.c")))
    srcs += [os.path.join(gen, f) for f in ("table.c", "imports.c")]
    srcs.sort(key=lambda s: -os.path.getsize(s))  # big files first: better use of the cores
    m = placeholders(tools, {"gen": fwd(gen)})
    flags = [sub(a, m) for a in man["gamecode_cflags"]] + ["-g0"]
    done, failures, lock = [0], [], threading.Lock()
    todo = sum(1 for src in srcs if not (os.path.isfile(os.path.join(obj_dir, os.path.basename(src) + ".o")) and
                                         os.path.getmtime(os.path.join(obj_dir, os.path.basename(src) + ".o"))
                                         >= os.path.getmtime(src)))
    if todo:
        say("  %d of %d files to compile, %d at a time" % (todo, len(srcs), jobs))
    else:
        say("  everything is already compiled: nothing to do")
    flags_low = 0x08000000 | 0x00004000 if IS_WIN else 0  # no window, below-normal priority: the PC stays usable

    def one(src):
        obj = os.path.join(obj_dir, os.path.basename(src) + ".o")
        if os.path.isfile(obj) and os.path.getmtime(obj) >= os.path.getmtime(src):
            out, rc = "", 0  # done by an interrupted earlier run
        else:
            p = subprocess.run([tools.clang] + flags + ["-c", fwd(src), "-o", fwd(obj + ".tmp")],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags_low)
            out, rc = p.stdout.decode("utf-8", "replace"), p.returncode
            if rc == 0:
                os.replace(obj + ".tmp", obj)
        with lock:
            if rc != 0:
                failures.append((src, out))
            done[0] += 1
            progress(done[0], len(srcs), T("compilation du code du jeu", "compiling the game code"))
        return obj

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        objs = [f.result() for f in as_completed([ex.submit(one, s) for s in srcs])]
    if failures:
        src, out = failures[0]
        raise MakerError("compiling %s failed:\n%s" % (os.path.basename(src), "\n".join(out.strip().splitlines()[-20:])))
    return sorted(objs)


def patched_link_script(tools, work):
    """OpenOrbis' link.x with toolchain/ps4-app.cmake's changes (prioritized constructors, per-symbol data)."""
    with open(os.path.join(tools.openorbis, "link.x")) as f:
        s = f.read()
    if "*(.init_array);" not in s:
        raise MakerError("unexpected OpenOrbis link.x (no '*(.init_array);')")
    s = s.replace("*(.init_array);", "KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*))); KEEP(*(.init_array));")
    for rule in (".data", ".tdata", ".tbss"):
        if "*(%s)" % rule not in s:
            raise MakerError("unexpected OpenOrbis link.x (no '*(%s)')" % rule)
        s = s.replace("*(%s)" % rule, "*(%s %s.*)" % (rule, rule))
    out = os.path.join(work, "ps4-link.x")
    with open(out, "w") as f:
        f.write(s)
    return out


def link(tools, man, objs, work):
    lib = os.path.join(work, "libgamecode.a")
    if os.path.exists(lib):
        os.remove(lib)
    rsp = os.path.join(work, "ar.rsp")
    with open(rsp, "w", encoding="utf-8") as f:
        f.write("\n".join('"%s"' % fwd(o) for o in objs))
    run([tools.ar, "rcs", fwd(lib), "@" + fwd(rsp)], quiet=True, what="archiving the game code")
    elf = os.path.join(work, "wwhd.elf")
    m = placeholders(tools, {"gamecode": fwd(lib), "out": fwd(elf), "linkx": fwd(patched_link_script(tools, work))})
    args = [sub(a, m) for a in man["link"]]
    rsp = os.path.join(work, "link.rsp")
    with open(rsp, "w", encoding="utf-8") as f:
        f.write("\n".join('"%s"' % a.replace("\\", "/") for a in args))
    say("  linking (the game code with the PS4 runtime and RADV)")
    run([tools.lld, "@" + fwd(rsp)], quiet=True, what="linking")
    return elf


def write_symbols(elf, path):
    """The function symbols of the linked ELF as text ("address size name", sorted): small enough to send with
    hang.log or crash.log, whose eboot addresses it names (wwhd.elf itself is over 100 MB)."""
    with open(elf, "rb") as f:
        data = f.read()
    if data[:4] != b"\x7fELF" or data[4] != 2:
        return
    shoff, = struct.unpack_from("<Q", data, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + k * shentsize) for k in range(shnum)]
    out = []
    for sh in sections:
        if sh[1] != 2:  # SHT_SYMTAB
            continue
        stroff = sections[sh[6]][4]
        off, size, entsize = sh[4], sh[5], sh[9] or 24
        for k in range(size // entsize):
            name, info, _other, _shndx, value, sz = struct.unpack_from("<IBBHQQ", data, off + k * entsize)
            if info & 0xF != 2 or not value:  # functions only
                continue
            end = data.index(b"\0", stroff + name)
            out.append((value, sz, data[stroff + name:end].decode("utf-8", "replace")))
    out.sort()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for value, sz, name in out:
            f.write("%x %x %s\n" % (value, sz, name))


def check_oelf(path):
    """The console refuses an OELF with more than one read-write PT_LOAD ("CE-41839-5"), which some create-fself
    versions write depending on the size of .data.rel.ro."""
    with open(path, "rb") as f:
        head = f.read(64)
        if head[:4] != b"\x7fELF":
            raise MakerError("create-fself wrote no ELF")
        phoff, = struct.unpack_from("<Q", head, 32)
        phentsize, phnum = struct.unpack_from("<HH", head, 54)
        f.seek(phoff)
        table = f.read(phentsize * phnum)
    rw = 0
    for i in range(phnum):
        ptype, pflags = struct.unpack_from("<II", table, i * phentsize)
        if ptype == 1 and pflags & 2:  # PT_LOAD, PF_W
            rw += 1
    if rw != 1:
        raise MakerError("the eboot has %d read-write segments (expected 1): the console would refuse it" % rw)


def make_eboot(tools, man, elf, stage, work):
    oelf = os.path.join(work, "wwhd.oelf")
    eboot = os.path.join(stage, "eboot.bin")
    env = dict(os.environ, OO_PS4_TOOLCHAIN=tools.openorbis)
    run([tools.create_fself, "-in=" + fwd(elf), "-out=" + fwd(oelf), "--eboot", fwd(eboot),
         "--paid", man["paid"], "--authinfo", man["authinfo"]], env=env, quiet=True, what="create-fself")
    check_oelf(oelf)
    say("  eboot.bin: %s" % human(os.path.getsize(eboot)))


# ---------------------------------------------------------------------------------------------------------------
# the package


def copy_tree(src, dst, label):
    files = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs]
    total = sum(os.path.getsize(f) for f in files) or 1
    done = 0
    for i, f in enumerate(files):
        out = os.path.join(dst, os.path.relpath(f, src))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            os.link(f, out)  # same drive: no copy
        except OSError:
            shutil.copy2(f, out)
        done += os.path.getsize(f)
        if i % 200 == 0 or i == len(files) - 1:
            progress(done, total, label)


def write_gp4(stage, path, content_id):
    """The PkgTool project of the package (the GP4 that OpenOrbis' create-gp4 writes), with every file of the staged
    folder and the whole folder tree (create-gp4 leaves folders out, which PkgTool then stops on; SMW's
    gp4-fix-dirs.py)."""
    files = []
    for r, dirs, fs in os.walk(stage):
        dirs.sort()
        for n in sorted(fs):
            rel = os.path.relpath(os.path.join(r, n), stage).replace("\\", "/")
            if rel != os.path.basename(path):
                files.append(rel)
    root = ET.Element("psproject", {"fmt": "gp4", "version": "1000"})
    vol = ET.SubElement(root, "volume")
    ET.SubElement(vol, "volume_type").text = "pkg_ps4_app"
    ET.SubElement(vol, "volume_id").text = "PS4VOLUME"
    ET.SubElement(vol, "volume_ts").text = time.strftime("%Y-%m-%d %H:%M:%S")
    ET.SubElement(vol, "package", {"content_id": content_id, "passcode": "0" * 32, "storage_type": "digital50",
                                   "app_type": "full"})
    ci = ET.SubElement(vol, "chunk_info", {"chunk_count": "1", "scenario_count": "1"})
    ET.SubElement(ET.SubElement(ci, "chunks"), "chunk", {"id": "0", "layer_no": "0", "label": "Chunk #0"})
    sc = ET.SubElement(ET.SubElement(ci, "scenarios", {"default_id": "0"}), "scenario",
                       {"id": "0", "type": "sp", "initial_chunk_count": "1", "label": "Scenario #0"})
    sc.text = "0"
    fe = ET.SubElement(root, "files", {"img_no": "0"})
    for f in files:
        ET.SubElement(fe, "file", {"targ_path": f, "orig_path": f})
    rootdir = ET.SubElement(root, "rootdir")
    nodes = {"": rootdir}
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(len(parts)):
            key = "/".join(parts[:i + 1])
            if key not in nodes:
                nodes[key] = ET.SubElement(nodes["/".join(parts[:i])], "dir", {"targ_name": parts[i]})
    if "sce_module" not in nodes:
        ET.SubElement(rootdir, "dir", {"targ_name": "sce_module"})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return len(files)


def make_pkg(tools, stage, out_dir, version, name_version):
    pk, env = tools.pkgtool_cmd()
    content_id = "IV0000-%s_00-%s" % (TITLE_ID, CONTENT_LABEL)
    sce = os.path.join(stage, "sce_sys")
    sfo = os.path.join(sce, "param.sfo")
    if os.path.exists(sfo):
        os.remove(sfo)
    run(pk + ["sfo_new", fwd(sfo)], env=env, quiet=True, what="PkgTool sfo_new")
    # The plain OpenOrbis homebrew identity (a game: APP_TYPE 1, CATEGORY gd), as the Vulkan ports that run (SMW,
    # SSBU, BOTW, TOTK, Dusklight: their SFO_STYLE=plain, no right.sprx). 0.1.0 to 0.1.4 used RetroArch's launch
    # parameters (an application, CATEGORY gde), which are for OpenGL (Piglet): with them the driver's first GPU
    # memory mapping (sceKernelMapDirectMemory with GPU access) never returned and the console froze.
    # ATTRIBUTE 0x2: system dialogs confirm with Cross.
    entries = [("APP_TYPE", "Integer", 4, "1"), ("ATTRIBUTE", "Integer", 4, "2"), ("CATEGORY", "Utf8", 4, "gd"),
               ("SYSTEM_VER", "Integer", 4, "0"), ("APP_VER", "Utf8", 8, version),
               ("CONTENT_ID", "Utf8", 48, content_id), ("DOWNLOAD_DATA_SIZE", "Integer", 4, "0"),
               ("TITLE", "Utf8", 128, TITLE), ("TITLE_ID", "Utf8", 12, TITLE_ID), ("VERSION", "Utf8", 8, version)]
    for name, kind, size, value in entries:
        run(pk + ["sfo_setentry", fwd(sfo), name, "--type", kind, "--maxsize", str(size), "--value", value],
            env=env, quiet=True, what="PkgTool sfo_setentry " + name)
    gp4 = os.path.join(stage, "pkg.gp4")
    if os.path.exists(gp4):
        os.remove(gp4)
    n = write_gp4(stage, gp4, content_id)
    say("  building the package (PkgTool, %d files)" % n)
    tmp_out = os.path.join(out_dir, "pkgtool")
    shutil.rmtree(tmp_out, ignore_errors=True)
    os.makedirs(tmp_out)
    with Busy(T("PkgTool construit le paquet", "PkgTool is building the package"), T("plusieurs minutes pour quelques Go, pas de pourcentage", "several minutes for a few GB, no percentage")):
        run(pk + ["pkg_build", "pkg.gp4", fwd(tmp_out)], cwd=stage, env=env, quiet=True, what="PkgTool pkg_build")
    os.remove(gp4)
    built = os.path.join(tmp_out, content_id + ".pkg")
    if not os.path.isfile(built):
        raise MakerError("PkgTool wrote no package")
    final = os.path.join(out_dir, "WWHD-PS4-%s.pkg" % name_version)
    if os.path.exists(final):
        os.remove(final)
    os.replace(built, final)
    shutil.rmtree(tmp_out, ignore_errors=True)
    return final


def stage_package(tools, stage, game_dir, data_in_pkg):
    """The package's files except eboot.bin and param.sfo: icons, the system modules, version.txt, the game files."""
    sce = os.path.join(stage, "sce_sys")
    os.makedirs(sce, exist_ok=True)
    for f in ("icon0.png", "pic1.png"):
        # perso\icon0.png (512x512) and perso\pic1.png (1920x1080, shown while the game starts), in the Maker's folder,
        # replace the Maker's own pictures
        mine = os.path.join(ROOT, "perso", f)
        shutil.copy2(mine if os.path.isfile(mine) else os.path.join(HERE, "sce_sys", f), os.path.join(sce, f))
        if os.path.isfile(mine):
            say("  %s: yours (perso\\%s)" % (f, f))
    samples = os.path.join(tools.openorbis, "samples", "piglet")
    os.makedirs(os.path.join(stage, "sce_module"), exist_ok=True)
    for prx in glob.glob(os.path.join(samples, "sce_module", "*.prx")):
        shutil.copy2(prx, os.path.join(stage, "sce_module", os.path.basename(prx)))
    with open(os.path.join(stage, "version.txt"), "w") as f:
        f.write(manifest()["version"] + "\n")
    if data_in_pkg:
        copy_tree(game_dir, os.path.join(stage, "game"), T("copie des fichiers du jeu dans le paquet", "putting the game files in the package"))


# ---------------------------------------------------------------------------------------------------------------
# FTP (GoldHEN's FTP server, port 2121)


def ftp_connect(addr):
    host, _, port = addr.partition(":")
    f = ftplib.FTP()
    f.connect(host, int(port or 2121), timeout=30)
    f.login()
    f.set_pasv(True)
    return f


def ftp_mkdirs(f, path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        try:
            f.mkd(cur)
        except ftplib.error_perm:
            pass


def ftp_put(f, local, remote, label):
    try:
        if f.size(remote) == os.path.getsize(local):
            return  # already there (an interrupted upload resumes)
    except ftplib.all_errors:
        pass
    total, done = os.path.getsize(local) or 1, [0]

    def cb(b):
        done[0] += len(b)
        if done[0] % (8 << 20) < len(b):
            progress(done[0], total, label)

    with open(local, "rb") as src:
        f.storbinary("STOR " + remote, src, 1 << 20, cb)


def upload(addr, pkg, game_dir):
    say("  connecting to %s" % addr)
    f = ftp_connect(addr)
    try:
        ftp_mkdirs(f, "/data/pkg")
        ftp_put(f, pkg, "/data/pkg/" + os.path.basename(pkg), T("envoi du paquet", "sending the package"))
        say("  package sent to /data/pkg/%s" % os.path.basename(pkg))
        ftp_mkdirs(f, "/data/WWHD")
        env_txt = os.path.join(os.path.dirname(pkg), "env.txt")
        if os.path.isfile(env_txt):
            try:
                f.size("/data/WWHD/env.txt")  # never replace the player's own settings
            except ftplib.all_errors:
                ftp_put(f, env_txt, "/data/WWHD/env.txt", "settings")
        if game_dir:
            files = [os.path.join(r, n) for r, _, fs in os.walk(game_dir) for n in fs]
            for i, local in enumerate(files):
                rel = os.path.relpath(local, game_dir).replace("\\", "/")
                remote = "/data/WWHD/game/" + rel
                ftp_mkdirs(f, os.path.dirname(remote))
                ftp_put(f, local, remote, T("envoi des fichiers du jeu", "sending the game files"))
                if i % 50 == 0 or i == len(files) - 1:
                    progress(i + 1, len(files), T("envoi des fichiers du jeu", "sending the game files"))
            say("  game files sent to /data/WWHD/game")
    finally:
        try:
            f.quit()
        except ftplib.all_errors:
            pass


# ---------------------------------------------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="WWHD-PS4 Maker")
    ap.add_argument("--game", help="disc image (.wud/.wux), Cemu archive (.wua) or extracted game folder")
    ap.add_argument("--disc-key", help="the image's disc key file (default: IMAGE.key) or Cemu's keys.txt")
    ap.add_argument("--common-key", help="the Wii U common key file, or Cemu's keys.txt")
    ap.add_argument("--common-key-hex", help="the Wii U common key, 32 hex digits")
    ap.add_argument("--out", help="where the package goes")
    ap.add_argument("--work", help="the work folder (default: <out>/work; about 6 GB, keep it for faster rebuilds)")
    ap.add_argument("--data", choices=("in-pkg", "ftp"), default="in-pkg",
                    help="the game files inside the package (default), or sent to /data/WWHD/game over FTP")
    ap.add_argument("--ftp", help="the PS4's FTP server (GoldHEN), e.g. 192.168.1.20:2121")
    ap.add_argument("--jobs", type=int, help="compilers at once (default: what the free memory allows)")
    ap.add_argument("--gen-dir", help="(build checks) use this translated code instead of recompiling the game")
    ap.add_argument("--upload-only", action="store_true", help="send what an earlier run made (needs --ftp, --out)")
    ap.add_argument("--check", action="store_true", help="only get and check the tools")
    ap.add_argument("--fresh", action="store_true", help="start from scratch (default: reuse what an interrupted "
                    "run already did: extracted game, translated code, compiled files)")
    args = ap.parse_args()
    try:
        tools = Tools()
        if args.check:
            step(1, 1, T("Outils", "Tools"))
            tools.ensure()
            return 0
        if not args.out:
            raise MakerError("--out is needed")
        out = os.path.abspath(args.out)
        os.makedirs(out, exist_ok=True)
        work = os.path.abspath(args.work or os.path.join(out, "work"))
        if " " in work and not IS_WIN:
            raise MakerError("the work folder's path must not contain spaces: %s" % work)
        version = manifest()["version"]
        version_sfo = "%02d.%02d" % tuple(int(x) for x in (version.split(".") + ["0"])[1:3])  # 0.1.0 -> 01.00
        if args.upload_only:
            if not args.ftp:
                raise MakerError("--upload-only needs --ftp")
            pkg = os.path.join(out, "WWHD-PS4-%s.pkg" % version)
            if not os.path.isfile(pkg):
                raise MakerError("no %s: build it first" % pkg)
            gd = os.path.join(work, "game") if args.data == "ftp" else None
            step(1, 1, T("Envoi vers la PS4", "Sending to the PS4"))
            upload(args.ftp, pkg, gd if gd and os.path.isdir(gd) else None)
            return 0
        if not args.game and not args.gen_dir:
            raise MakerError("--game is needed")
        total = 6 if args.ftp else 5
        os.makedirs(work, exist_ok=True)
        need = (8 << 30) if args.data == "in-pkg" else (5 << 30)
        if free_space(work) < need:
            raise MakerError("not enough free space for the work folder %s (%s needed)" % (work, human(need)))

        step(1, total, T("Outils", "Tools"))
        tools.ensure()
        man = manifest()
        ws = upstream_setup()
        ws.LOG.open(os.path.join(work, "setup.log"))  # upstream's own log (extraction, translation)

        step(2, total, T("Les fichiers du jeu", "The game files"))
        if args.fresh:
            for d in ("game", "gen", "obj"):
                shutil.rmtree(os.path.join(work, d), ignore_errors=True)
            for f in ("game.source", "gen.done"):
                if os.path.isfile(os.path.join(work, f)):
                    os.remove(os.path.join(work, f))
            say("  --fresh: the work of earlier runs is thrown away")
        if args.gen_dir:
            game_dir = os.path.abspath(args.game) if args.game else None
            say("  build check: the given translated code, no game")
        else:
            game_dir = prepare_game(ws, args, work)

        step(3, total, T("Traduction du code du jeu (PowerPC vers C)", "Translating the game code (PowerPC to C)"))
        if args.gen_dir:
            gen = os.path.abspath(args.gen_dir)
        else:
            gen = os.path.join(work, "gen")
            gen_mark = os.path.join(work, "gen.done")
            me = "%s|%s" % (recomp_digest(ws), sha256_of(os.path.join(game_dir, "code", "cking.rpx")))
            reuse = False
            if os.path.isfile(os.path.join(gen, "report.txt")):  # recomp.py writes it last: a complete translation
                reuse = True  # no mark: made by 0.1.0, whose recompiler is this one
                if os.path.isfile(gen_mark):
                    with open(gen_mark, encoding="utf-8") as f:
                        reuse = f.read().strip() == me
            if reuse:
                say("  the code translated by an earlier run is reused")
            else:
                if os.path.isfile(gen_mark):
                    os.remove(gen_mark)
                t0 = time.time()
                with Busy(T("Traduction du code du jeu", "Translating the game code"), T("pas de pourcentage pour cette étape, de 10 à 40 min sur un PC lent", "no percentage for this step, 10 to 40 min on a slow PC")):
                    n = ws.recompile(game_dir, gen)
                with open(gen_mark, "w", encoding="utf-8") as f:
                    f.write(me)
                say("  %d source files (%d min)" % (n, (time.time() - t0) // 60))

        step(4, total, T("Compilation pour la PS4 (la partie longue)", "Compiling for the PS4 (this is the long part)"))
        obj_dir = os.path.join(work, "obj")
        obj_mark = os.path.join(obj_dir, "flags.txt")
        headers = gamecode_headers_digest()
        me = json.dumps(["headers", headers, man["gamecode_cflags"]])
        if os.path.isdir(obj_dir):
            old = ""
            if os.path.isfile(obj_mark):
                with open(obj_mark, encoding="utf-8") as f:
                    old = f.read()
            # 0.1.1 marked its files with its version: the same game code headers as now, they stay good
            if old == json.dumps(["0.1.1", man["gamecode_cflags"]]) and headers in SAME_HEADERS_AS_0_1_1:
                old = me
            if old != me:
                shutil.rmtree(obj_dir, ignore_errors=True)  # compiled by another version: compile again
            else:
                n = len(glob.glob(os.path.join(glob.escape(obj_dir), "*.o")))
                if n:
                    say("  %d files compiled by an earlier run are reused (only what is missing or changed is "
                        "compiled)" % n)
        os.makedirs(obj_dir, exist_ok=True)
        with open(obj_mark, "w", encoding="utf-8") as f:
            f.write(me)
        t0 = time.time()
        objs = compile_gamecode(tools, man, gen, obj_dir, args.jobs or default_jobs())
        say("  compiled in %d min" % ((time.time() - t0) // 60))
        with Busy(T("Édition des liens", "Linking"), T("quelques minutes, pas de pourcentage", "a few minutes, no percentage")):
            elf = link(tools, man, objs, work)
        stage = os.path.join(work, "stage")
        shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage)
        with Busy(T("Création de eboot.bin", "Making eboot.bin")):
            make_eboot(tools, man, elf, stage, work)
        shutil.copy2(elf, os.path.join(out, "wwhd.elf"))  # for symbolizing crash.log (llvm-symbolizer --obj)
        write_symbols(elf, os.path.join(out, "wwhd-symbols.txt"))

        step(5, total, T("Le paquet", "The package"))
        in_pkg = args.data == "in-pkg" and game_dir is not None
        stage_package(tools, stage, game_dir, in_pkg)
        need = (folder_size(game_dir) if in_pkg else 0) + (1 << 30)
        if free_space(out) < need:
            raise MakerError("not enough free space for the package in %s: %s needed (delete old WWHD-PS4-*.pkg "
                             "files)" % (out, human(need)))
        try:
            pkg = make_pkg(tools, stage, out, version_sfo, version)
        except MakerError as e:
            if not in_pkg:
                raise
            # the package without the game files then, which go to /data/WWHD/game instead (FTP); the reason in full
            lines = [l.strip() for l in str(e).splitlines() if l.strip()]
            why = next((l for l in lines if "Exception" in l or "rror" in l), lines[-1] if lines else "?")
            say("  the package with the game files failed: %s" % why)
            say("  (the whole PkgTool output is in the log above: %s)" % lines[0])
            for l in lines[1:]:
                say("    " + l)
            say("  building it without them: the game files then go to /data/WWHD/game (FTP)")
            shutil.rmtree(os.path.join(stage, "game"), ignore_errors=True)
            in_pkg = False
            pkg = make_pkg(tools, stage, out, version_sfo, version)
        with open(os.path.join(out, "env.txt"), "w") as f:
            f.write(ENV_TXT)
        for old in glob.glob(os.path.join(glob.escape(out), "WWHD-PS4-*.pkg")):  # earlier versions' packages (2+ GB each)
            if os.path.abspath(old) != os.path.abspath(pkg):
                try:
                    os.remove(old)
                    say("  removed the older package %s" % os.path.basename(old))
                except OSError:
                    pass
        say("  %s (%s)" % (pkg, human(os.path.getsize(pkg))))
        if not in_pkg and game_dir:
            say("  the game files are not in the package: they go to /data/WWHD/game on the PS4 (--ftp, or copy "
                "%s there yourself)" % game_dir)

        if args.ftp:
            step(6, total, T("Envoi vers la PS4", "Sending to the PS4"))
            upload(args.ftp, pkg, None if in_pkg else game_dir)
        say("")
        say("done: install %s with GoldHEN's Package Installer (/data/pkg) and start %s from the home screen."
            % (os.path.basename(pkg), TITLE))
        say("This package contains the game: it is yours alone, never share it.")
        return 0
    except MakerError as e:
        say("error: %s" % e)
        return 1
    except Exception as e:  # upstream's SetupError and the like
        if type(e).__name__ == "SetupError":
            say("error: %s" % e)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
