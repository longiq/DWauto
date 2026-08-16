# Spec: DWauto — tool auto rally cho Darkwar Survival

> Tài liệu bàn giao. Mục tiêu "chạy nền hoàn toàn" đã đạt được trên macOS qua
> MuMu Player — không cần đường Windows nữa (xem cập nhật 16/08/2026 cuối file).
> Cập nhật 05/08/2026.

## Tình trạng hiện tại

| Hạng mục | Trạng thái |
|---|---|
| Ghi thao tác (`recorder.py`) | xong, chạy được macOS + Windows |
| Nhận diện nút (`dwauto/screen.py`) | xong, 67 test |
| Chụp qua ADB (`dwauto/adb.py`) | xong, verify trên BlueStacks Air + MuMu Player |
| Vòng lặp rally (`dwauto/rally.py`) | xong, **3/3 lượt thật thành công** |
| App GUI (`app.py`) + đóng gói (`build.py`) | xong, `dist/DWauto.app` 62MB nén |
| Click qua ADB (chạy nền hoàn toàn) | **xong trên MuMu Player (16/08/2026) — xem cuối file** |

## Chu trình rally (đo từ bản ghi thật, KHÔNG theo phỏng đoán ban đầu)

```
world map ──search_button──▶ panel Rally ──search_confirm──▶ popup mục tiêu
          ──rally_button──▶ panel March ──march_button──▶ world map
```

Khác spec gốc ở hai chỗ, đã xác nhận với người dùng:

- **Không có bước chọn team.** Game tự lấy đội quân rảnh. Thay vào đó chạy
  `marches_per_round` lượt liên tiếp (mặc định 3, cho 3 đội quân).
- **Không giám sát "target under attack".** Thay bằng: xong 3 lượt thì chờ
  `wait_minutes` phút rồi lặp lại.

Mỗi bước đều **kiểm chứng được**: sau click phải thấy màn hình kế tiếp, không thấy thì
click lại (`timing.retries`). Riêng bước March xác nhận bằng **panel March đóng lại**,
không phải "world map hiện ra" — vì game chạy animation bay tới điểm tập kết, bản đầu
bắt chờ world map nên báo hỏng oan.

## Kiến trúc

```
recorder.py      ghi click + screenshot + tự cắt template ứng viên
app.py           GUI: Cycle / [số phút] / Start-Stop   ← thứ đem chia sẻ
main.py          CLI: --dry-run, --marches N, phím tắt F8/Esc
build.py         PyInstaller → dist/DWauto.app (hoặc dist/DWauto/ trên Windows)
dwauto/
  config.py      đọc/kiểm config.yaml, ngưỡng riêng theo từng nút
  screen.py      template matching thuần (test được, không cần màn hình)
  adb.py         AdbScreen: chụp qua ADB, quy đổi toạ độ
  window.py      dò + focus cửa sổ giả lập (Quartz / pygetwindow)
  actions.py     click qua pyautogui, offset + delay ngẫu nhiên
  rally.py       state machine
```

**Hai nguồn ảnh** (`capture.backend`): `adb` (mặc định) và `screen`. Backend `adb`
chụp thẳng từ Android nên ảnh luôn 1080×1920, không phụ thuộc cửa sổ — cửa sổ để đâu,
to nhỏ thế nào, bị che một phần cũng nhìn được, và không cần quyền Screen Recording.

**Quy đổi toạ độ** (đã kiểm chứng tới 1px): ảnh ADB co về `template_width` (506) để
khớp template, rồi map sang màn hình qua vùng game thật trong cửa sổ. Vùng game suy từ
tỉ lệ Android: chiếm trọn bề ngang cửa sổ, sát đáy, phần thừa phía trên là thanh tiêu đề.
Vị trí cửa sổ dò lại **mỗi lần click** nên kéo/resize giữa chừng vẫn đúng.

## Việc của phiên Windows

### 1. Kiểm chứng ADB shell TRƯỚC KHI viết code

Đây là điều kiện sống-còn. Trên **BlueStacks Air / macOS** đã đo được: adbd là bản shim,
chỉ chạy `getprop`, `dumpsys`, `screencap`; mọi thứ khác trả `error: closed`.

```bat
adb connect 127.0.0.1:5555
adb -s 127.0.0.1:5555 shell input tap 100 100
```

- **Chạy được** → làm tiếp bước 2, đạt được mục tiêu chạy nền hoàn toàn.
- **`error: closed`** → Windows cũng bị khoá như macOS; dừng, báo người dùng, không
  có đường vòng nào khác (xem "Những đường đã thử và thất bại").

Bật ADB: BlueStacks 5 → Settings → Advanced → *Android Debug Bridge*. Multi-instance thì
mỗi instance một cổng riêng (5555, 5565, 5575…) → `capture.adb_port: 0` để tự dò.

