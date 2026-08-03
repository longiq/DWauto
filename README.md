# DWauto

Tool auto rally cho **Darkwar Survival** — chỉ giả lập input chuột, không can thiệp
API/bộ nhớ game. Xem [SPEC.md](SPEC.md).

Hỗ trợ hai môi trường:

1. **macOS + BlueStacks**
2. **Windows + app/giả lập của game**

## Cài đặt

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Quyền trên macOS (bắt buộc)

System Settings → Privacy & Security, cấp cho **Terminal** (hoặc iTerm/VS Code — app
nào đang chạy python):

- **Screen Recording** — để `mss` chụp được cửa sổ BlueStacks (không cấp thì ảnh chụp
  chỉ có hình nền, không có game).
- **Accessibility** — để `pynput` bắt được click và phím tắt.

Cấp xong phải **thoát hẳn và mở lại** Terminal.

Nếu `F8`/`F9` không ăn (macOS chiếm làm phím media), bật *Keyboard → "Use F1, F2, etc.
keys as standard function keys"*, hoặc đổi phím: `--start-key f7 --snap-key f6`.

## Giai đoạn 1 — Ghi thao tác (`recorder.py`)

```bash
python recorder.py
```

Phím tắt:

| Phím | Tác dụng |
| --- | --- |
| `F8` | bật/tắt ghi |
| `F9` | chụp 1 frame không kèm click (dùng khi popup **"target under attack"** hiện) |
| `Esc` | thoát |

Thao tác **đúng một chu trình rally đầy đủ**: Search → chọn team → March → chờ
"under attack" (nhấn `F9` lúc popup hiện).

### Chỉ chụp cửa sổ giả lập (khuyến nghị)

Chụp cả màn hình thì template dính cả desktop. Đo toạ độ cửa sổ bằng chuột:

```bash
python recorder.py --pick-region     # đưa chuột tới 2 góc cửa sổ, mỗi góc nhấn F9
# → in ra: python recorder.py --region 100,80,900,1600
```

Rồi ghi với vùng đó:

```bash
python recorder.py --region 100,80,900,1600
```

### Tuỳ chọn khác

```bash
python recorder.py --out recordings --crop 120x60 --monitor 1
```

- `--crop WxH` — ô cắt quanh con trỏ, **tính theo toạ độ chuột** (mặc định `120x60`);
  trên màn Retina sẽ tự nhân đôi thành 240×120 pixel thật.
- `--monitor N` — chỉ số monitor của `mss` (`1` = màn hình chính, `0` = toàn bộ desktop).
- `--start-key / --snap-key / --quit-key` — đổi phím tắt.

### Retina & DPI scaling

`pynput` trả toạ độ **logic** còn `mss` chụp ra **pixel vật lý**: trên Retina (macOS)
hay Windows scaling >100% hai hệ này lệch nhau. Recorder đo tỉ lệ ngay lúc chạy
(kích thước ảnh ÷ kích thước vùng chụp) và in ra khi khác 1.0. Mỗi sự kiện lưu cả hai:

- `x_abs, y_abs` — toạ độ chuột (dùng để click lại ở giai đoạn 3),
- `x, y` — toạ độ pixel trong ảnh (dùng để cắt/khớp template).

`scale` cũng được ghi ở đầu `clicks.json` để giai đoạn 3 quy đổi vị trí khớp template
ngược về toạ độ chuột.

### Output

```
recordings/
├── clicks.json        # platform, capture_area, scale + danh sách sự kiện (ghi lại sau mỗi sự kiện)
├── frames/frame_000.png ...
└── crops/crop_000.png ...   # ảnh mẫu ứng viên
```

Mỗi sự kiện có `label: null` — giai đoạn 2 (chuẩn hoá) sẽ gán nhãn (`search_button`,
`team1/2/3`, `march_button`, `under_attack`) và sinh `config.yaml`.

**Lưu ý:** giữ kích thước/độ phân giải cửa sổ giả lập cố định; đổi thì phải ghi lại
template. Template ghi trên BlueStacks macOS **không dùng lại được** cho Windows và
ngược lại — mỗi máy ghi một bộ riêng (`--out recordings_mac`, `--out recordings_win`).

## Giai đoạn 3 — Chạy auto

Chưa triển khai (`main.py`, `dwauto/`).
