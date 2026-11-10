import ast
from pathlib import Path
from queue import Queue
from threading import Event, Lock
import unittest
from unittest.mock import Mock

TREE = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())


class SpeechTests(unittest.TestCase):
    def make_scope(self):
        scope = {"subprocess": Mock(), "lookup_lock": Lock(), "word_cache": {},
                 "pending_words": set(), "time": Mock(),
                 "stop_event": Event(), "ui_events": Queue()}
        nodes = [n for n in TREE.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"speak_word", "lookup_worker"}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "main.py", "exec"), scope)
        return scope

    def test_say_nonblocking(self):
        scope = self.make_scope()
        scope["speak_word"](" injection ")
        scope["subprocess"].Popen.assert_called_once_with(["say", "injection"])
        scope["subprocess"].Popen.return_value.wait.assert_not_called()
        scope["speak_word"](" ")
        scope["subprocess"].Popen.assert_called_once()

    def test_worker_print_before_say(self):
        scope = self.make_scope()
        events = []
        def lookup(word):
            events.append("print")
            scope["word_cache"][word] = "formatted"
        scope["lookup_word"] = lookup
        scope["subprocess"].Popen.side_effect = lambda args: events.append(args)
        jobs = Queue()
        jobs.put("injection")
        jobs.put(None)
        scope["lookup_worker"](jobs)
        self.assertEqual(events, ["print", ["say", "injection"]])
        self.assertEqual(jobs.unfinished_tasks, 0)

    def test_unknown_word_not_spoken(self):
        scope = self.make_scope()
        scope["lookup_word"] = Mock()
        jobs = Queue()
        jobs.put("unknown")
        jobs.put(None)
        scope["lookup_worker"](jobs)
        scope["subprocess"].Popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
