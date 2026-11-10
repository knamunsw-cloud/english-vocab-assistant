import ast
import math
from pathlib import Path
import unittest
from unittest.mock import Mock


class StablePointerTimingTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'StablePointer')
        self.clock = Mock()
        scope = {'math': math, 'time': self.clock, 'OCR_STABLE_SECONDS': .45,
                 'OCR_MOVEMENT_TOLERANCE': 14}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        self.pointer = scope['StablePointer']()

    def update(self, now, point=(100, 100), hand='Left'):
        self.clock.monotonic.return_value = now
        return self.pointer.update(point, hand)

    def test_time_not_frame_count(self):
        self.assertFalse(self.update(0))
        self.assertFalse(self.update(.44))
        self.assertTrue(self.update(.46))
        self.pointer.triggered = True
        self.assertFalse(self.update(2))

    def test_small_jitter_and_large_move(self):
        self.update(0)
        generation = self.pointer.generation
        self.assertTrue(self.update(.5, (110, 100)))
        self.assertEqual(self.pointer.generation, generation)
        self.assertFalse(self.update(.6, (120, 100)))
        self.assertGreater(self.pointer.generation, generation)
        self.assertTrue(self.update(1.1, (120, 100)))

    def test_release_requires_new_hold(self):
        self.update(0)
        self.assertTrue(self.update(.5))
        self.update(.6, None)
        self.assertFalse(self.update(1))
        self.assertTrue(self.update(1.5))


if __name__ == '__main__':
    unittest.main()
