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

### `dwauto/screen.py` — chụp màn hình + nhận diện nút

```python
from dwauto import Screen, find_template

with Screen(area={"left": 100, "top": 80, "width": 900, "height": 1600}) as sc:
    m = sc.find("templates/search_button.png", threshold=0.85)
    if m:
        print(m.x, m.y, m.score)      # tâm vùng khớp, theo PIXEL của ảnh chụp
        print(sc.to_mouse(m.x, m.y))  # → toạ độ chuột để pyautogui click

    # chờ popup "under attack" trong một vùng nhất định
    sc.wait_for("templates/under_attack.png", timeout=180, interval=1.0,
                region=(200, 100, 700, 400))
```

Lưu ý toạ độ: `find/wait_for` trả **pixel của ảnh chụp**; trên Retina hoặc Windows
scaling >100% con số này **không phải** toạ độ chuột — luôn đi qua `to_mouse()` trước
khi click. `Screen.scale` được đo lại ở mỗi `capture()`.

### Hai nguồn ảnh (`capture.backend`)

| | `adb` (mặc định) | `screen` |
|---|---|---|
| Cửa sổ giả lập để **đâu** trên màn hình | chạy | phải khai `region` cố định |
| Cửa sổ **đổi kích thước** | chạy | chết |
| Cửa sổ bị che một phần | vẫn *nhìn* được | chết |
| Quyền Screen Recording (macOS) | **không cần** | cần |
| Tốc độ mỗi ảnh | ~0.7s | ~0.05s |

`adb` chụp thẳng từ Android nên ảnh luôn cùng độ phân giải, không phụ thuộc cửa sổ.
Vị trí cửa sổ chỉ dùng lúc **click**, và được dò lại mỗi lần — kéo cửa sổ đi giữa
chừng vẫn đúng.

**Giới hạn đã đo trên BlueStacks Air 5.21.770 (macOS):** adbd của nó là bản shim, chỉ
chạy `getprop`, `dumpsys`, `screencap`. `input tap` bị chặn (`error: closed`), nên
click vẫn phải qua chuột thật → **cửa sổ vẫn phải hiện ra và không bị che lúc click**.
Chạy hoàn toàn ẩn cần emulator không khoá ADB shell (BlueStacks trên Windows, hoặc
giả lập khác).

### Chạy tool

```bash
python main.py --dry-run    # chỉ báo thấy nút gì, ở đâu — KHÔNG click
python main.py              # F8 chạy/dừng, Esc thoát
```

Chu trình (đo từ bản ghi thật, **không có bước chọn team** — game tự lấy đội quân rảnh):

```
world map ──search_button──▶ panel Rally ──search_confirm──▶ popup mục tiêu
          ──rally_button──▶ panel March ──march_button──▶ world map
```

Chạy `rally.marches_per_round` lượt liên tiếp (mặc định 3, cho 3 đội quân) rồi chờ
`rally.wait_minutes` phút và lặp lại. **`wait_minutes` mặc định là 5 — chỉnh trong
`config.yaml` cho khớp thời gian rally của bạn.**

Sau mỗi click, tool **kiểm chứng** màn hình kế tiếp đã hiện chưa; chưa thì click lại
(tối đa `timing.retries` lần). Nhờ vậy chịu được click bị macOS nuốt khi BlueStacks
chưa được focus — lỗi này có thật, gặp ngay lúc ghi. Hỏng 2 lượt liên tiếp thì bỏ vòng
và chờ tới vòng sau, không click vô ích vào game đang kẹt.

Dừng khẩn cấp: kéo chuột lên **góc trên-trái màn hình** (pyautogui FAILSAFE), hoặc `Esc`.

**Cửa sổ giả lập phải nằm trên cùng và không bị che** — `mss` chụp theo màn hình, cửa
sổ nào đè lên là chụp trúng cửa sổ đó.

## Test

```bash
pytest              # 65 test, chạy bằng ảnh tổng hợp + game giả, không cần màn hình
```
