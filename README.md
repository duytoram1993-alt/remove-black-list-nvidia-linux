[English](README.md) | [Tiếng Việt](README.vi.md)

# remove-black-list-nvidia-linux

Remove the **Restricted Mining-Card SKU table** from the proprietary NVIDIA Linux kernel driver (`nvidia.ko`), eliminating the artificial `~218 µs/batch` 3D graphics delay that throttles Pascal mining cards (P106-100, P106-090, P104-100, P104-101, P102-100) to ~15–45 FPS in games and OpenGL/Vulkan apps.

> **Completely independent of PCIe speed unlocking:** This tool **does not** touch PCIe BAR0 registers, does **not** load any extra kernel module, and works standalone. If you also want PCIe Gen2 (`5.0 GT/s`) on P106-100, see the separate companion repository: [unlock-pcie-p106-100-linux](https://github.com/duytoram1993-alt/unlock-pcie-p106-100-linux).

---

## Why is gaming FPS so low on P106 / P104 / P102 on Linux?

The proprietary NVIDIA Linux driver (`nvidia.ko`) contains a 5-entry restricted SKU lookup table in `.rodata`:

| PCI Device ID | GPU Model |
|---|---|
| `10DE:1B07` | NVIDIA P102-100 |
| `10DE:1B87` | NVIDIA P104-100 |
| `10DE:1BC7` | NVIDIA P104-101 |
| `10DE:1C07` | NVIDIA P106-100 |
| `10DE:1C09` | NVIDIA P106-090 |

When the driver detects one of these IDs, it automatically inserts a `~218 µs` delay per `gr3d` batch (`method 0x3998 = 0xF0`), cutting real-world 3D/game performance by **3×–4×** even when GPU utilization and clocks look normal.

This patch replaces the 5 IDs in that table (`0x0007{1B07,1B87,1BC7,1C07,1C09}`) with the sentinel `0x0007FFFF` (**10 bytes total**, located via an anchored 36-byte signature so it does not rely on hardcoded offsets).

---

## Real-World Verified Result

Tested on **Fedora 45 KDE Plasma** (kernel `7.3.3-300.fc45.x86_64`, proprietary driver `akmod-nvidia-580xx 580.196.07`, Gigabyte **P106-100 `10DE:1C07`**, Intel Core i7-3770K + HD 4000 PRIME offload):

- **Tomb Raider (2013), 1080p Normal (Proton Experimental):**
  - Before patch: `low 15 FPS / avg 32 FPS / high 44 FPS`
  - After patch: **`>100 FPS`** (VSync off)

---

## Supported Distros & Formats

Works on any Linux distribution using the **proprietary** (`closed`) NVIDIA kernel module:
- **Fedora / RHEL / Nobara** (`.ko.xz` — automatically recompressed with `xz --check=crc32` as required by the Linux kernel, preserving SELinux context via `chcon`/`restorecon`)
- **Arch / CachyOS / Manjaro / openSUSE** (`.ko.zst` — requires `zstd`)
- **Debian / Ubuntu / Linux Mint / Pop!_OS** (`.ko` uncompressed or `.ko.zst` / `.ko.gz`)

> **Requirements:**
> - **Proprietary (`closed`) NVIDIA driver** (Pascal GPUs are not supported by `nvidia-open`).
> - **Secure Boot disabled** (modifying `nvidia.ko` invalidates any module signature; alternatively re-sign the module with your MOK key).
> - Python 3 (standard library only — no `pip` packages needed).

---

## Quick Start

```bash
git clone https://github.com/duytoram1993-alt/remove-black-list-nvidia-linux.git
cd remove-black-list-nvidia-linux

# 1. Read-only check (safe, modifies nothing)
bash remove-blacklist.sh check

# 2. Backup original module & apply patch
sudo bash remove-blacklist.sh apply

# 3. Reboot to load the patched nvidia kernel module
sudo reboot
```

### Custom module path (optional)

If `modinfo -n nvidia` does not point to your target module (for example, patching a non-running kernel or DKMS cache):

```bash
sudo bash remove-blacklist.sh apply --ko /lib/modules/<kernel-version>/updates/dkms/nvidia.ko
```

### Initramfs & DKMS Notes

- **If your distro embeds `nvidia.ko` inside initramfs** (common on Ubuntu/Debian/Arch with early KMS): rebuild initramfs before rebooting:
  - Debian / Ubuntu: `sudo update-initramfs -u`
  - Arch: `sudo mkinitcpio -P`
  - Fedora / RHEL *(usually excludes `nvidia` from initramfs by default)*: only needed if `lsinitrd | grep nvidia.ko` shows it (`sudo dracut --regenerate-all --force`).
- **Kernel or driver upgrades:** Upgrading the kernel or NVIDIA driver rebuilds `nvidia.ko` cleanly, which removes the patch. Simply re-run `sudo bash remove-blacklist.sh apply` and reboot.

---

## Revert / Rollback

```bash
# Revert only the 10-byte blacklist patch (keeps any other patches intact)
sudo bash remove-blacklist.sh revert

# Or restore the exact untouched original backup from /var/backups/
sudo bash remove-blacklist.sh restore-orig
```

Then reboot (and rebuild initramfs if applicable).

---

## Safety Mechanisms

1. **Exact unique signature match:** Refuses to modify the file unless the full 36-byte anchored signature matches **exactly once**.
2. **One-time original backup:** Automatically saved to `/var/backups/remove-black-list-nvidia-linux/<kernel>/nvidia.ko*.orig` before the first write.
3. **Kernel-safe XZ CRC32:** Explicitly passes `--check=crc32` and verifies the compressed header (Linux's in-kernel XZ decoder rejects default CRC64 `.ko.xz` modules).
4. **Atomic replacement & post-write verification:** Writes to a temp file in the same directory, preserves permissions/owner/SELinux labels, atomically swaps, and reads the file back from disk to verify.

---

## Credits & Disclaimer

- Restricted SKU table discovery and reverse-engineering reference: [WJNKAC/nvidia-p104-unlock-gen2-for-linux](https://github.com/WJNKAC/nvidia-p104-unlock-gen2-for-linux)
- Provided **as-is** under the [MIT License](LICENSE). Modifying binary kernel drivers is done at your own risk; always keep a backup or a fallback boot entry.