### 2. Nếu `input tap` chạy: thêm backend click qua ADB

Chỗ này là toàn bộ giá trị của bản Windows — **cửa sổ thu nhỏ / bị che vẫn auto được,
không chiếm chuột, không cần cấp quyền gì.**

- `dwauto/actions.py`: thêm `AdbMouse` cùng giao diện `Mouse.click(x, y, label)`,
  gửi `input tap` qua `adb_shell` (`device.exec_out`). Giữ offset ngẫu nhiên.
- `dwauto/adb.py`: thêm `to_device(x, y)` đổi toạ độ ảnh template → **toạ độ Android**
  (nhân `raw_w / template_width`). `AdbMouse` dùng cái này, không dùng `to_mouse`.
- `dwauto/rally.py`: chọn `to_device` hay `to_mouse` theo loại mouse đang dùng.
- `config.yaml`: thêm `click.backend: adb | mouse`, mặc định tự dò —
  thử `input tap` một lần lúc khởi động, không được thì rơi về chuột.
- Khi dùng `AdbMouse` thì **bỏ luôn** `focus_window()` (không cần cửa sổ nữa).

### 3. Ghi lại template trên máy Windows

Template hiện tại cắt từ game **của người dùng trên BlueStacks Air**. Sang máy khác gần
như chắc chắn phải cắt lại: khác độ phân giải Android, khác ngôn ngữ game, khác quái đã
chọn sẵn trong panel Search.

```bat
python recorder.py --pick-region        REM đo cửa sổ
python recorder.py --region x,y,w,h --out recordings_win
```

Ghi đúng **một** chu trình: Search → Search (trong panel) → Rally → March. Rồi gán nhãn
4 crop thành `templates/*.png`.

**Kinh nghiệm đã trả giá khi cắt template:** `search_button` (kính lúp) **vẽ đè thẳng lên
bản đồ, không có nền riêng**. Cắt rộng thì dính nền, chat trong game chạy qua là điểm rớt
từ 0.99 xuống 0.62 và tool mù. Phải cắt **sát riêng hình icon** (28×28) và cho ngưỡng
riêng trong `match.thresholds`. Luôn kiểm bằng ma trận: mỗi template phải ăn cao trên
frame của nó và thấp trên mọi frame khác, ngưỡng nằm giữa khoảng trống.

### 4. Đóng gói .exe

```bat
python build.py
```

Không build chéo được: `.exe` phải build trên Windows. Windows không cần quyền
Accessibility như macOS, nhưng SmartScreen sẽ cảnh báo app không ký số.

## Những đường đã thử và THẤT BẠI (đừng thử lại)

Đo trên BlueStacks Air 5.21.770, macOS 26.5.2, Android 13 arm64, `ro.secure=0`,
`ro.debuggable=1`. Dùng cả `adb-shell` (Python) lẫn client `adb` chính chủ của Google:

| Đường | Kết quả |
|---|---|
| `adb shell input tap` (cả `-T`, `-t`, `-x`) | `error: closed` |
| `adb exec-out input tap` | treo / `error: closed` |
| `app_process` gọi thẳng lớp Input (đúng thứ script `input` làm) | `error: closed` |
| `getevent` / `sendevent` (bơm sự kiện mức kernel) | `error: closed` |
| `adb root` | `unable to connect for root: closed` |
| `screencap` ra file rồi `adb pull` | sync protocol không tương thích (`recv_v1`) |
| `CGEventPostToPid` bơm chuột thẳng vào tiến trình | app phớt lờ |
| `CGEventPostToPid` + `clickState` + mouseMoved | app phớt lờ |
| Đưa BlueStacks sang Space khác rồi click | **không được, và nguy hiểm** — macOS định tuyến sự kiện theo vị trí trên Space đang hoạt động, click sẽ rơi vào cửa sổ người dùng đang làm việc |

Chỉ `getprop`, `dumpsys`, `screencap` là chạy.

## Giới hạn còn lại

- **macOS**: lúc click vẫn cần cửa sổ hiện ra và không bị che. Chạy nền hoàn toàn phải
  chờ đường Windows, hoặc giả lập khác không khoá ADB shell (chưa thử MuMu Player).
- **Template phụ thuộc người dùng**: ngôn ngữ game, độ phân giải, quái chọn sẵn.
  Bạn bè dùng cấu hình khác thì phải ghi lại template — chưa có cách tự động.
- **App chưa ký số**: macOS phải chuột phải → Open; cần Apple Developer ID (99$/năm)
  mới mở thẳng được.
- **Chỉ Apple Silicon**: bundle build trên M4 không chạy trên Mac Intel.

## Môi trường đã dùng (macOS)

