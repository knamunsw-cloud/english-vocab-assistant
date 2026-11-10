# English Vocabulary Assistant

Ứng dụng desktop Python hỗ trợ học tiếng Anh trên giấy qua camera top-down.

## Tính năng

- MediaPipe nhận diện tay; OpenCV và Tesseract OCR từ được chỉ vào.
- Tra SQLite offline, dùng NLTK tìm từ gốc và Google Translate dự phòng khi không tìm thấy.
- Hiển thị từ, IPA, từ loại, nghĩa tiếng Việt bằng CustomTkinter.
- Phát âm bằng lệnh `say` của macOS.
- Lưu từ, xuất CSV UTF-8 BOM và gửi sang Anki Desktop qua AnkiConnect.
- Pomodoro preset 15/3, 25/5, 50/10; pause/resume/cancel và lịch sử trong phiên.

**Lưu ý:** Timer hiện chỉ chạy phần học, chưa tự chạy phần nghỉ. Camera/GUI được thiết kế cho macOS; không phải ứng dụng web. Google fallback cần internet; AnkiConnect chạy nội bộ máy.

## Cài đặt (macOS, Python 3.11)

```bash
brew install tesseract
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m nltk.downloader wordnet
```

Các dependency chưa khóa phiên bản; nếu phiên bản mới gây khác biệt, kiểm tra môi trường trước khi nâng cấp.

Database `offline_dict.db` và mô hình `models/hand_landmarker.task` có sẵn trong repository. Nếu thiếu database, chạy `python download_dict.py` tại thư mục dự án. Script không ghi đè database đã có.

## Chạy

```bash
source .venv/bin/activate
python main.py
```

Trong `main.py`, chỉnh `VIDEO_SOURCE` theo camera thực tế (0, 1, ...). Chỉ số camera có thể thay đổi sau khi kết nối lại. Có thể dùng đường dẫn video thay cho số.

Chỉnh `FLIP_MODE`: `None` giữ nguyên, `1` lật ngang, `0` lật dọc, `-1` xoay 180°. Chữ phải đúng chiều trên preview. Cấp quyền camera cho Terminal/Python trong macOS nếu được hỏi.

## Cử chỉ và thao tác

| Thao tác | Cách thực hiện |
| --- | --- |
| Tra từ | Một tay, duỗi ngón trỏ hướng lên ảnh, gập ba ngón còn lại; giữ ổn định dưới từ |
| Lưu từ | Chạm hai đầu ngón trỏ |
| Xuất | Nút **Xuất CSV + Anki**, hoặc hai Thumbs Up giữ 3 giây |
| Chọn Pomodoro | Shaka một tay giữ 1,5 giây, rồi giơ 1–3 ngón để chọn preset |
| Bắt đầu preset | Thumbs Up một tay giữ 1,5 giây |
| Pause/resume | Shaka một tay giữ 1,5 giây |
| Hủy phiên | Shaka hai tay giữ 1,5 giây |

Thả/đổi cử chỉ trước lần thực thi tiếp theo. OCR và cử chỉ có thể kém ổn định khi chữ mờ, tay che chữ hoặc xoay khác hướng dự kiến. Dùng nút xuất nếu Double Thumbs Up không nhận. Phím `q` dừng camera; đóng cửa sổ để thoát.

## Anki và CSV

Mở Anki Desktop với [AnkiConnect](https://ankiweb.net/shared/info/2055492159). API local dùng `http://localhost:8765`.

Trong `anki_service.py`, có thể sửa `DECK_NAME`, `MODEL_NAME`, `FRONT_FIELD`, `BACK_FIELD`. Mặc định là `My_English_Vocab`, `Basic`, `Front`, `Back`.

CSV luôn lưu trước vào `Vocab Export/` cạnh `main.py`; sau đó Anki được gọi ở background thread. Nếu Anki lỗi, CSV vẫn còn. Danh sách UI được reset khi CSV thành công. Lỗi/chi tiết kết quả Anki được in ra Terminal. Batch có thể thành công một phần; kiểm tra Anki trước khi thử lại.

`anki_demo.py` là demo riêng: chạy script sẽ gửi 10 từ ngẫu nhiên sang Anki thật.

## Kiểm thử

```bash
python -m unittest discover -s work -p 'test_*.py'
```

Tests sử dụng mock API và thư mục tạm; không thay thế kiểm thử camera/GUI thực tế.

## Cấu trúc

- `main.py`: camera, gesture, OCR, hàng đợi worker.
- `vocab_ui.py`: giao diện, saved cards, CSV và Anki background export.
- `vocab_services.py`: SQLite, lemma và online fallback.
- `pomodoro.py`: gesture/state machine Pomodoro.
- `anki_service.py`, `anki_demo.py`: AnkiConnect và demo.
- `work/test_*.py`: unit tests; scratch/cache khác không được commit.

## Dữ liệu bên thứ ba và quyền riêng tư

Từ điển lấy từ [skypediacode/english-vietnamese-dictionary](https://github.com/skypediacode/english-vietnamese-dictionary). Giữ nguyên `offline_dict.LICENSE.txt` và `offline_dict.ATTRIBUTION.md` đi kèm; đây không phải dữ liệu do tác giả ứng dụng tự biên soạn.

Mô hình bàn tay là MediaPipe Hand Landmarker của Google; xem `models/README.md` để biết nguồn. Chưa chọn license riêng cho mã ứng dụng; không suy diễn license của database áp dụng cho toàn bộ source.

Không đưa venv, video, dữ liệu xuất cá nhân hay credentials vào Git. Google fallback gửi từ OCR ra dịch vụ ngoài khi offline lookup thất bại. AnkiConnect chỉ nên truy cập trên máy cục bộ.
