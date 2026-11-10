"""Anki integration for the CSV export workflow; no GUI calls."""

from html import escape

from anki_demo import call_anki


DECK_NAME = "My_English_Vocab"
MODEL_NAME = "Basic"  # Đổi nếu note type trên máy có tên khác.
FRONT_FIELD = "Front"  # Có thể đổi thành "Mặt trước".
BACK_FIELD = "Back"    # Có thể đổi thành "Mặt sau".


def export_to_anki_via_api(vocab_list):
    """Return a report; transport/API errors never escape into the GUI.

    call_anki uses requests.post to localhost:8765, API v6, timeout=(3, 20).
    No automatic retries: a timeout may occur after Anki has added notes.
    """
    report = {"ok": False, "total": 0, "added": 0, "not_added": [], "error": None}
    try:
        rows = [dict(row) for row in vocab_list]
        report["total"] = len(rows)
        if not rows:
            report["ok"] = True
            return report
        notes = []
        words = []
        for row in rows:
            def clean(key):
                return " ".join(str(row.get(key) or "").split())

            word, meaning = clean("word"), clean("meaning")
            if not word or not meaning:
                raise ValueError("Mỗi từ cần có word và meaning không rỗng.")
            words.append(word)
            notes.append({
                "deckName": DECK_NAME,
                "modelName": MODEL_NAME,
                "fields": {
                    FRONT_FIELD: escape(word),
                    BACK_FIELD: (
                        f"<b>IPA:</b> {escape(clean('ipa') or 'N/A')}<br>"
                        f"<i>{escape(clean('part_of_speech') or clean('word_type') or 'N/A')}</i><br><br>"
                        f"{escape(meaning)}"
                    ),
                },
                "options": {"allowDuplicate": False},
                "tags": ["english_vocab", "desktop_app"],
            })
        fields = call_anki("modelFieldNames", {"modelName": MODEL_NAME})
        if not isinstance(fields, list) or not {FRONT_FIELD, BACK_FIELD} <= set(fields):
            raise ValueError(
                f"Note type '{MODEL_NAME}' cần trường '{FRONT_FIELD}' và '{BACK_FIELD}'. "
                "Sửa cấu hình trong anki_service.py cho khớp Anki."
            )
        call_anki("createDeck", {"deck": DECK_NAME})
        ids = call_anki("addNotes", {"notes": notes})
        if not isinstance(ids, list) or len(ids) != len(notes):
            raise ValueError("Kết quả không hợp lệ; kiểm tra Anki trước khi thử lại.")
        report["added"] = sum(note_id is not None for note_id in ids)
        report["not_added"] = [word for word, note_id in zip(words, ids) if note_id is None]
        report["ok"] = not report["not_added"]
        if report["not_added"]:
            report["error"] = "Một số từ không được thêm (có thể trùng hoặc bị từ chối)."
    except Exception as error:
        report["error"] = str(error)
    return report
