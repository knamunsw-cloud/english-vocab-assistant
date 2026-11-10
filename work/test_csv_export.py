import ast
import csv
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class CSVExportTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'vocab_ui.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'export_saved_words')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project_dir = Path(self.temp.name)
        scope = {'csv': csv, 'datetime': datetime, 'Path': Path,
                 '__file__': str(self.project_dir / 'vocab_ui.py')}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'vocab_ui.py', 'exec'), scope)
        self.export = scope['export_saved_words']
        self.row = [1, 'injection', 'Noun', '/ɪnˈdʒekʃn/', 'Sự tiêm, thuốc tiêm']
        self.widget = Mock()
        self.ui = SimpleNamespace(
            saved_words_data=[self.row[:]], saved_count=1,
            saved_panel=Mock(), saved_list_label=Mock(), export_notice_after=None,
            after=Mock(), after_cancel=Mock(), restore_saved_title=Mock(),
            start_anki_export=Mock(),
        )
        self.ui.saved_panel.winfo_children.return_value = [self.widget]

    def test_utf8_bom_and_reset(self):
        with patch.object(Path, 'cwd', side_effect=AssertionError('Must not depend on cwd')):
            self.export(self.ui)
            files = list((self.project_dir / 'Vocab Export').glob('vocab_export_*.csv'))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].read_bytes().startswith(b'\xef\xbb\xbf'))
            with files[0].open(encoding='utf-8-sig', newline='') as file:
                rows = list(csv.reader(file))
            self.assertEqual(rows[1], [str(x) for x in self.row])
        self.assertEqual(self.ui.saved_words_data, [])
        self.assertEqual(self.ui.saved_count, 0)
        self.widget.destroy.assert_called_once()
        vocab_list, csv_path = self.ui.start_anki_export.call_args.args
        self.assertTrue(Path(csv_path).name.startswith('vocab_export_'))
        self.assertEqual(vocab_list[0]['meaning'], self.row[4])

    def test_failure_preserves_data(self):
        with patch.object(Path, 'open', side_effect=PermissionError('denied')), patch('builtins.print'):
            self.export(self.ui)
        self.assertEqual(self.ui.saved_words_data, [self.row])
        self.widget.destroy.assert_not_called()
        self.ui.start_anki_export.assert_not_called()

    def test_empty_no_file(self):
        self.ui.saved_words_data.clear()
        with patch.object(Path, 'open') as opened:
            self.export(self.ui)
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
