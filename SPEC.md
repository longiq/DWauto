# Spec: Tool Auto Rally cho Darkwar Survival (workflow ghi-thao-tác)

> Tài liệu này là **spec để phiên Claude CLI cục bộ trên Windows** thực thi.
> Phiên đám mây không build code (không thấy màn hình Windows); mọi bước ghi/chạy
> diễn ra trên máy Windows có giả lập + game đang mở.

## Bối cảnh

Game **Darkwar Survival** (giả lập Android trên Windows) không có auto rally.
Cần một tool **tự động hóa click trên màn hình**, chỉ giả lập input như người thật,
**không can thiệp API/bộ nhớ game** (an toàn, "hợp lý").

Chu trình cần auto:
1. Click **Search** (tìm mục tiêu).
2. Chọn **team** để march — luân phiên **1 → 2 → 3 → 1 ...**.
3. Click **March**.
4. Giám sát: nếu hiện thông báo **"target under attack"** → quay lại bước 1 (Search lại).

## Quyết định đã chốt

- **Toàn bộ chạy ở phiên Claude CLI CỤC BỘ trên Windows.**
- Lấy ảnh mẫu + luồng bằng **chế độ "recorder"**: người dùng thao tác rally một lần
  bằng tay, script ghi **screenshot + tọa độ tại mỗi lần click** và tự cắt vùng quanh
  nút thành ảnh mẫu. Sau đó Claude **chuẩn hóa** (gán nhãn, sinh config) rồi viết tool auto.
- Ngôn ngữ: **Python**. Nhận diện UI: **template matching (OpenCV)**.
- Chọn team: **luân phiên 1 → 2 → 3**. Phát hiện "under attack": **template matching**.

## Thư viện

- `mss` — chụp màn hình nhanh (numpy array).
- `opencv-python` + `numpy` — `cv2.matchTemplate`, cắt/khớp ảnh.
- `pyautogui` — giả lập di chuyển chuột + click (offset/độ trễ ngẫu nhiên).
- `pynput` — hook chuột (recorder) + phím tắt Start/Stop (auto tool).
- `PyYAML` — đọc/ghi cấu hình.

## Cấu trúc dự án

```
DWauto/
├── README.md               # hướng dẫn cài đặt, cách ghi, cách chạy
├── requirements.txt
├── config.yaml             # sinh ra sau bước chuẩn hóa
├── recorder.py             # CHẾ ĐỘ GHI: log click + screenshot + tự cắt template
├── main.py                 # CHẾ ĐỘ AUTO: vòng lặp rally + phím tắt dừng + --dry-run
├── dwauto/
│   ├── __init__.py
│   ├── config.py           # load/validate config.yaml
│   ├── screen.py           # chụp màn hình + template matching
│   ├── actions.py          # click/move qua pyautogui (offset + delay ngẫu nhiên)
│   └── rally.py            # state machine chu trình rally
├── recordings/             # output recorder: frames + clicks.json + crop ảnh mẫu
├── templates/              # ảnh mẫu đã chuẩn hóa & gán nhãn
│   ├── search_button.png
│   ├── team1.png / team2.png / team3.png
│   ├── march_button.png
│   └── under_attack.png
└── tests/
    └── test_screen.py      # test logic matching với ảnh tĩnh (không cần màn hình)
```

## Giai đoạn 1 — `recorder.py` (Chế độ ghi / học)

- Dùng `pynput.mouse.Listener` bắt mọi click → ghi `(timestamp, x, y, button)`.
- Tại mỗi click: chụp màn hình (`mss`), lưu `frame_{n}.png` và **cắt vùng quanh con trỏ**
  (vd ô ~120×60 px quanh (x,y)) thành `crop_{n}.png` làm ảnh mẫu ứng viên.
- Ghi tất cả ra `recordings/clicks.json` (thứ tự, tọa độ, đường dẫn frame + crop).
- Phím tắt bắt đầu/kết thúc ghi (vd F8). Người dùng thao tác **đúng một chu trình rally
  đầy đủ**: Search → chọn team → March → (chờ "under attack") → chụp thêm 1 frame khi
  popup "under attack" hiện để làm mẫu cảnh báo.

## Giai đoạn 2 — Chuẩn hóa (Claude xử lý dữ liệu ghi)

- Xem `clicks.json` + crop → **gán nhãn** từng bước: `search_button`, `team1/2/3`,
  `march_button`, `under_attack` → lưu vào `templates/` tên chuẩn.
- Tinh chỉnh crop nếu cần (cắt sát nút, loại nền nhiễu).
- Sinh `config.yaml`: `match_threshold` (~0.85), `delays` (min/max), `monitor_interval`,
  `monitor_timeout`, đường dẫn template, `regions` (vùng quét under_attack), thứ tự bước,
  team `[1,2,3]`.

## Giai đoạn 3 — Tool auto

- `screen.py`:
  - `capture()` → ảnh BGR qua `mss`.
  - `find_template(screen, path, threshold, region=None)` → `cv2.matchTemplate`
    (`TM_CCOEFF_NORMED`) + `minMaxLoc`; trả tâm `(x,y)` nếu `maxVal>=threshold`, else `None`.
  - `wait_for(path, timeout, interval)` → poll đến khi thấy hoặc hết giờ.
- `actions.py`: `click(x,y)` với `pyautogui` + offset ±vài px + delay ngẫu nhiên;
  bật `pyautogui.FAILSAFE`.
- `rally.py` — state machine:
  1. **SEARCH** → click `search_button`.
  2. **SELECT_TARGET** → (nếu có) click nút xác nhận mục tiêu mở màn điều quân.
  3. **SELECT_TEAM** → click `team{idx}` với `idx` luân phiên 1→2→3.
  4. **MARCH** → click `march_button`.
  5. **MONITOR** → quét `under_attack` theo `region` định kỳ; thấy → quay lại **SEARCH**;
     hết giờ/quân về → bắt đầu chu trình kế.
- `main.py`: đọc config, vòng `while running`; phím tắt **F8 Start/Stop**, **Esc thoát**;
  bắt exception; cờ **`--dry-run`** (chỉ log "sẽ click ở (x,y)"); logging console + file.

## Verification

1. **`pytest tests/test_screen.py`**: ảnh tổng hợp chứa template ở vị trí biết trước →
   `find_template` trả đúng tâm; ảnh không chứa → `None`. (Không cần màn hình.)
2. **`python main.py --dry-run`** trên Windows: quan sát log nhận diện đúng nút mà chưa click.
3. **Chạy thật**: mở giả lập + game, `python main.py`, F8 chạy, quan sát chu trình
   Search → Team 1/2/3 → March → (under attack) → Search.

## Lưu ý

- Tool chỉ giả lập input chuột → không can thiệp API game.
- Giữ **độ phân giải giả lập cố định**; đổi thì ghi/chụp lại template.
- Bước chuẩn hóa cần con người/Claude xác nhận nhãn để tránh gán sai nút.

## Ngoài phạm vi (trừ khi yêu cầu thêm)

- Đóng gói `.exe` (PyInstaller, thêm sau).
- GUI cấu hình đồ họa.
- Nhận diện team rảnh/bận (đã chốt luân phiên cố định 1→2→3).
