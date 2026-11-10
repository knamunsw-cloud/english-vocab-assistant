"""Tải từ điển Anh–Việt SQLite; không thay đổi main.py.

Cài dependency: python -m pip install requests
Chạy: python download_dict.py
File được lưu trong thư mục hiện tại của Terminal.
"""

import json
from pathlib import Path
import sqlite3
import tempfile

import requests


REPOSITORY = "skypediacode/english-vietnamese-dictionary"
BASE_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main"
DATA_URL = f"{BASE_URL}/dictionary_en_vi.db"
OUTPUT_NAME = "offline_dict.db"


def download(url, destination):
    """Tải streaming, giữ xác thực HTTPS, dừng nếu lỗi hoặc file quá lớn."""
    size = 0
    with requests.get(url, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        with destination.open("xb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    size += len(chunk)
                    if size > 250 * 1024 * 1024:
                        raise ValueError("Dữ liệu vượt giới hạn 250 MB")
                    file.write(chunk)
    if not size:
        raise ValueError("Server trả về file rỗng")
    return size


def inspect_database(path):
    """Mở read-only và lấy mẫu theo schema công bố của nguồn dữ liệu."""
    with path.open("rb") as file:
        if file.read(16) != b"SQLite format 3\x00":
            raise ValueError("File tải về không phải SQLite (có thể là HTML/LFS pointer)")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Database không vượt qua kiểm tra toàn vẹn")
        connection.row_factory = sqlite3.Row
        count = connection.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        row = connection.execute(
            "SELECT id, word FROM words WHERE word = ? LIMIT 1", ("injection",)
        ).fetchone()
        if row is None:
            row = connection.execute("SELECT id, word FROM words ORDER BY id LIMIT 1").fetchone()
        if row is None:
            raise ValueError("Từ điển không có mục từ")
        definitions = connection.execute(
            "SELECT d.definition, d.pos, d.sub_pos, wd.example "
            "FROM word_definitions wd "
            "JOIN definitions d ON d.id = wd.definition_id "
            "WHERE wd.word_id = ? LIMIT 5", (row["id"],)
        ).fetchall()
        pronunciations = connection.execute(
            "SELECT ipa, region FROM pronunciations WHERE word_id = ?", (row["id"],)
        ).fetchall()
        return count, {
            "word": row["word"],
            "pronunciations": [dict(item) for item in pronunciations],
            "definitions": [dict(item) for item in definitions],
        }
    finally:
        connection.close()


def main():
    output_dir = Path.cwd()
    output = output_dir / OUTPUT_NAME
    if output.exists():
        print(f"File đã tồn tại; không tải đè: {output}")
        count, sample = inspect_database(output)
    else:
        print(f"Nguồn: https://github.com/{REPOSITORY}")
        print(f"Đang tải: {DATA_URL}")
        # File tạm cùng ổ đĩa, chỉ công bố sau khi tải và kiểm tra thành công.
        with tempfile.TemporaryDirectory(prefix="dict-download-", dir=output_dir) as temp:
            temp_dir = Path(temp)
            temporary = temp_dir / OUTPUT_NAME
            size = download(DATA_URL, temporary)
            count, sample = inspect_database(temporary)
            for remote, local in (
                ("LICENSE", "offline_dict.LICENSE.txt"),
                ("ATTRIBUTION.md", "offline_dict.ATTRIBUTION.md"),
            ):
                target = output_dir / local
                if not target.exists():
                    staged = temp_dir / local
                    download(f"{BASE_URL}/{remote}", staged)
                    # Hard link tạo đích mới, không ghi đè nếu có tiến trình khác tạo file.
                    target.hardlink_to(staged)
            output.hardlink_to(temporary)
        print(f"Đã tải {size / 1024 / 1024:.1f} MB vào: {output}")
    print(f"Số mục từ: {count:,}")
    print("Mẫu dữ liệu (tối đa 5 định nghĩa):")
    print(json.dumps(sample, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (requests.RequestException, OSError, sqlite3.Error, ValueError) as error:
        print(f"Không tải/đọc được từ điển: {error}")
        raise SystemExit(1)
