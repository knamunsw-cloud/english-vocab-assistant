"""Ưu tiên SQLite; chỉ dịch online khi không tìm thấy từ trong DB."""

from contextlib import closing
from pathlib import Path
import sqlite3
import re
import requests
import time
from threading import Lock
from nltk.stem import WordNetLemmatizer

lemmatizer = WordNetLemmatizer()
_api_lock = Lock()
_api_retry_at = 0.0


DB_PATH = Path(__file__).resolve().parent / "offline_dict.db"
POS_NAMES = {
    "n": "Noun", "noun": "Noun",
    "v": "Verb", "verb": "Verb",
    "a": "Adjective", "adj": "Adjective",
    "d": "Adverb", "adv": "Adverb",
    "pron": "Pronoun", "idiom": "Idiom", "name": "Proper noun",
}


def join_unique(values):
    """Loại trùng, giữ nguyên thứ tự và giữ mỗi trường trên một dòng."""
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = " ".join(value.split())
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return ", ".join(result)


def _query_sqlite(word):
    word = word.strip().lower()
    result = {
        "word": word, "ipa": "N/A", "word_type": "N/A",
        "meaning": "Không có trong từ điển", "found": False,
    }
    if not word:
        return result
    try:
        # Mỗi lần cache miss dùng connection riêng: an toàn với Queue worker.
        # mode=ro không tạo DB rỗng nếu file bị thiếu; closing luôn đóng kết nối.
        uri = DB_PATH.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            with connection:
                words = connection.execute(
                    "SELECT id FROM words WHERE word = ? ORDER BY id", (word,)
                ).fetchall()
                if not words:
                    return result
                pronunciations, definitions, parts = [], [], []
                for (word_id,) in words:
                    pronunciations.extend(
                        row[0] for row in connection.execute(
                            "SELECT ipa FROM pronunciations WHERE word_id = ? ORDER BY id",
                            (word_id,),
                        )
                    )
                    # Query riêng tránh nhân bản định nghĩa khi có nhiều IPA.
                    rows = connection.execute(
                        "SELECT d.definition, d.pos FROM word_definitions wd "
                        "JOIN definitions d ON d.id = wd.definition_id "
                        "WHERE wd.word_id = ? ORDER BY wd.id", (word_id,),
                    )
                    for definition, pos in rows:
                        # Bỏ dấu chấm kết thúc trước khi ghép bằng dấu phẩy.
                        definitions.append(definition.strip().rstrip(".")
                                           if isinstance(definition, str) else definition)
                        if isinstance(pos, str) and pos.strip():
                            code = pos.strip()
                            parts.append(POS_NAMES.get(code.lower(), code))
                result.update(
                    ipa=join_unique(pronunciations) or "N/A",
                    word_type=join_unique(parts) or "N/A",
                    meaning=join_unique(definitions) or "Không có trong từ điển",
                    found=True,
                )
    except (sqlite3.Error, OSError, ValueError):
        result["meaning"] = "Không đọc được từ điển SQLite"
    return result


ROOT_PATTERN = re.compile(
    r"(?:số nhiều|quá khứ(?:\s+đơn)?|phân từ(?:\s+(?:quá khứ|hiện tại))?)"
    r"\s+của\s+[\s\"'“‘*]*([a-zA-Z]+(?:[-'][a-zA-Z]+)*)(?!\w)",
    re.IGNORECASE,
)


def _resolve_sqlite(word, visited=None):
    visited = set() if visited is None else set(visited)
    result = _query_sqlite(word)
    if not result["found"] or word in visited or len(visited) >= 8:
        return result
    visited.add(word)
    resolved = []
    for match in ROOT_PATTERN.finditer(result["meaning"]):
        root = match.group(1).lower()
        if root in visited:
            continue
        base = _resolve_sqlite(root, visited)
        if base["found"] and base["meaning"] != "Không có trong từ điển":
            resolved.append(base["meaning"])
    if resolved:
        # Giữ IPA/từ loại của từ đã quét và mọi nghĩa độc lập sẵn có.
        result["meaning"] = join_unique([result["meaning"], *resolved])
    return result


def translate_fallback(word):
    global _api_retry_at
    # Không để lỗi mạng lặp lại làm nghẽn worker tra SQLite.
    with _api_lock:
        if time.monotonic() < _api_retry_at:
            return None
        _api_retry_at = time.monotonic() + 1.0
    try:
        with requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "tw-ob", "sl": "en", "tl": "vi", "dt": "t", "q": word},
            timeout=(1.5, 2.0),
        ) as response:
            if response.status_code == 429:
                with _api_lock:
                    _api_retry_at = time.monotonic() + 60
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, list) or not data or not isinstance(data[0], list):
            return None
        parts = [segment[0] for segment in data[0]
                 if isinstance(segment, list) and segment
                 and isinstance(segment[0], str)]
        return "".join(parts).strip() or None
    except (requests.RequestException, ValueError, TypeError):
        with _api_lock:
            _api_retry_at = max(_api_retry_at, time.monotonic() + 30)
        return None


def query_vocabulary(word):
    word = word.strip().lower()
    result = _resolve_sqlite(word)
    # 1. Ưu tiên kết quả nguyên bản.
    if result["found"] or not word:
        return result

    # 2. Thiếu WordNet không được chặn bước gọi API dự phòng.
    try:
        word_n = lemmatizer.lemmatize(word, "n")
        word_v = lemmatizer.lemmatize(word, "v")
    except (LookupError, OSError):
        word_n = word_v = word

    checked = {word}
    for root in (word_n, word_v):
        if root in checked:
            continue
        checked.add(root)
        base = _resolve_sqlite(root)
        if base["found"]:
            return {
                **base,
                "word": word,
                "ipa": "N/A",  # IPA của từ gốc không phải IPA của từ đã quét.
                "meaning": f"(từ gốc: {root}) {base['meaning']}",
            }

    # 3. Luôn thử Google khi cả nguyên bản lẫn hai từ gốc đều không có.
    meaning = translate_fallback(word)
    if meaning:
        result.update(meaning=meaning, found=True)
    return result
