#!/usr/bin/env python3
"""RADV's PS4 winsys (SMW's sdk-1, built from Crema's) writes its log, GPU hang and fault reports and flight recorder
under /data/Crema/gpu, the Crema emulator's folder. This points them to /data/WWHD//gpu (same length; the double slash
is one folder: /data/WWHD/gpu), so the port neither overwrites Crema's files nor mixes its reports with Crema's.
Idempotent.
    patch-radv-paths.py <build/mesa folder of SMW's sdk-1>
"""
import os
import sys

OLD, NEW = b"/data/Crema/", b"/data/WWHD//"


def patch(mesa):
    lib = os.path.join(mesa, "src", "amd", "common", "libamd_common.a")
    with open(lib, "rb") as f:
        data = f.read()
    n = data.count(OLD)
    if n:
        with open(lib + ".tmp", "wb") as f:
            f.write(data.replace(OLD, NEW))
        os.replace(lib + ".tmp", lib)
    return n


if __name__ == "__main__":
    print("radv paths: %d replaced" % patch(sys.argv[1]))
