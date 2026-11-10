import ast
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock, Thread
from types import SimpleNamespace
import re
import time
import unittest
from unittest.mock import Mock


TREE = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())


class UIPipelineTests(unittest.TestCase):
    def scope(self):
        result = {"word": "injection", "ipa": "/ipa/", "word_type": "Noun",
                  "meaning": "Sự tiêm", "found": True}
        scope = {"ui_events": Queue(), "active_vocab_updates": Queue(), "video_frames": Queue(maxsize=1),
                 "Empty": Empty, "Full": Full, "re": re, "time": time,
                 "lookup_lock": Lock(), "word_cache": {}, "last_word": "",
                 "last_call_time": 0, "query_vocabulary": Mock(return_value=result)}
        nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"update_ui", "publish_frame", "lookup_word"}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), scope)
        return scope

    def test_background_lookup_queues_fields_and_cache(self):
        scope = self.scope()
        thread = Thread(target=scope["lookup_word"], args=(" Injection! ",))
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(scope["ui_events"].get_nowait(),
                         ("vocab", ("injection", "/ipa/", "Noun", "Sự tiêm")))
        scope["lookup_word"]("injection")
        scope["query_vocabulary"].assert_called_once()
        self.assertEqual(scope["active_vocab_updates"].get_nowait(), ("injection", "Noun", "/ipa/", "Sự tiêm"))
        self.assertEqual(scope["active_vocab_updates"].get_nowait(), ("injection", "Noun", "/ipa/", "Sự tiêm"))

    def test_preview_keeps_latest(self):
        scope = self.scope()
        for frame in range(100):
            scope["publish_frame"](frame)
        self.assertEqual(scope["video_frames"].qsize(), 1)
        self.assertEqual(scope["video_frames"].get_nowait(), 99)

    def test_no_opencv_gui_calls(self):
        forbidden = {"imshow", "waitKey", "namedWindow", "destroyAllWindows"}
        for node in ast.walk(TREE):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "cv2":
                    self.assertNotIn(node.func.attr, forbidden)


if __name__ == "__main__":
    unittest.main()
