"""Đọc video trên Desktop và hiển thị các điểm mốc bàn tay.

Chạy: python main.py
Chạy offline với mô hình Hand Landmarker và từ điển SQLite đã có sẵn.
"""

import os
import warnings

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["GLOG_minloglevel"] = "2"
warnings.filterwarnings(
    "ignore", category=UserWarning,
    module=r"google\.protobuf\.symbol_database",
)

import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time

import cv2
import mediapipe as mp
import pytesseract
from vocab_services import query_vocabulary
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from vocab_ui import VocabApp
from pomodoro import PomodoroGesture, is_shaka, count_fingers, is_thumbs_up


VIDEO_PATH = Path.home() / "Desktop" / "video.MOV"
VIDEO_SOURCE = 1  
FLIP_MODE = -1 # 1: lật ngang, 0: lật dọc, -1: xoay 180 độ, None: tắt lật
MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
WINDOW_NAME = "Hand Tracking - Press q to quit"
OCR_STABLE_SECONDS = 0.45
OCR_COOLDOWN = 0.4
OCR_MOVEMENT_TOLERANCE = 14  # Pixel so với điểm neo; không cộng dồn trôi tay.
OCR_MIN_CONFIDENCE = 55
OCR_PREVIEW_WINDOW = "OCR crop - last captured frame"
word_cache = {}
last_word = ""
last_call_time = 0
LOOKUP_COOLDOWN = 3.0
lookup_lock = Lock()
pending_words = set()
ui_events = Queue()
active_vocab_updates = Queue()
video_frames = Queue(maxsize=1)
stop_event = Event()


def update_ui(word, ipa, word_type, meaning):
    """Thread-safe: chỉ gửi dữ liệu, tuyệt đối không gọi widget từ worker."""
    ui_events.put(("vocab", (word, ipa, word_type, meaning)))
    active_vocab_updates.put((word, word_type or "N/A", ipa or "", " ".join((meaning or "").split())))


def publish_frame(frame):
    """Chỉ giữ frame mới nhất để preview không tích lũy độ trễ."""
    try:
        video_frames.get_nowait()
    except Empty:
        pass
    try:
        video_frames.put_nowait(frame)
    except Full:
        pass


def lookup_word(ocr_text):
    """Tra SQLite/cache rồi gửi dữ liệu có cấu trúc sang main thread."""
    global last_word, last_call_time
    word = re.sub(r"[^a-zA-Z]", "", ocr_text or "").lower()
    if len(word) <= 1:
        return None
    with lookup_lock:
        last_word = word
        last_call_time = time.time()
        cached = word_cache.get(word)
    if cached is not None:
        update_ui(cached["word"], cached["ipa"], cached["word_type"], cached["meaning"])
        return cached

    result = query_vocabulary(word)
    if result["found"]:
        with lookup_lock:
            word_cache[word] = result
    update_ui(result["word"], result["ipa"], result["word_type"], result["meaning"])
    return result


def enqueue_lookup(ocr_text, jobs):
    """Debounce trước khi xếp hàng, không bỏ qua hiển thị/phím q của video."""
    word = re.sub(r"[^a-zA-Z]", "", ocr_text or "").lower()
    if len(word) <= 1:
        return False
    with lookup_lock:
        if word in pending_words:
            return False
        if word == last_word and time.time() - last_call_time < LOOKUP_COOLDOWN:
            return False
        pending_words.add(word)
    jobs.put(word)
    return True


def fetch_vocab_info(word):
    """Lấy cả ba trường từ SQLite; không fallback sang thư viện/API khác."""
    result = query_vocabulary(word)
    formatted = (
        f"[Vocab: {result['word']}]\n"
        f"Word IPA: {result['ipa']}\n"
        f"Word type: {result['word_type']}\n"
        f"Vietnamese meaning: {result['meaning']}"
    )
    return formatted, result["found"]


def speak_word(word):
    """Phát âm bằng macOS say, không chờ tiến trình âm thanh kết thúc."""
    word = word.strip()
    if word:
        subprocess.Popen(["say", word])


def lookup_worker(jobs):
    """Tra lần lượt trên luồng riêng, không chặn OCR hay cửa sổ video."""
    while True:
        word = jobs.get()
        try:
            if word is None:
                return
            if stop_event.is_set():
                continue
            lookup_word(word)
            # Dữ liệu đã gửi tới UI; chỉ phát âm từ tìm thấy trong SQLite.
            with lookup_lock:
                found = word in word_cache
            if found:
                speak_word(word)
        except Exception as error:
            ui_events.put(("status", f"Lỗi tra từ/âm thanh: {error}"))
        finally:
            with lookup_lock:
                pending_words.discard(word)
            jobs.task_done()


