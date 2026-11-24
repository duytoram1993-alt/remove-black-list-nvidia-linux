#!/usr/bin/env python3
"""
patch_nvidia_blacklist.py - Remove NVIDIA Linux Restricted Mining-Card SKU Table

Removes the 5 Pascal mining GPU Device IDs from the NVIDIA proprietary Linux kernel
module (`nvidia.ko`, `nvidia.ko.xz`, `nvidia.ko.zst`, or `nvidia.ko.gz`):
  - 0x1B07 : P102-100
  - 0x1B87 : P104-100
  - 0x1BC7 : P104-101
  - 0x1C07 : P106-100
  - 0x1C09 : P106-090

Why:
  The proprietary NVIDIA Linux driver matches these 5 PCI Device IDs in an internal
  `.rodata` table and injects an artificial ~218 us delay per 3D/gr3d submission batch
  (`method 0x3998 = 0xF0`), severely throttling OpenGL/Vulkan/Proton gaming FPS.

Safety guarantees:
  - Signature-anchored 36-byte lookup (refuses to patch unless matched uniquely once)
  - Automatic one-time backup of the untouched original module in /var/backups/
  - Supports raw .ko, .ko.xz (mandatory CRC32 check for Linux kernel), .ko.zst, .ko.gz
  - Preserves file mode, ownership, and SELinux context (when chcon/restorecon exist)
  - Atomic replacement + post-write read-back verification
  - Independent from PCIe Gen2 patches (touches only 10 bytes in .rodata)
"""
import argparse
import glob
import gzip
import hashlib
import lzma
import os
import shutil
import subprocess
import sys
import tempfile

# Anchored 36-byte signature in nvidia.ko .rodata:
#   8-byte prefix + 5 restricted P1XX SKU dwords (20 bytes) + 8-byte suffix
WL_PREFIX = bytes.fromhex("bf390000c2150700")
WL_ORIG   = bytes.fromhex("071b0700871b0700c71b0700071c0700091c0700")
WL_PATCH  = bytes.fromhex("ffff0700ffff0700ffff0700ffff0700ffff0700")
WL_SUFFIX = bytes.fromhex("831d0700841d0700")

ORIG_SIG  = WL_PREFIX + WL_ORIG + WL_SUFFIX
PATCH_SIG = WL_PREFIX + WL_PATCH + WL_SUFFIX


def find_nvidia_ko(explicit_path=None):
    if explicit_path:
        return explicit_path
    try:
        out = subprocess.check_output(["modinfo", "-n", "nvidia"], text=True, stderr=subprocess.DEVNULL).strip()
        if out and os.path.exists(out):
            return out
    except Exception:
        pass

    kver = os.uname().release
    patterns = [
        f"/lib/modules/{kver}/extra/nvidia*/nvidia.ko*",
        f"/lib/modules/{kver}/updates/dkms/nvidia.ko*",
        f"/lib/modules/{kver}/updates/nvidia*.ko*",
        f"/lib/modules/{kver}/extramodules/nvidia.ko*",
        f"/lib/modules/{kver}/kernel/drivers/video/nvidia.ko*",
        f"/usr/lib/modules/{kver}/extramodules/nvidia.ko*",
    ]
    for pat in patterns:
        for match in sorted(glob.glob(pat)):
            if os.path.isfile(match):
                return match
    return f"/lib/modules/{kver}/updates/dkms/nvidia.ko"


def backup_path_for(ko_path):
    kver = os.uname().release
    base = os.path.basename(ko_path)
    return f"/var/backups/remove-black-list-nvidia-linux/{kver}/{base}.orig"


def read_ko_bytes(ko_path):
    if ko_path.endswith(".xz"):
        with lzma.open(ko_path, "rb") as f:
            return bytearray(f.read()), "xz"
    if ko_path.endswith(".zst"):
        zstd_bin = shutil.which("zstd")
        if not zstd_bin:
            raise RuntimeError("Found .ko.zst module, but 'zstd' is not installed.")
        raw = subprocess.check_output([zstd_bin, "-d", "-c", "-q", ko_path])
        return bytearray(raw), "zst"
    if ko_path.endswith(".gz"):
        with gzip.open(ko_path, "rb") as f:
            return bytearray(f.read()), "gz"
    with open(ko_path, "rb") as f:
        return bytearray(f.read()), "raw"