- Python **3.12** + Tk **9.0** (`brew install python-tk@3.12`).
  **Không dùng Python 3.9 hệ thống**: Tk 8.5 của nó vỡ trên macOS 26 — `tk.Label` và
  toàn bộ widget `ttk` không vẽ ra, cửa sổ đen trơn.
- `opencv-python-headless` (không dùng hàm GUI của OpenCV; nhẹ hơn ~95MB khi đóng gói).
- `adb-shell` — client ADB thuần Python, không cần cài `adb` binary.

## Kiểm chứng

```bash
pytest                      # 67 test, ảnh tổng hợp + game giả, không cần màn hình
python main.py --dry-run    # báo thấy nút gì, ở đâu, sẽ click chỗ nào — không click
python main.py --marches 1  # chạy thật đúng một lượt
```

## Cập nhật 16/08/2026 — MuMu Player: đạt "chạy nền hoàn toàn" trên macOS, bỏ đường Windows

Test trực tiếp `adb shell input tap` trên **MuMu Player** (không phải BlueStacks) —
**chạy được**, không bị `error: closed` như BlueStacks Air. Xác nhận bằng UI thật
đổi màn hình sau tap, không chỉ exit code 0.

**AdbMouse đã hiện thực** (đúng việc mà mục "Việc của phiên Windows" ở trên định làm
cho Windows, giờ làm luôn trên macOS):

- `dwauto/actions.py`: thêm `AdbMouse` — cùng giao diện `click(x, y, label)` với
  `Mouse`, nhưng gọi `adb shell input tap` qua subprocess (không dùng `adb_shell`
  Python, xem lý do bên dưới). Có `uses_device_coords = True` để `rally.py` phân biệt.
- `dwauto/adb.py`: thêm `AdbScreen.to_device(x, y)` — quy đổi toạ độ template sang
  toạ độ Android thật, không cần dò cửa sổ (khác `to_mouse`).
- `dwauto/rally.py`: `do_step()` chọn `to_device` hay `to_mouse` theo
  `getattr(self.mouse, "uses_device_coords", False)`.
- `config.yaml`: `click.backend: adb` (mặc định mới). `mouse` vẫn còn cho BlueStacks
  Air hoặc máy nào ADB bị khoá.
- `main.py`: khi `click.backend == adb`, bỏ hẳn `focus_window()` (`focus()` trả
  `True` ngay) — verify chạy đúng **khi cửa sổ MuMu đã thu nhỏ hoàn toàn**.

**Bug thư viện `adb_shell` (Python thuần) với MuMu — ĐỪNG dùng lại `device.exec_out`
trực tiếp cho MuMu:** `grab_raw()` gốc dùng `adb_shell.AdbDeviceTcp.exec_out` để
chụp màn hình, treo tới hết timeout (25s) trên MuMu dù `adb` binary thật trả kết quả
trong <0.4s cho đúng lệnh đó. Chưa rõ nguyên nhân sâu (nghi ngờ khác biệt nhỏ trong
cách adbd của MuMu trả stream so với AOSP/BlueStacks), không đáng để đào sâu — fix
bằng cách thêm `capture.adb_binary` (đường dẫn `adb` thật, MuMu tự kèm sẵn trong
`MuMuPlayer Pro.app/Contents/MacOS/MuMu Android Device.app/Contents/MacOS/tools/adb`)
và `AdbScreen._grab_raw_via_binary()` gọi qua `subprocess` thay vì thư viện. Bỏ trống
`adb_binary` thì quay lại đường `adb_shell` cũ (BlueStacks Air vẫn dùng đường này).
`AdbMouse` dùng luôn cùng cơ chế subprocess cho nhất quán.

**Template phải ghi lại theo từng emulator/tài khoản** (đã biết trước, đúng như dự
đoán): cắt template MuMu bằng cách chụp burst qua ADB (1 tấm/giây) trong lúc tự tay
thao tác 1 chu trình rally thật, chọn khung đúng bằng mắt rồi crop bằng script Python
(resize ảnh raw về `template_width` trước khi crop, để khớp đúng không gian toạ độ
runtime dùng) — nhanh hơn và đỡ phụ thuộc hơn `recorder.py` (cần quyền Accessibility
cho tiến trình Python thật thi, xin quyền qua System Settings không đủ, phải quit hẳn
app cha rồi mở lại mới nhận — nếu vẫn không nhận thì đường vòng burst-capture này là
lựa chọn tốt, không cần Accessibility gì cả vì không dùng `pynput`).

**MuMu nhẹ hơn BlueStacks đáng kể** (RAM idle <400MB so với ~740MB). Máy này chuyển
hẳn từ Parallels Windows VM (36GB) sang MuMu cho DWauto — không còn lý do giữ VM
Windows cho việc này nữa.