class StablePointer:
    """Cho phép OCR một lần mỗi lần giữ tay ổn định."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.anchor = None
        self.hand_label = None
        self.frames = 0
        self.stable_since = None
        self.triggered = False
        self.generation = getattr(self, "generation", 0) + 1

    def update(self, point, hand_label):
        now = time.monotonic()
        if point is None:
            self.reset()
            return False
        if (
            self.anchor is None
            or hand_label != self.hand_label
            or math.dist(point, self.anchor) > OCR_MOVEMENT_TOLERANCE
        ):
            self.anchor = point
            self.hand_label = hand_label
            self.frames = 0
            self.stable_since = now
            self.triggered = False
            self.generation += 1
        self.frames += 1
        return (self.stable_since is not None
                and now - self.stable_since >= OCR_STABLE_SECONDS
                and not self.triggered)


def select_word(data, tip, origin, region_shape, scale=2):
    """Chọn từ gần nhất phía trên đầu ngón; trả tọa độ ảnh gốc."""
    tx, ty = tip
    ox, oy = origin
    height, width = region_shape[:2]
    candidates = []
    for i, raw_text in enumerate(data["text"]):
        word = raw_text.strip().strip(".,;:!?()[]{}\"'“”‘’")
        if not re.fullmatch(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", word):
            continue
        confidence = float(data["conf"][i])
        if confidence < 0:
            continue
        left = data["left"][i] / scale
        top = data["top"][i] / scale
        right = left + data["width"][i] / scale
        bottom = top + data["height"][i] / scale
        if left <= 1 or right >= width - 1 or top <= 1 or bottom >= height - 1:
            continue
        x1, y1 = ox + math.floor(left), oy + math.floor(top)
        x2, y2 = ox + math.ceil(right), oy + math.ceil(bottom)
        horizontal_gap = max(x1 - tx, tx - x2, 0)
        vertical_gap = ty - y2
        # Giới hạn sai lệch ngang theo chiều cao chữ; không chọn từ xa bên cạnh.
        if vertical_gap < 0 or horizontal_gap > max(8, (y2 - y1) * 0.6):
            continue
        score = vertical_gap + 2 * horizontal_gap
        candidates.append((score, abs((x1 + x2) / 2 - tx),
                           {"text": word, "confidence": confidence,
                            "box": (x1, y1, x2, y2)}))
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate[:2])[2]


def read_word(frame, tip):
    """Tìm hộp từng từ, chọn theo ngón tay, crop đúng từ rồi OCR lại."""
    height, width = frame.shape[:2]
    x, y = tip
    # Đây chỉ là vùng TÌM KIẾM nhiều từ, không phải hộp crop của từ cuối cùng.
    half_width = max(300, round(width * 0.30))
    search_height = max(100, round(height * 0.16))
    x1, x2 = max(0, x - half_width), min(width, x + half_width)
    y1, y2 = max(0, y - search_height), min(height, y - 5)
    if x1 >= x2 or y1 >= y2:
        return None
    region = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(
        enlarged, lang="eng", config="--psm 11",
        output_type=pytesseract.Output.DICT, timeout=4,
    )
    selected = select_word(data, tip, (x1, y1), region.shape)
    if selected is None:
        return None
    bx1, by1, bx2, by2 = selected["box"]
    # Không lấy thêm pixel hai bên: tránh ăn sang từ trước/sau.
    crop = frame[by1:by2, bx1:bx2].copy()
    # Kết quả rõ ràng không cần khởi chạy Tesseract lần thứ hai.
    if selected["confidence"] >= 85:
        selected["crop"] = crop
        return selected
    word_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    word_gray = cv2.resize(word_gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # Thêm viền trắng tổng hợp, không lấy chữ hàng xóm từ ảnh gốc.
    prepared = cv2.copyMakeBorder(
        word_gray, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255
    )
    confirmed = pytesseract.image_to_data(
        prepared, lang="eng", config="--psm 8",
        output_type=pytesseract.Output.DICT, timeout=3,
    )
    words = [(text.strip().strip(".,;:!?()[]{}\"'“”‘’"), float(conf))
             for text, conf in zip(confirmed["text"], confirmed["conf"])
             if text.strip() and float(conf) >= 0]
    if len(words) == 1 and re.fullmatch(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", words[0][0]):
        text, confidence = words[0]
        if confidence >= max(OCR_MIN_CONFIDENCE, selected["confidence"]):
            selected.update(text=text, confidence=confidence)
    if selected["confidence"] < OCR_MIN_CONFIDENCE:
        return None
    selected["crop"] = crop
    return selected

# Các cặp chỉ số nối 21 điểm mốc thành khung xương bàn tay.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def ensure_model() -> None:
    """Chỉ dùng mô hình local, không tự tải qua mạng."""
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Thiếu mô hình offline: {MODEL_PATH}")


def is_pointing(hand) -> bool:
    """Kiểm tra ngón trỏ duỗi và ba ngón còn lại gập theo trục y.

    Giả định các ngón hướng lên trên ảnh (y tăng từ trên xuống dưới).
    Ngón cái không tham gia điều kiện này.
    """
    return (
        hand[8].y < hand[6].y
        and hand[12].y > hand[10].y
        and hand[16].y > hand[14].y
        and hand[20].y > hand[18].y
    )


def draw_landmarks(frame, hands) -> bool:
    """Đổi tọa độ chuẩn hóa của MediaPipe sang pixel và vẽ lên ảnh."""
    height, width = frame.shape[:2]
    pointing_detected = False
    for hand in hands:
        points = [
            (round(landmark.x * (width - 1)), round(landmark.y * (height - 1)))
            for landmark in hand
        ]
        for start, end in HAND_CONNECTIONS:
            cv2.line(frame, points[start], points[end], (0, 255, 0), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(frame, point, 4, (0, 0, 255), -1, cv2.LINE_AA)
        if is_pointing(hand):
            pointing_detected = True
            cv2.circle(frame, points[8], 20, (0, 255, 0), 4, cv2.LINE_AA)
    return pointing_detected


def video_worker() -> None:
    """Chạy OpenCV/MediaPipe ở nền; không tạo bất kỳ cửa sổ native nào."""
    try:
        process_video()
    except Exception as error:
        ui_events.put(("status", f"Không xử lý được video: {error}"))


def process_video() -> None:
    if isinstance(VIDEO_SOURCE, str) and not Path(VIDEO_SOURCE).is_file():
        raise FileNotFoundError(f"Không tìm thấy video: {VIDEO_SOURCE}")
    # Kiểm tra chương trình Tesseract trước khi mở vòng lặp video.
    pytesseract.get_tesseract_version()

    capture = cv2.VideoCapture(
        VIDEO_SOURCE,
        cv2.CAP_AVFOUNDATION if isinstance(VIDEO_SOURCE, int) else cv2.CAP_ANY,
    )
    executor = ThreadPoolExecutor(max_workers=1)
    ocr_future = None
    ocr_generation = None
    selected_word = None
    next_ocr_at = 0.0
    pointer = StablePointer()
    lookup_jobs = Queue()
    # Tra cứu chạy nền; mỗi dịch vụ có timeout và số lần thử hữu hạn.
    vocab_thread = Thread(target=lookup_worker, args=(lookup_jobs,), daemon=True)
    vocab_thread.start()
    try:
        if not capture.isOpened():
            raise RuntimeError(f"OpenCV không mở được nguồn video: {VIDEO_SOURCE}")
        ensure_model()
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30.0

        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            frame_index = 0
            previous_timestamp = -1
            stream_started_at = time.perf_counter()
            current_active_word = None
            current_active_type = "N/A"
            current_active_ipa = ""
            current_active_meaning = ""
            double_like_start = 0
            double_like_fired = False
            already_saved = False
            pomo = PomodoroGesture()

            ui_events.put(("status", "Giữ ngón trỏ ổn định để tra từ"))
            while not stop_event.is_set():
                started_at = time.perf_counter()
                success, frame = capture.read()
                if not success:
                    if frame_index == 0:
                        raise RuntimeError("Không đọc được khung hình đầu tiên của video.")
                    break

                if FLIP_MODE is not None:
                    frame = cv2.flip(frame, FLIP_MODE)

                # OpenCV dùng BGR, còn MediaPipe nhận ảnh RGB.
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                # Webcam dùng thời gian thực; không đọc CAP_PROP_POS_MSEC.
                if isinstance(VIDEO_SOURCE, int):
                    timestamp_ms = round(
                        (time.perf_counter() - stream_started_at) * 1000
                    )
                else:
                    timestamp_ms = round(frame_index * 1000.0 / fps)
                timestamp_ms = max(previous_timestamp + 1, timestamp_ms)
                previous_timestamp = timestamp_ms
                result = landmarker.detect_for_video(image, timestamp_ms)

                # Nhận kết quả từ worker tra từ, không chia sẻ state không khóa.
                while True:
                    try:
                        (current_active_word, current_active_type,
                         current_active_ipa, current_active_meaning) = active_vocab_updates.get_nowait()
                        already_saved = False
                    except Empty:
                        break

                two_hands = len(result.hand_landmarks) >= 2
                now = time.monotonic()
                double_like = sum(is_thumbs_up(hand) for hand in result.hand_landmarks) == 2
                if double_like:
                    if double_like_start == 0:
                        double_like_start = now
                    elif now - double_like_start >= 3.0 and not double_like_fired:
                        ui_events.put(("export_csv", None))
                        double_like_fired = True
                else:
                    double_like_start = 0
                    double_like_fired = False
                # Double Like không được đồng thời xác nhận preset Pomodoro.
                pomo_busy, pomo_events = pomo.update([] if double_like else result.hand_landmarks, now)
                for state in pomo_events:
                    ui_events.put(("pomo_update", state))
                if two_hands and not pomo_busy and not double_like:
                    hand1, hand2 = result.hand_landmarks[:2]
                    distance = math.hypot(
                        hand2[8].x - hand1[8].x,
                        hand2[8].y - hand1[8].y,
                    )
                    if distance < 0.05 and current_active_word and not already_saved:
                        ui_events.put(("save_word", (
                            current_active_word, current_active_type,
                            current_active_ipa, current_active_meaning,
                        )))
                        already_saved = True

                # Chỉ chọn vùng OCR khi có đúng một bàn tay đang chỉ.
                candidates = [
                    (hand, handedness[0].category_name)
                    for hand, handedness in zip(
                        result.hand_landmarks, result.handedness
                    )
                    if is_pointing(hand)
                ]
                pointing_now = not pomo_busy and not two_hands and len(candidates) == 1
                if pointing_now:
                    hand, label = candidates[0]
                    height, width = frame.shape[:2]
                    tip = (
                        round(hand[8].x * (width - 1)),
                        round(hand[8].y * (height - 1)),
                    )
                    ready = pointer.update(tip, label)
                else:
                    # Mở khóa lần giữ tay kế tiếp và vô hiệu hóa kết quả cũ.
                    pointer.reset()
                    ocr_generation = None
                    selected_word = None
                    ready = False
                    if ocr_future is not None and ocr_future.cancel():
                        ocr_future = None
                    # Nếu OCR đang chạy, giữ future để thu hồi, không xếp job chồng.

                if ocr_generation != pointer.generation:
                    selected_word = None

                if ocr_future is not None and ocr_future.done():
                    next_ocr_at = time.monotonic() + OCR_COOLDOWN
                    # Không vẽ hộp cũ nếu tay đã di chuyển khi OCR đang chạy.
                    if ocr_generation == pointer.generation:
                        selected_word = report_ocr(ocr_future)
                        if selected_word is not None:
                            # lookup_worker sẽ gọi lookup_word(ocr_text) ở nền.
                            enqueue_lookup(selected_word["text"], lookup_jobs)
                            ui_events.put(("crop", selected_word["crop"]))
                        else:
                            # OCR thất bại không được khóa tay ở trạng thái triggered.
                            pointer.triggered = False
                            pointer.frames = 0
                            pointer.stable_since = time.monotonic()
                    ocr_future = None

                if (pointing_now and ready and ocr_future is None
                        and time.monotonic() >= next_ocr_at):
                    # Giữ ảnh gốc trước khi vẽ; luồng nền sẽ tìm và crop từ.
                    ocr_future = executor.submit(read_word, frame.copy(), tip)
                    ocr_generation = pointer.generation
                    pointer.triggered = True

                draw_landmarks(frame, result.hand_landmarks)
                if selected_word is not None:
                    x1, y1, x2, y2 = selected_word["box"]
                    cv2.rectangle(frame, (x1, y1), (x2 - 1, y2 - 1),
                                  (0, 255, 255), 2, cv2.LINE_AA)
                    cv2.putText(frame, selected_word["text"], (x1, max(20, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 0), 2)
                publish_frame(frame)
                frame_index += 1

                # Trừ thời gian xử lý để tốc độ phát gần FPS gốc khi có thể.
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                delay_ms = max(1, round(1000 / fps - elapsed_ms))
                stop_event.wait(delay_ms / 1000)
    finally:
        capture.release()
        executor.shutdown(wait=True)
        if (not stop_event.is_set() and ocr_future is not None
                and ocr_generation == pointer.generation):
            last_result = report_ocr(ocr_future)
            if last_result is not None:
                enqueue_lookup(last_result["text"], lookup_jobs)
        lookup_jobs.put(None)
        # Cho kết quả đang tra kịp in sau khi hết video, nhưng không chờ vô hạn.
        vocab_thread.join(timeout=45)
    ui_events.put(("status", "Đã dừng video" if stop_event.is_set()
                   else "Video đã kết thúc · Kết quả được giữ trên màn hình"))


def report_ocr(future):
    try:
        result = future.result()
        return result
    except Exception as error:
        ui_events.put(("status", f"Lỗi OCR: {error}"))
        return None


def main():
    # CTk/mainloop và mọi widget đều được tạo ở main thread.
    worker = Thread(target=video_worker, daemon=True, name="video-worker")
    app = VocabApp(ui_events, video_frames, stop_event, worker)
    app.after(100, worker.start)
    app.mainloop()


if __name__ == "__main__":
    main()