def finalize_atomic_replace(tmp_file, target_path, st):
    os.chmod(tmp_file, st.st_mode & 0o7777)
    os.chown(tmp_file, st.st_uid, st.st_gid)
    if shutil.which("chcon"):
        subprocess.run(["chcon", "--reference", target_path, tmp_file],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.replace(tmp_file, target_path)
    if shutil.which("restorecon"):
        subprocess.run(["restorecon", target_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_ko_bytes_atomic(ko_path, data, fmt):
    ko_dir = os.path.dirname(os.path.abspath(ko_path))
    st = os.stat(ko_path)

    if fmt == "xz":
        fd_raw, tmp_raw = tempfile.mkstemp(prefix=".nvko_raw_", dir=ko_dir)
        tmp_out = tmp_raw + ".xz"
        try:
            with os.fdopen(fd_raw, "wb") as f:
                f.write(data)
            xz_bin = shutil.which("xz")
            if xz_bin:
                # Linux kernel XZ decompressor requires CRC32 (default xz uses CRC64!)
                subprocess.check_call([xz_bin, "-T0", "-6", "--check=crc32", "-f", tmp_raw])
                info = subprocess.check_output([xz_bin, "--list", tmp_out], text=True)
                if "CRC32" not in info:
                    raise RuntimeError(f"Compressed .xz does not use CRC32:\n{info}")
            else:
                with lzma.open(tmp_out, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=6) as f:
                    f.write(data)
                os.unlink(tmp_raw)
            finalize_atomic_replace(tmp_out, ko_path, st)
        except Exception:
            for p in (tmp_raw, tmp_out):
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            raise
    elif fmt == "zst":
        zstd_bin = shutil.which("zstd")
        if not zstd_bin:
            raise RuntimeError("'zstd' is required to recompress .ko.zst modules.")
        fd_raw, tmp_raw = tempfile.mkstemp(prefix=".nvko_raw_", dir=ko_dir)
        tmp_out = tmp_raw + ".zst"
        try:
            with os.fdopen(fd_raw, "wb") as f:
                f.write(data)
            subprocess.check_call([zstd_bin, "-T0", "-q", "-f", "-o", tmp_out, tmp_raw])
            os.unlink(tmp_raw)
            finalize_atomic_replace(tmp_out, ko_path, st)
        except Exception:
            for p in (tmp_raw, tmp_out):
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            raise
    elif fmt == "gz":
        fd_tmp, tmp_out = tempfile.mkstemp(prefix=".nvko_gz_", dir=ko_dir)
        try:
            with os.fdopen(fd_tmp, "wb") as raw_f:
                with gzip.GzipFile(fileobj=raw_f, mode="wb", compresslevel=6) as gz_f:
                    gz_f.write(data)
            finalize_atomic_replace(tmp_out, ko_path, st)
        except Exception:
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)
            raise
    else:
        fd_tmp, tmp_out = tempfile.mkstemp(prefix=".nvko_tmp_", dir=ko_dir)
        try:
            with os.fdopen(fd_tmp, "wb") as f:
                f.write(data)
            finalize_atomic_replace(tmp_out, ko_path, st)
        except Exception:
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)
            raise


def find_all(buf, needle):
    hits = []
    pos = 0
    while True:
        i = buf.find(needle, pos)
        if i == -1:
            break
        hits.append(i)
        pos = i + 1
    return hits


def inspect_state(data):
    orig_hits = find_all(data, ORIG_SIG)
    patched_hits = find_all(data, PATCH_SIG)
    if len(orig_hits) == 1 and len(patched_hits) == 0:
        return "ORIG", orig_hits[0]
    if len(orig_hits) == 0 and len(patched_hits) == 1:
        return "PATCHED", patched_hits[0]
    return "UNKNOWN", (orig_hits, patched_hits)


def ensure_backup(ko_path):
    bak = backup_path_for(ko_path)
    if os.path.exists(bak):
        print(f"  [Backup] Keeping existing original backup: {bak}")
        return bak
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(ko_path, bak)
    print(f"  [Backup] Saved original module -> {bak}")
    return bak


def sha256_short(b):
    return hashlib.sha256(b).hexdigest()[:16]


def check_dkms_hint():
    kver = os.uname().release
    dkms_hits = glob.glob(f"/var/lib/dkms/nvidia*/{kver}/*/module/nvidia.ko*")
    if dkms_hits:
        print("\n[Note] DKMS cache detected:")
        for p in dkms_hits:
            print(f"  - {p}")
        print("  If 'dkms install' runs later, it may overwrite /lib/modules from the DKMS cache.")
        print("  You can also patch the DKMS cached copy with: sudo python3 patch_nvidia_blacklist.py apply --ko <path>")


def main():
    ap = argparse.ArgumentParser(
        description="Remove NVIDIA Linux Restricted Mining-Card SKU table (P102/P104/P106) from nvidia.ko"
    )
    ap.add_argument("action", choices=["check", "apply", "revert", "restore-orig"],
                    help="Action to perform")
    ap.add_argument("--ko", default=None,
                    help="Optional explicit path to nvidia.ko / .ko.xz / .ko.zst / .ko.gz")
    args = ap.parse_args()

    ko_path = find_nvidia_ko(args.ko)
    if not os.path.exists(ko_path):
        print(f"[ERROR] NVIDIA kernel module not found: {ko_path}", file=sys.stderr)
        print("        Pass --ko /path/to/nvidia.ko(.xz/.zst/.gz) if installed in a custom path.", file=sys.stderr)
        return 1

    bak = backup_path_for(ko_path)

    if args.action == "restore-orig":
        if os.geteuid() != 0:
            print("[ERROR] Root privileges (sudo) required for restore-orig.", file=sys.stderr)
            return 1
        if not os.path.exists(bak):
            print(f"[ERROR] Backup file not found: {bak}", file=sys.stderr)
            return 1
        st = os.stat(ko_path)
        tmp_path = ko_path + ".restore_tmp"
        shutil.copy2(bak, tmp_path)
        finalize_atomic_replace(tmp_path, ko_path, st)
        print(f"[OK] Restored original module {ko_path} from {bak}")
        print("Reboot to load the restored module (rebuild initramfs if your distro embeds nvidia.ko in initramfs).")
        return 0

    print(f"Module : {ko_path}")
    print(f"Backup : {bak} ({'present' if os.path.exists(bak) else 'not created yet'})")
    data, fmt = read_ko_bytes(ko_path)
    print(f"Size   : {len(data):,} bytes (uncompressed) | sha256={sha256_short(data)}... | format={fmt}")
    print()

    state, info = inspect_state(data)

    if args.action == "check":
        if state == "ORIG":
            print(f"[STATUS] UNPATCHED (ORIG) @ offset 0x{info:x}")
            print("         Restricted SKU entries active: P102-100(1B07), P104-100(1B87), P104-101(1BC7), P106-100(1C07), P106-090(1C09)")
            return 0
        if state == "PATCHED":
            print(f"[STATUS] PATCHED @ offset 0x{info:x}")
            print("         All 5 restricted P1XX SKU entries replaced with sentinel 0x0007FFFF.")
            return 0
        print(f"[STATUS] SIGNATURE NOT FOUND (orig_hits={info[0]}, patched_hits={info[1]})", file=sys.stderr)
        print("         This driver build/branch may use a different table layout or open kernel modules (nvidia-open).", file=sys.stderr)
        return 2

    if os.geteuid() != 0:
        print(f"[ERROR] Root privileges (sudo) required for '{args.action}'.", file=sys.stderr)
        return 1

    if args.action == "apply":
        if state == "PATCHED":
            print(f"[OK] Already patched @ offset 0x{info:x}. No changes needed.")
            return 0
        if state != "ORIG":
            print(f"[ERROR] Could not uniquely locate signature (orig={info[0]}, patched={info[1]}). Aborting safely!", file=sys.stderr)
            return 2
        ensure_backup(ko_path)
        data[info:info + len(PATCH_SIG)] = PATCH_SIG
        print(f"  -> Patched 5 restricted SKU entries @ offset 0x{info:x} (0x0007{{1b07,1b87,1bc7,1c07,1c09}} -> 0x0007ffff)")
        expected = "PATCHED"
    else:  # revert
        if state == "ORIG":
            print(f"[OK] Module is already in original (unpatched) state @ offset 0x{info:x}.")
            return 0
        if state != "PATCHED":
            print(f"[ERROR] Module does not match patched signature (orig={info[0]}, patched={info[1]}). Use restore-orig if needed.", file=sys.stderr)
            return 2
        data[info:info + len(ORIG_SIG)] = ORIG_SIG
        print(f"  -> Reverted 5 restricted SKU entries @ offset 0x{info:x}")
        expected = "ORIG"

    print(f"\nWriting ({fmt}) atomically to {ko_path} ...")
    write_ko_bytes_atomic(ko_path, data, fmt)

    verify_data, _ = read_ko_bytes(ko_path)
    st_after, off_after = inspect_state(verify_data)
    if st_after != expected:
        print(f"[CRITICAL] Post-write verification failed: expected {expected}, got {st_after}", file=sys.stderr)
        return 3

    print(f"[VERIFIED] state={st_after} @ offset 0x{off_after:x} | sha256={sha256_short(verify_data)}...")
    check_dkms_hint()
    print("\n[SUCCESS] Reboot to load the updated nvidia kernel module.")
    print("          Note: If your distro includes nvidia in initramfs (e.g., Ubuntu/Debian/Arch with early KMS),")
    print("                rebuild initramfs first (update-initramfs -u / mkinitcpio -P / dracut --regenerate-all --force).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
