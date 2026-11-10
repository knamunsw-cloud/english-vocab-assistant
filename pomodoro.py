"""Gesture state machine and duration parsing; no GUI or camera dependencies."""

import math
from datetime import datetime


def is_finger_extended(tip, pip, wrist):
    return math.hypot(tip.x - wrist.x, tip.y - wrist.y) > math.hypot(
        pip.x - wrist.x, pip.y - wrist.y
    )


def is_thumb_extended(landmarks):
    return math.hypot(
        landmarks[4].x - landmarks[17].x,
        landmarks[4].y - landmarks[17].y,
    ) > math.hypot(
        landmarks[3].x - landmarks[17].x,
        landmarks[3].y - landmarks[17].y,
    )


def is_shaka(landmarks):
    wrist = landmarks[0]
    thumb_ext = is_thumb_extended(landmarks)
    pinky_ext = is_finger_extended(landmarks[20], landmarks[18], wrist)
    return thumb_ext and pinky_ext and all(
        not is_finger_extended(landmarks[tip], landmarks[pip], wrist)
        for tip, pip in ((8, 6), (12, 10), (16, 14))
    )


def count_fingers(landmarks):
    wrist = landmarks[0]
    return int(is_thumb_extended(landmarks)) + sum(
        is_finger_extended(landmarks[tip], landmarks[pip], wrist)
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
    )


def is_thumbs_up(hand):
    return hand[4].y < hand[3].y < hand[2].y and all(
        hand[t].y > hand[j].y for t, j in ((8, 6), (12, 10), (16, 14), (20, 18))
    )


class PomodoroGesture:
    PRESETS = {1: (15, 3), 2: (25, 5), 3: (50, 10)}

    def __init__(self):
        self.state = "IDLE"
        self.selected = 0
        self.end_time = 0
        self.start_str = ""
        self.pause_start = 0
        self.total_pause = 0
        self.gesture = None
        self.gesture_start = 0
        self.gesture_fired = False
        self.cooldown_until = 0
        self.last_tick = None

    def finish(self, now, cancelled):
        if self.state == "PAUSED":
            self.total_pause += now - self.pause_start
        work, rest = self.PRESETS[self.selected]
        history = (
            f"{work}/{rest}",
            f"{self.start_str} - {datetime.now():%H:%M}",
            f"Dừng: {int(self.total_pause)}s | Hủy: {'CÓ' if cancelled else 'KHÔNG'}",
        )
        self.state = "IDLE"
        self.selected = 0
        self.last_tick = None
        return ("HISTORY", history)

    def update(self, hands, now):
        events = []
        # Hoàn thành lượt học; chưa chạy giai đoạn nghỉ theo UX mới.
        if self.state == "RUNNING" and now >= self.end_time:
            events.append(self.finish(now, False))

        shakas = sum(is_shaka(h) for h in hands)
        action = None
        if shakas >= 2:
            action = "DOUBLE_SHAKA"
        elif shakas == 1:
            action = "SINGLE_SHAKA"
        elif self.state == "SELECTING" and hands:
            if is_thumbs_up(hands[0]):
                action = "LIKE"
            else:
                fingers = count_fingers(hands[0])
                if fingers in (1, 2, 3):
                    action = f"FINGER_{fingers}"

        busy = self.state == "SELECTING" or action is not None
        if action != self.gesture:
            self.gesture = action
            self.gesture_start = now
            self.gesture_fired = False
        if (action is not None and not self.gesture_fired
                and now - self.gesture_start >= 1.5 and now >= self.cooldown_until):
            self.gesture_fired = True  # Phải đổi/thả cử chỉ để thực thi lần tiếp theo.
            self.cooldown_until = now + 2
            if action == "DOUBLE_SHAKA" and self.state in ("RUNNING", "PAUSED"):
                events.append(self.finish(now, True))
            elif action == "SINGLE_SHAKA":
                if self.state == "IDLE":
                    self.state = "SELECTING"
                    self.selected = 0
                    events.append(("SELECTING", None))
                elif self.state == "RUNNING":
                    self.state = "PAUSED"
                    self.pause_start = now
                    events.append(("PAUSED", None))
                elif self.state == "PAUSED":
                    paused = now - self.pause_start
                    self.end_time += paused
                    self.total_pause += paused
                    self.state = "RUNNING"
                    work, rest = self.PRESETS[self.selected]
                    events.append(("RUNNING", {"name": f"{work}/{rest}"}))
            elif action.startswith("FINGER_") and self.state == "SELECTING":
                self.selected = int(action[-1])
                events.append(("SELECTED", self.selected))
            elif action == "LIKE" and self.state == "SELECTING" and self.selected:
                work, rest = self.PRESETS[self.selected]
                self.state = "RUNNING"
                self.end_time = now + work * 60
                self.total_pause = 0
                self.start_str = datetime.now().strftime("%H:%M")
                self.last_tick = None
                events.append(("RUNNING", {"name": f"{work}/{rest}"}))

        if self.state == "RUNNING":
            remaining = max(0, math.ceil(self.end_time - now))
            tick = f"{remaining // 60:02d}:{remaining % 60:02d}"
            if tick != self.last_tick:
                events.append(("TICK", tick))
                self.last_tick = tick
        return busy or self.state == "SELECTING", events
