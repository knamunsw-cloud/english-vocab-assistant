import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vocab_services as services


class SQLiteDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "dict.db"
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE words(id INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE pronunciations(id INTEGER PRIMARY KEY, word_id INTEGER, ipa TEXT);
            CREATE TABLE definitions(id INTEGER PRIMARY KEY, definition TEXT, pos TEXT);
            CREATE TABLE word_definitions(id INTEGER PRIMARY KEY, word_id INTEGER, definition_id INTEGER);
            INSERT INTO words VALUES(1,'test'),(2,'empty');
            INSERT INTO pronunciations VALUES(1,1,'/test/'),(2,1,'/test/'),(3,1,'/other/');
            INSERT INTO definitions VALUES(1,'kiểm tra','V'),(2,'bài thi','N'),(3,'kiểm tra','V');
            INSERT INTO word_definitions VALUES(1,1,1),(2,1,2),(3,1,3);
        """)
        con.close()
        self.patch = patch.object(services, "DB_PATH", self.db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        fallback_patch = patch.object(services, "translate_fallback", return_value=None)
        self.fallback = fallback_patch.start()
        self.addCleanup(fallback_patch.stop)

    def test_recursive_root_and_cycle(self):
        with sqlite3.connect(self.db) as con:
            con.executescript("""
                INSERT INTO words VALUES(3,'tests'),(4,'loop');
                INSERT INTO definitions VALUES(4,'Số nhiều của test.','N'),
                    (5,'Quá khứ của loop','V');
                INSERT INTO word_definitions VALUES(4,3,4),(5,4,5);
            """)
        result = services.query_vocabulary('tests')
        self.assertIn('kiểm tra, bài thi', result['meaning'])
        self.assertEqual(result['word'], 'tests')
        self.assertTrue(services.query_vocabulary('loop')['found'])
        self.fallback.assert_not_called()

    def test_online_only_for_missing(self):
        self.fallback.return_value = 'nghĩa dự phòng'
        self.assertEqual(services.query_vocabulary('unknown')['meaning'], 'nghĩa dự phòng')
        self.fallback.assert_called_once_with('unknown')
        services.query_vocabulary('test')
        self.fallback.assert_called_once()

    def test_lemma_noun_then_verb(self):
        for forms in (("test", "testing"), ("testing", "test")):
            with self.subTest(forms=forms), patch.object(
                services.lemmatizer, "lemmatize", side_effect=forms
            ):
                result = services.query_vocabulary("testing")
            self.assertTrue(result["found"])
            self.assertEqual(result["word"], "testing")
            self.assertIn("(từ gốc: test)", result["meaning"])
        self.fallback.assert_not_called()

    def test_missing_wordnet_still_calls_api(self):
        with patch.object(services.lemmatizer, "lemmatize", side_effect=LookupError):
            services.query_vocabulary("unknown")
        self.fallback.assert_called_once_with("unknown")

    def test_fields_and_dedup(self):
        result = services.query_vocabulary(" TEST ")
        self.assertTrue(result["found"])
        self.assertEqual(result["ipa"], "/test/, /other/")
        self.assertEqual(result["word_type"], "Verb, Noun")
        self.assertEqual(result["meaning"], "kiểm tra, bài thi")

    def test_missing_and_parameterized_query(self):
        for word in ("unknown", "test' OR 1=1 --", ""):
            result = services.query_vocabulary(word)
            self.assertFalse(result["found"])
            self.assertEqual(result["meaning"], "Không có trong từ điển")

    def test_null_fields(self):
        result = services.query_vocabulary("empty")
        self.assertTrue(result["found"])
        self.assertEqual(result["ipa"], "N/A")
        self.assertEqual(result["word_type"], "N/A")

    def test_missing_database_does_not_create_file(self):
        missing = self.db.with_name("missing.db")
        with patch.object(services, "DB_PATH", missing):
            result = services.query_vocabulary("test")
        self.assertFalse(result["found"])
        self.assertFalse(missing.exists())
        self.assertEqual(result["meaning"], "Không đọc được từ điển SQLite")

    def test_worker_threads(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(services.query_vocabulary, ["test"] * 6))
        self.assertTrue(all(r["found"] for r in results))

    def test_main_format(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch_vocab_info")
        scope = {"query_vocabulary": services.query_vocabulary}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"), scope)
        formatted, found = scope["fetch_vocab_info"]("test")
        self.assertTrue(found)
        self.assertEqual(formatted.splitlines(), [
            "[Vocab: test]", "Word IPA: /test/, /other/",
            "Word type: Verb, Noun", "Vietnamese meaning: kiểm tra, bài thi",
        ])


if __name__ == "__main__":
    unittest.main()
