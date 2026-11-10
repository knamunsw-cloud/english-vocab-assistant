# Thay toàn bộ nội dung vocab_ui.py bằng đoạn dưới.
# main.py giữ nguyên import: from vocab_ui import VocabApp

from queue import Empty
import csv
from datetime import datetime
from pathlib import Path
from threading import Thread
from anki_service import export_to_anki_via_api

import cv2
import customtkinter as ctk
from PIL import Image


class VocabApp(ctk.CTk):
    def __init__(self, events, frames, stop_event, worker):
        super().__init__()
        self.events = events
        self.frames = frames
        self.stop_event = stop_event
        self.worker = worker
        self.closing = False
        self.video_image = None
        self.last_frame = None
        self.last_video_size = None
        self.saved_count = 0
        self.saved_words_data = []
        self.export_notice_after = None
        self.last_export_path = None

        self.title("Từ điển Anh–Việt")
        self.geometry("1440x640")
        self.minsize(1200, 520)
        self.configure(fg_color="#101827")

        self.grid_columnconfigure(0, weight=3, minsize=440)
        self.grid_columnconfigure(1, weight=2, minsize=340)
        self.grid_columnconfigure(2, weight=3, minsize=380)
        self.grid_rowconfigure(0, weight=1)

        # LEFT: thông tin từ vựng.
        left = ctk.CTkFrame(self, fg_color="#182438", corner_radius=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=20)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            left,
            text="TỪ VỰNG",
            font=("Helvetica", 18, "bold"),
            text_color="#FF6B6B",
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 16))

        self.word_label = ctk.CTkLabel(
            left,
            text="Sẵn sàng",
            font=("Helvetica", 42, "bold"),
            text_color="#F5F7FC",
            anchor="w",
            justify="left",
            wraplength=440,
        )
        self.word_label.grid(row=1, column=0, sticky="ew", padx=24)

        self.ipa_label = ctk.CTkLabel(
            left,
            text="—",
            font=("Helvetica", 23),
            text_color="#A5B4C9",
            anchor="w",
            justify="left",
            wraplength=440,
        )
        self.ipa_label.grid(
            row=2, column=0, sticky="ew", padx=24, pady=(8, 16)
        )

        self.type_label = ctk.CTkLabel(
            left,
            text="Chưa có từ",
            font=("Helvetica", 15, "italic"),
            fg_color="#203F49",
            text_color="#8AE2D6",
            corner_radius=8,
            padx=12,
            pady=6,
            wraplength=420,
        )
        self.type_label.grid(row=3, column=0, sticky="w", padx=24)

        self.meaning_panel = ctk.CTkScrollableFrame(
            left, fg_color="transparent"
        )
        self.meaning_panel.grid(
            row=4, column=0, sticky="nsew", padx=16, pady=(20, 24)
        )
        self.meaning_panel.grid_columnconfigure(0, weight=1)

        self.meaning_label = ctk.CTkLabel(
            self.meaning_panel,
            text="Chỉ vào một từ tiếng Anh để xem nghĩa tại đây.",
            font=("Helvetica", 25),
            text_color="#F1F5F9",
            anchor="nw",
            justify="left",
            wraplength=420,
        )
        self.meaning_label.grid(
            row=0, column=0, sticky="ew", padx=8, pady=8
        )
        left.bind("<Configure>", self.resize_text, add="+")

        # RIGHT: video ở góc trên; không tạo cửa sổ phụ hay Tabview.
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(
            row=0, column=1, sticky="nsew", padx=(10, 20), pady=20
        )
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            right,
            text="VIDEO",
            font=("Helvetica", 13, "bold"),
            text_color="#A5B4C9",
        ).grid(row=0, column=0, sticky="w", pady=(4, 10))

        # CTkLabel không có border_width; đặt viền trên frame bao ngoài.
        self.video_border = ctk.CTkFrame(
            right,
            height=260,
            corner_radius=12,
            border_width=2,
            border_color="gray",
            fg_color="#080E18",
        )
        self.video_border.grid(row=1, column=0, sticky="ew")
        self.video_border.grid_propagate(False)
        self.video_border.grid_columnconfigure(0, weight=1)
        self.video_border.grid_rowconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(
            self.video_border,
            text="Đang chuẩn bị video…",
            text_color="#A5B4C9",
            font=("Helvetica", 15),
        )
        self.video_label.grid(
            row=0, column=0, sticky="nsew", padx=6, pady=6
        )

        self.saved_list_label = ctk.CTkLabel(
            right, text="TỪ VỰNG ĐÃ LƯU", font=("Helvetica", 16, "bold"),
            text_color="#FFD700", anchor="center",
        )
        self.saved_list_label.grid(row=2, column=0, sticky="ew", pady=(16, 8))
        self.saved_panel = ctk.CTkScrollableFrame(
            right, fg_color="#182438", corner_radius=12,
        )
        self.saved_panel.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        self.export_button = ctk.CTkButton(
            right,
            text="Xuất CSV + Anki",
            command=self.export_saved_words,
            font=("Helvetica", 15, "bold"),
            height=42,
            corner_radius=10,
            fg_color="#0F766E",
            hover_color="#115E59",
            text_color="#FFFFFF",
        )
        self.export_button.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        far_right = ctk.CTkFrame(self, fg_color="#182438", corner_radius=16)
        far_right.grid(row=0, column=2, sticky="nsew", padx=(10, 20), pady=20)
        far_right.grid_columnconfigure(0, weight=1)
        self.pomo_frame = ctk.CTkFrame(far_right, fg_color="#2A3B5C", corner_radius=16)
        self.pomo_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 0))
        self.pomo_title = ctk.CTkLabel(
            self.pomo_frame, text="🍅 POMODORO SESSION",
            font=("Helvetica", 22, "bold"), text_color="#FF9671",
        )
        self.pomo_title.pack(pady=(15, 0))
        self.pomo_status = ctk.CTkLabel(
            self.pomo_frame, text="INACTIVE", font=("Helvetica", 14), text_color="#A5B4C9",
        )
        self.pomo_status.pack(pady=(0, 15))
        self.tabs_frame = ctk.CTkFrame(self.pomo_frame, fg_color="transparent")
        self.tabs_frame.pack(pady=5, fill="x", padx=20)
        tabs = []
        for work, rest in ((15, 3), (25, 5), (50, 10)):
            tab = ctk.CTkLabel(
                self.tabs_frame, text=f"{work} min work  |  {rest} min rest",
                font=("Helvetica", 16, "bold"), fg_color="#182438",
                text_color="#FFFFFF", corner_radius=8, height=40,
            )
            tab.pack(fill="x", pady=5)
            tabs.append(tab)
        self.tab1, self.tab2, self.tab3 = tabs
        self.pomo_timer_label = ctk.CTkLabel(
            self.pomo_frame, text="--:--", font=("Helvetica", 42, "bold"), text_color="#FFD700",
        )
        self.pomo_timer_label.pack(pady=(5, 15))
        self.history_container = ctk.CTkFrame(far_right, fg_color="#182438", corner_radius=16)
        self.history_container.grid(row=1, column=0, sticky="nsew", padx=16, pady=(15, 20))
        far_right.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            self.history_container, text="LỊCH SỬ HỌC TẬP",
            font=("Helvetica", 14, "bold"), text_color="#6ECFC4",
        ).pack(anchor="w", padx=15, pady=(15, 5))
        header = ctk.CTkFrame(self.history_container, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=5)
        for title, width in (("Session", 60), ("Thời gian", 95), ("Chi tiết", 110)):
            ctk.CTkLabel(
                header, text=title, font=("Helvetica", 12, "bold"),
                width=width, anchor="w",
            ).pack(side="left", padx=3)
        self.history_scroll = ctk.CTkScrollableFrame(
            self.history_container, fg_color="transparent",
        )
        self.history_scroll.pack(fill="both", expand=True, padx=5, pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.bind("q", lambda event: self.stop_video())
        self.after(30, self.poll_queues)

    def handle_pomo_update(self, action, payload):
        tabs = (self.tab1, self.tab2, self.tab3)
        if action == "SELECTING":
            self.pomo_status.configure(text="ĐANG CHỌN SET HỌC...", text_color="#FF6B6B")
            self.pomo_timer_label.configure(text="--:--")
            for tab in tabs:
                tab.configure(fg_color="#182438", text_color="#FFFFFF")
        elif action == "SELECTED":
            for i, tab in enumerate(tabs, 1):
                tab.configure(
                    fg_color="#6ECFC4" if i == payload else "#182438",
                    text_color="#000000" if i == payload else "#FFFFFF",
                )
        elif action == "RUNNING":
            self.pomo_status.configure(text=f"ĐANG CHẠY ({payload['name']})", text_color="#6ECFC4")
        elif action == "PAUSED":
            self.pomo_status.configure(text="TẠM DỪNG", text_color="#FFD700")
        elif action == "TICK":
            self.pomo_timer_label.configure(text=payload)
        elif action == "HISTORY":
            sess, time_str, stat = payload
            row = ctk.CTkFrame(self.history_scroll, fg_color="#2A3B5C", corner_radius=6)
            row.pack(fill="x", pady=2, padx=5)
            for text, width, color, bold in (
                (sess, 60, "#FFD700", True),
                (time_str, 95, "#F5F7FC", False),
                (stat, 110, "#A5B4C9", False),
            ):
                ctk.CTkLabel(
                    row, text=text, font=("Helvetica", 12, "bold" if bold else "normal"),
                    text_color=color, width=width, wraplength=width, anchor="w", justify="left",
                ).pack(side="left", padx=3, pady=4)
            self.after_idle(lambda: self.scroll_to_bottom(self.history_scroll))
            self.pomo_status.configure(text="INACTIVE", text_color="#A5B4C9")
            self.pomo_timer_label.configure(text="--:--")
            for tab in tabs:
                tab.configure(fg_color="#182438", text_color="#FFFFFF")

    def export_saved_words(self):
        if not self.saved_words_data:
            self.saved_list_label.configure(text="CHƯA CÓ TỪ ĐỂ XUẤT", text_color="#FFD700")
            if self.export_notice_after is not None:
                self.after_cancel(self.export_notice_after)
            self.export_notice_after = self.after(2000, self.restore_saved_title)
            return  # Chỉ thoát helper; poll_queues vẫn tiếp tục chạy.
        rows = [row[:] for row in self.saved_words_data]
        try:
            export_dir = Path(__file__).resolve().parent / "Vocab Export"
            export_dir.mkdir(parents=True, exist_ok=True)
            filename = export_dir / f"vocab_export_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
            # Exclusive create: không ghi đè file export có sẵn.
            with filename.open("x", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["STT", "Vocabulary", "Word type", "IPA", "Vietnamese Meaning"])
                writer.writerows(rows)
        except Exception as error:
            self.saved_list_label.configure(text="LỖI XUẤT CSV · DỮ LIỆU ĐƯỢC GIỮ", text_color="#FF6B6B")
            print(f"Lỗi xuất CSV: {error}")
            return

        for widget in self.saved_panel.winfo_children():
            widget.destroy()
        self.saved_count = 0
        self.saved_words_data.clear()
        if self.export_notice_after is not None:
            self.after_cancel(self.export_notice_after)
        self.export_notice_after = None
        self.saved_list_label.configure(text="ĐÃ LƯU CSV · ĐANG GỬI ANKI…", text_color="#6ECFC4")
        self.last_export_path = str(filename)
        vocab_list = [
            {"word": word, "part_of_speech": word_type, "ipa": ipa, "meaning": meaning}
            for _, word, word_type, ipa, meaning in rows
        ]
        self.start_anki_export(vocab_list, str(filename))

    def start_anki_export(self, vocab_list, csv_path):
        def worker():
            report = export_to_anki_via_api(vocab_list)
            self.events.put(("anki_export_done", (csv_path, report)))

        try:
            Thread(target=worker, daemon=True, name="anki-export").start()
        except Exception as error:
            self.events.put(("anki_export_done", (csv_path, {
                "ok": False, "added": 0, "total": len(vocab_list),
                "not_added": [], "error": str(error),
            })))

    def restore_saved_title(self):
        self.export_notice_after = None
        if not self.closing:
            self.saved_list_label.configure(text="TỪ VỰNG ĐÃ LƯU", text_color="#FFD700")

    def scroll_to_bottom(self, panel):
        if not self.closing and panel.winfo_exists():
            panel.update_idletasks()
            panel._parent_canvas.yview_moveto(1.0)

    def resize_text(self, event):
        width = max(260, event.width - 60)
        self.word_label.configure(wraplength=width)
        self.ipa_label.configure(wraplength=width)
        self.type_label.configure(wraplength=width)
        self.meaning_label.configure(wraplength=max(240, width - 16))

    def update_video(self, frame):
        """Nhận frame BGR từ video file hoặc webcam; chạy trên main thread."""
        width = max(1, self.video_border.winfo_width() - 16)
        height = max(1, self.video_border.winfo_height() - 16)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((width, height), Image.Resampling.LANCZOS)

        self.video_image = ctk.CTkImage(
            light_image=image,
            dark_image=image,
            size=image.size,
        )
        self.video_label.configure(image=self.video_image, text="")
        self.last_video_size = (width, height)

    def poll_queues(self):
        if self.closing:
            return

        for _ in range(30):
            try:
                kind, payload = self.events.get_nowait()
            except Empty:
                break

            if kind == "vocab":
                word, ipa, word_type, meaning = payload
                self.word_label.configure(text=word)
                self.ipa_label.configure(text=ipa)
                self.type_label.configure(text=word_type)
                self.meaning_label.configure(text=meaning)
            elif kind == "pomo_update":
                self.handle_pomo_update(*payload)
            elif kind == "anki_export_done":
                csv_path, report = payload
                print(f"CSV đã lưu: {csv_path} | Anki: {report['added']}/{report['total']}")
                if report["error"]:
                    print(f"Anki: {report['error']} | Chưa thêm: {report['not_added']}")
                if csv_path == self.last_export_path:
                    if self.export_notice_after is not None:
                        self.after_cancel(self.export_notice_after)
                    notice = ("ĐÃ LƯU CSV + ANKI" if report["ok"]
                              else f"CSV ĐÃ LƯU · ANKI {report['added']}/{report['total']}")
                    self.saved_list_label.configure(
                        text=notice, text_color="#6ECFC4" if report["ok"] else "#FFD700",
                    )
                    self.export_notice_after = self.after(6000, self.restore_saved_title)
            elif kind == "export_csv":
                self.export_saved_words()
            elif kind == "save_word":
                word, word_type, ipa, meaning = payload
                self.saved_count += 1
                self.saved_words_data.append([self.saved_count, word, word_type, ipa, meaning])
                item_frame = ctk.CTkFrame(
                    self.saved_panel, fg_color="#223047", corner_radius=8,
                )
                item_frame.pack(fill="x", padx=8, pady=5)
                ctk.CTkLabel(
                    item_frame, text=f"{self.saved_count}. {word}",
                    font=("Helvetica", 15, "bold"),
                    text_color="#F5F7FC", anchor="w",
                ).pack(side="left", padx=(12, 10), pady=8)
                word_type = str(word_type or "N/A").strip() or "N/A"
                w_type = word_type.lower()
                # Adverb chứa chuỗi 'verb'; kiểm tra trước Verb.
                if "adv" in w_type or "trạng từ" in w_type:
                    badge_color = "#8B5CF6"
                elif "adj" in w_type or "tính từ" in w_type:
                    badge_color = "#F59E0B"
                elif "pronoun" in w_type or "đại từ" in w_type:
                    badge_color = "#64748B"
                elif "noun" in w_type or "danh từ" in w_type:
                    badge_color = "#3B82F6"
                elif "verb" in w_type or "động từ" in w_type:
                    badge_color = "#EF4444"
                else:
                    badge_color = "#64748B"
                ctk.CTkLabel(
                    item_frame, text=word_type, font=("Helvetica", 11, "bold"),
                    fg_color=badge_color, text_color="#FFFFFF", corner_radius=6,
                    width=50, height=24, wraplength=120,
                ).pack(side="right", padx=(10, 12), pady=8)
                self.after_idle(lambda: self.scroll_to_bottom(self.saved_panel))
            # Event "crop" không tạo thêm cửa sổ.

        new_frame = False
        try:
            self.last_frame = self.frames.get_nowait()
            new_frame = True
        except Empty:
            pass

        size = (
            max(1, self.video_border.winfo_width() - 16),
            max(1, self.video_border.winfo_height() - 16),
        )
        if self.last_frame is not None:
            if new_frame or size != self.last_video_size:
                self.update_video(self.last_frame)

        self.after(30, self.poll_queues)

    def stop_video(self):
        self.stop_event.set()

    def close_app(self):
        if self.closing:
            return
        self.closing = True
        self.stop_event.set()
        self.wait_for_worker()

    def wait_for_worker(self):
        if self.worker.is_alive():
            self.after(100, self.wait_for_worker)
        else:
            self.destroy()
