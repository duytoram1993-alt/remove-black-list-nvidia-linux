[English](README.md) | [Tiếng Việt](README.vi.md)

# remove-black-list-nvidia-linux

Gỡ **bảng giới hạn card đào (Restricted SKU Table)** trong driver NVIDIA độc quyền trên Linux (`nvidia.ko`), loại bỏ lệnh trễ nhân tạo `~218 µs/batch` của `gr3d` khiến các card mining Pascal (P106-100, P106-090, P104-100, P104-101, P102-100) bị kẹt hiệu năng ~15–45 FPS khi chơi game hoặc chạy ứng dụng 3D/OpenGL/Vulkan.

> **Độc lập hoàn toàn với việc mở khóa PCIe Gen2:** Công cụ này **không** ghi thanh ghi BAR0, **không** nạp thêm kernel module ngoài, và chạy hoàn toàn riêng lẻ. Nếu bạn muốn mở khóa thêm PCIe Gen2 (`5.0 GT/s`) cho P106-100, xem repo đi kèm: [unlock-pcie-p106-100-linux](https://github.com/duytoram1993-alt/unlock-pcie-p106-100-linux).

---

## Nguyên nhân khiến P106 / P104 / P102 tụt FPS nặng trên Linux

Driver NVIDIA độc quyền (`nvidia.ko`) chứa sẵn một bảng 5 Device ID card đào trong vùng `.rodata`:

| PCI Device ID | Tên card |
|---|---|
| `10DE:1B07` | NVIDIA P102-100 |
| `10DE:1B87` | NVIDIA P104-100 |
| `10DE:1BC7` | NVIDIA P104-101 |
| `10DE:1C07` | NVIDIA P106-100 |
| `10DE:1C09` | NVIDIA P106-090 |

Khi gặp 1 trong 5 ID này, driver tự chèn lệnh delay `~218 µs` vào mỗi batch vẽ `gr3d` (`method 0x3998 = 0xF0`), làm hiệu năng 3D thực tế giảm **3–4 lần** dù xung nhịp GPU vẫn bình thường.

Script sẽ đổi 5 mục này (`0x0007{1B07,1B87,1BC7,1C07,1C09}`) thành giá trị rỗng `0x0007FFFF` (**chỉ sửa đúng 10 byte**, định vị bằng chữ ký 36 byte có neo đầu-cuối, không phụ thuộc offset cứng).

---

## Kết quả kiểm chứng thực tế

Đã test trên **Fedora 45 KDE Plasma** (kernel `7.3.3-300.fc45.x86_64`, driver `akmod-nvidia-580xx 580.196.07`, Gigabyte **P106-100 `10DE:1C07`**, Intel Core i7-3770K + iGPU HD 4000 PRIME offload):

- **Tomb Raider (2013), 1080p Normal (Proton Experimental):**
  - Trước khi patch: `low 15 FPS / trung bình 32 FPS / cao nhất 44 FPS`
  - Sau khi patch: **vượt `100 FPS`** (tắt VSync)

---

## Distro & định dạng hỗ trợ

Hỗ trợ mọi bản phân phối Linux dùng driver NVIDIA **độc quyền (proprietary/closed)**:
- **Fedora / RHEL / Nobara** (`.ko.xz` — tự nén lại bằng `xz --check=crc32` đúng chuẩn kernel Linux, giữ nguyên nhãn SELinux qua `chcon`/`restorecon`)
- **Arch / CachyOS / Manjaro / openSUSE** (`.ko.zst` — cần gói `zstd`)
- **Debian / Ubuntu / Linux Mint / Pop!_OS** (`.ko` không nén hoặc `.ko.zst` / `.ko.gz`)

> **Yêu cầu:**
> - Dùng driver NVIDIA **proprietary (closed)** (dòng Pascal không hỗ trợ `nvidia-open`).
> - **Tắt Secure Boot** (sửa `nvidia.ko` sẽ làm mất chữ ký số gốc; hoặc bạn cần tự ký lại bằng khóa MOK).
> - Python 3 có sẵn trên hệ thống (không cần cài thêm thư viện ngoài).

---

## Hướng dẫn nhanh

```bash
git clone https://github.com/duytoram1993-alt/remove-black-list-nvidia-linux.git
cd remove-black-list-nvidia-linux

# 1. Kiểm tra chỉ đọc (an toàn, không sửa file)
bash remove-blacklist.sh check

# 2. Tự động sao lưu bản gốc và áp patch
sudo bash remove-blacklist.sh apply

# 3. Khởi động lại máy để nạp nvidia.ko mới
sudo reboot
```

### Chỉ định đường dẫn module thủ công (tùy chọn)

Nếu muốn patch cho một phiên bản kernel khác hoặc bản cache DKMS:

```bash
sudo bash remove-blacklist.sh apply --ko /lib/modules/<phien-ban-kernel>/updates/dkms/nvidia.ko
```

### Lưu ý về Initramfs & cập nhật hệ thống

- **Nếu distro nhúng `nvidia.ko` vào initramfs** (thường gặp trên Ubuntu/Debian/Arch bật early KMS), hãy tạo lại initramfs trước khi reboot:
  - Debian / Ubuntu: `sudo update-initramfs -u`
  - Arch: `sudo mkinitcpio -P`
  - Fedora / RHEL *(thường không nhúng `nvidia` trong initramfs)*: chỉ cần chạy `sudo dracut --regenerate-all --force` nếu `lsinitrd | grep nvidia.ko` có kết quả.
- **Khi cập nhật kernel hoặc driver NVIDIA:** File `nvidia.ko` mới sẽ trở về bản gốc, bạn chỉ cần chạy lại `sudo bash remove-blacklist.sh apply` rồi reboot (hoặc dùng `dnf versionlock` / `apt-mark hold` khóa bản driver nếu không muốn cập nhật).

---

## Hoàn tác / Khôi phục bản gốc

```bash
# Hoàn tác riêng 10 byte của patch blacklist (không ảnh hưởng patch khác nếu có)
sudo bash remove-blacklist.sh revert

# Hoặc khôi phục nguyên bản file .orig từ /var/backups/
sudo bash remove-blacklist.sh restore-orig
```

Sau đó khởi động lại máy.

---

## Cơ chế an toàn

1. **Khớp chữ ký duy nhất:** Từ chối ghi nếu chuỗi chữ ký 36 byte không khớp **đúng 1 vị trí duy nhất**.
2. **Sao lưu tự động 1 lần:** Lưu file gốc tại `/var/backups/remove-black-list-nvidia-linux/<kernel>/nvidia.ko*.orig` trước khi sửa.
3. **Chuẩn nén XZ CRC32:** Bắt buộc dùng `--check=crc32` và kiểm tra header sau khi nén (kernel Linux không nạp được `.ko.xz` nén CRC64 mặc định).
4. **Ghi nguyên tử & đọc lại kiểm chứng:** Ghi ra file tạm cùng thư mục, giữ quyền/chủ sở hữu/SELinux context, đổi tên nguyên tử và đọc lại từ đĩa để xác nhận.

---

## Nguồn tham khảo & miễn trừ trách nhiệm

- Cơ chế bảng Restricted SKU được tham khảo từ dự án: [WJNKAC/nvidia-p104-unlock-gen2-for-linux](https://github.com/WJNKAC/nvidia-p104-unlock-gen2-for-linux)
- Phát hành theo giấy phép [MIT License](LICENSE). Việc sửa đổi driver nhị phân tiềm ẩn rủi ro; người dùng tự chịu trách nhiệm và nên giữ bản sao lưu.
