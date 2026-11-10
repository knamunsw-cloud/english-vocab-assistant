"""Demo xuất 10 từ vựng sang Anki Desktop qua AnkiConnect.

Chạy: python anki_demo.py
Anki Desktop phải mở và đã cài add-on AnkiConnect.
"""

import random
from html import escape

import requests


ANKI_URL = "http://localhost:8765"
DECK_NAME = "My_English_Vocab"


def get_mock_vocab_data():
    """Lấy ngẫu nhiên 10 từ không trùng từ bộ dữ liệu mẫu."""
    samples = [
        ("discover", "khám phá", "/dɪˈskʌvər/", "Verb"),
        ("knowledge", "kiến thức", "/ˈnɑːlɪdʒ/", "Noun"),
        ("confident", "tự tin", "/ˈkɑːnfɪdənt/", "Adjective"),
        ("improve", "cải thiện", "/ɪmˈpruːv/", "Verb"),
        ("journey", "hành trình", "/ˈdʒɜːrni/", "Noun"),
        ("carefully", "một cách cẩn thận", "/ˈkerfəli/", "Adverb"),
        ("achieve", "đạt được", "/əˈtʃiːv/", "Verb"),
        ("curious", "tò mò", "/ˈkjʊriəs/", "Adjective"),
        ("opportunity", "cơ hội", "/ˌɑːpərˈtuːnəti/", "Noun"),
        ("remember", "ghi nhớ", "/rɪˈmembər/", "Verb"),
        ("patient", "kiên nhẫn", "/ˈpeɪʃənt/", "Adjective"),
        ("frequently", "thường xuyên", "/ˈfriːkwəntli/", "Adverb"),
    ]
    return [
        {"word": word, "meaning": meaning, "ipa": ipa, "part_of_speech": word_type}
        for word, meaning, ipa, word_type in random.sample(samples, 10)
    ]


def call_anki(action, params=None):
    """Gọi AnkiConnect; không tự retry để tránh thêm thẻ lặp."""
    payload = {"action": action, "version": 6, "params": params or {}}
    try:
        with requests.post(ANKI_URL, json=payload, timeout=(3, 20)) as response:
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("AnkiConnect trả về JSON không hợp lệ.") from exc
    except requests.Timeout as exc:
        raise RuntimeError(
            "AnkiConnect phản hồi quá lâu. Kiểm tra Anki trước khi thử lại "
            "vì một số thẻ có thể đã được thêm."
        ) from exc
    except requests.ConnectionError as exc:
        raise RuntimeError(
            "Không kết nối được AnkiConnect. Hãy mở Anki Desktop, "
            "cài/bật add-on AnkiConnect và khởi động lại Anki."
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Lỗi HTTP khi gọi AnkiConnect: {exc}") from exc

    if not isinstance(data, dict) or not {"result", "error"} <= data.keys():
        raise RuntimeError("Cấu trúc phản hồi AnkiConnect không hợp lệ.")
    if data["error"] is not None:
        raise RuntimeError(f"AnkiConnect: {data['error']}")
    return data["result"]


def build_note(vocab):
    """Escape nội dung để HTML chỉ dùng cho định dạng, không thực thi dữ liệu."""
    def text(key):
        return " ".join(str(vocab.get(key) or "").split())

    word = text("word")
    meaning = text("meaning")
    ipa = text("ipa") or "N/A"
    word_type = text("part_of_speech") or "N/A"
    if not word or not meaning:
        raise ValueError("Mỗi từ phải có 'word' và 'meaning' không rỗng.")
    return {
        "deckName": DECK_NAME,
        "modelName": "Basic",
        "fields": {
            "Front": escape(word),
            "Back": (
                f"<b>IPA:</b> {escape(ipa)}<br>"
                f"<i>{escape(word_type)}</i><br><br>"
                f"{escape(meaning)}"
            ),
        },
        "options": {"allowDuplicate": False},
        "tags": ["english_vocab", "python_app"],
    }


def export_to_anki(vocab_list):
    """Trả kết quả từng từ; không tự xóa dữ liệu nguồn nếu thành công một phần."""
    vocab_list = list(vocab_list)
    if not vocab_list:
        return []
    notes = [build_note(vocab) for vocab in vocab_list]
    fields = call_anki("modelFieldNames", {"modelName": "Basic"})
    if not isinstance(fields, list) or not {"Front", "Back"} <= set(fields):
        raise RuntimeError(
            "Cần Note Type tên 'Basic' với hai trường 'Front' và 'Back'. "
            "Kiểm tra tên note type nếu Anki đang dùng ngôn ngữ khác."
        )
    call_anki("createDeck", {"deck": DECK_NAME})
    note_ids = call_anki("addNotes", {"notes": notes})
    if not isinstance(note_ids, list) or len(note_ids) != len(notes):
        raise RuntimeError("Kết quả thêm thẻ không hợp lệ. Kiểm tra Anki trước khi thử lại.")
    return [
        {
            "word": vocab["word"],
            "note_id": note_id,
            "status": "added" if note_id is not None else "not_added",
        }
        for vocab, note_id in zip(vocab_list, note_ids)
    ]


def main():
    try:
        results = export_to_anki(get_mock_vocab_data())
        added = sum(item["status"] == "added" for item in results)
        print(f"Đã thêm {added}/{len(results)} từ vào deck '{DECK_NAME}'.")
        for item in results:
            if item["status"] == "not_added":
                print(f"Không thêm được: {item['word']} (có thể trùng từ hoặc bị Anki từ chối).")
    except (RuntimeError, ValueError) as error:
        print(f"Lỗi: {error}")


if __name__ == "__main__":
    main()
