import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pomodoro import PomodoroGesture


class PomodoroTests(unittest.TestCase):
    def setUp(self):
        self.pomo = PomodoroGesture()
        self.shaka = patch('pomodoro.is_shaka', side_effect=lambda h: h == 'shaka')
        self.thumb = patch('pomodoro.is_thumbs_up', side_effect=lambda h: h == 'like')
        self.fingers = patch('pomodoro.count_fingers', side_effect=lambda h: h if isinstance(h, int) else 0)
        for p in (self.shaka, self.thumb, self.fingers):
            p.start()
            self.addCleanup(p.stop)

    def hold(self, hands, start):
        self.pomo.update([], start - .1)
        self.pomo.update(hands, start)
        return self.pomo.update(hands, start + 1.5)[1]

    def start_timer(self):
        self.hold(['shaka'], 0)
        self.hold([2], 4)
        return self.hold(['like'], 8)

    def test_select_start_and_no_held_toggle(self):
        self.assertEqual(self.hold(['shaka'], 0), [('SELECTING', None)])
        self.pomo.update(['shaka'], 10)
        self.assertEqual(self.pomo.state, 'SELECTING')
        self.assertEqual(self.hold([2], 12), [('SELECTED', 2)])
        events = self.hold(['like'], 16)
        self.assertIn(('RUNNING', {'name': '25/5'}), events)
        self.assertIn(('TICK', '25:00'), events)
        self.assertEqual(self.pomo.update([], 17.6)[1], [])

    def test_pause_resume(self):
        self.start_timer()
        deadline = self.pomo.end_time
        self.hold(['shaka'], 12)
        self.pomo.update(['shaka'], 100)
        self.assertEqual(self.pomo.state, 'PAUSED')
        self.hold(['shaka'], 104)
        self.assertEqual(self.pomo.state, 'RUNNING')
        self.assertEqual(self.pomo.total_pause, 92)
        self.assertEqual(self.pomo.end_time, deadline + 92)

    def test_cancel_counts_current_pause(self):
        self.start_timer()
        self.hold(['shaka'], 12)
        events = self.hold(['shaka', 'shaka'], 20)
        history = next(p for a, p in events if a == 'HISTORY')
        self.assertEqual(history[0], '25/5')
        self.assertIn('Dừng: 8s', history[2])
        self.assertIn('Hủy: CÓ', history[2])
        self.assertEqual(self.pomo.state, 'IDLE')

    def test_finish_only_once(self):
        self.start_timer()
        events = self.pomo.update([], self.pomo.end_time)[1]
        self.assertEqual(len(events), 1)
        self.assertIn('Hủy: KHÔNG', events[0][1][2])
        self.assertEqual(self.pomo.update([], 10000)[1], [])

    def test_idle_pointing_does_not_block_ocr(self):
        self.assertEqual(self.pomo.update([1], 0), (False, []))


if __name__ == '__main__':
    unittest.main()
