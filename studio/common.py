import hashlib
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREATIVE = ROOT / "creative"
CAST = ("Đen", "Vằn")


def read(path):
    return path.read_text(encoding="utf-8-sig")


def load(path):
    return json.loads(read(path))


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def save(path, value):
    if isinstance(value, (dict, list)):
        value = encoded(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(value)
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def signature(*values):
    return hashlib.sha256(encoded(values).encode()).hexdigest()


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def cached(path, make):
    if not path.is_file():
        save(path, make())
    return path


def nonempty(obj, fields):
    if not isinstance(obj, dict) or any(not isinstance(obj.get(k), str) or not obj[k].strip() for k in fields):
        raise ValueError("Thiếu trường văn bản bắt buộc: " + ", ".join(fields))


def validate_shots(shots, seconds):
    if not isinstance(shots, list) or not shots:
        raise ValueError("Cảnh phải có danh sách shot.")
    for shot in shots:
        nonempty(shot, ("visual", "action", "camera", "sound", "continuity"))
        d = shot.get("duration")
        if type(d) is not int or not 3 <= d <= 10:
            raise ValueError("Mỗi shot cần thời lượng nguyên 3–10 giây.")
        cast = shot.get("cast")
        if not isinstance(cast, list) or any(c not in CAST for c in cast) or len(set(cast)) != len(cast):
            raise ValueError("cast chỉ nhận Đen và Vằn có mặt trong hình.")
        lines = shot.get("lines")
        if not isinstance(lines, list):
            raise ValueError("lines phải là danh sách, kể cả khi shot im lặng.")
        prior = 0
        for line in lines:
            nonempty(line, ("who", "text"))
            start, end = line.get("start"), line.get("end")
            if (line["who"] not in CAST or type(start) not in (float, int) or type(end) not in (float, int)
                    or not prior <= start < end <= d):
                raise ValueError("Sai nhân vật hoặc mốc thoại chồng nhau/vượt shot.")
            prior = end
    if sum(s["duration"] for s in shots) != seconds:
        raise ValueError(f"Tổng thời lượng shot phải bằng {seconds} giây của cảnh.")
