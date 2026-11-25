import re
from html import escape
from . import providers
from .common import CAST, CREATIVE, cached, digest, encoded, load, nonempty, read, save, signature, validate_shots


LOCATION_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def location_code(value):
    return isinstance(value, str) and len(value) <= 48 and LOCATION_ID.fullmatch(value) is not None


def inherited_locations(ep):
    return {path.stem: path for path in sorted((ep / "locations").glob("*.png"))
            if path.is_file() and location_code(path.stem)}


def world_context(ep):
    known = ", ".join(inherited_locations(ep)) or "chưa có ảnh bối cảnh đã duyệt"
    return read(ep / "bible.md") + "\nMã các địa điểm đã duyệt: " + known


def role(*names):
    agents = load(CREATIVE / "agents.json")
    return "\n".join(agents[name] for name in names)


def episode_script(ep):
    prior = ep / "tap-truoc.md"
    direction = world_context(ep) + "\n" + read(ep / "dinh-huong.md")
    if prior.exists():
        direction += "\nKịch bản tập trước dùng để giữ liên tục; hãy kể một diễn biến mới:\n" + read(prior)
    idea = cached(ep / "y-tuong.md", lambda: providers.response(role("producer", "story"),
                  direction + "\nĐưa 3 ý tưởng và chọn 1 đề xuất bám sát định hướng."))
    return cached(ep / "kich-ban.md", lambda: providers.response(role("story"),
                  direction + "\n" + read(idea)
                  + "\nViết toàn bộ kịch bản tiếng Việt 8–10 phút, gồm các nhịp có timecode, hành động và từng lời thoại. Mỗi dòng thoại theo mẫu **Đen** — lời nói hoặc **Vằn** — lời nói. Ghi Chờ chủ dự án duyệt."))


def check_dialogue(script, shots):
    expected = re.findall(r"^\*\*(Đen|Vằn)\*\*\s*—\s*(.+)$", script, re.M)
    if expected:
        actual = [(line["who"], line["text"].strip()) for s in shots for line in s["lines"]]
        expected = [(c, line.strip()) for c, line in expected]
        if expected != actual:
            index = next((i for i, (x, y) in enumerate(zip(expected, actual)) if x != y), min(len(expected), len(actual)))
            raise ValueError(f"Lượt thoại {index+1} khác kịch bản. Kiểm tra người nói, nguyên văn và thứ tự trong shots.json.")


def script_key(ep):
    return signature(*(digest(ep / n) for n in ("kich-ban.md", "bible.md", "dinh-huong.md")))


def timed_outline(script):
    headings = list(re.finditer(r"^#{2,3}\s+(\d\d):(\d\d)\s*[–—-]\s*(\d\d):(\d\d)\s*[·|—-]\s*(.+)$", script, re.M))
    scenes = []
    prior = 0
    for i, heading in enumerate(headings):
        m1, s1, m2, s2 = map(int, heading.groups()[:4])
        start, end = 60*m1+s1, 60*m2+s2
        if start != prior or s1 >= 60 or s2 >= 60 or end <= start:
            return None
        stop = headings[i+1].start() if i+1 < len(headings) else len(script)
        scenes.append({"name": heading[5].strip(), "content": script[heading.end():stop].strip(), "seconds": end-start})
        prior = end
    return {"scenes": scenes} if scenes else None


def checked_json(path, instructions, task, validate):
    if path.exists():
        obj = load(path)
        validate(obj)
        return obj
    last_error = ""
    for _ in range(2):
        obj = providers.response(instructions, task + last_error, structured=True)
        try:
            validate(obj)
        except (ValueError, TypeError, KeyError) as exc:
            last_error = "\nSửa lỗi lần trước: " + str(exc)
            save(path.with_suffix(".invalid.json"), obj)
            continue
        save(path, obj)
        return obj
    raise ValueError(f"{path.name}: {last_error}. Xem bản .invalid.json và chạy lại.")


def validate_outline(obj):
    scenes = obj["scenes"]
    if not isinstance(scenes, list) or not 6 <= len(scenes) <= 14:
        raise ValueError("Cần 6–14 cảnh.")
    for scene in scenes:
        nonempty(scene, ("name", "content"))
        if type(scene.get("seconds")) is not int or not 20 <= scene["seconds"] <= 120:
            raise ValueError("Mỗi cảnh cần 20–120 giây nguyên.")
    if not 480 <= sum(s["seconds"] for s in scenes) <= 600:
        raise ValueError("Tổng các cảnh cần đạt 480–600 giây.")


def plan(ep, folder):
    script = read(ep / "kich-ban.md")
    outline_path = folder / "canh.json"
    outline = timed_outline(script)
    if outline and not outline_path.exists():
        try:
            validate_outline(outline)
        except ValueError:
            pass
        else:
            save(outline_path, outline)
    task = (script + '\nTrả JSON {"scenes":[{"name":"...","content":"...","seconds":60}]}. '
            'Trích đủ từng dòng thoại nguyên văn theo định dạng gốc trong content. 6–14 cảnh, '
            'mỗi cảnh 20–120 giây nguyên, tổng 480–600 giây.')
    scenes = checked_json(outline_path, role("planner"), task, validate_outline)["scenes"]
    shots = []
    prior = ""
    world = world_context(ep)
    known = set(inherited_locations(ep))
    for i, scene in enumerate(scenes, 1):
        task = (f"{world}\nKịch bản đã duyệt:\n{script}\nCảnh đang chia: {encoded(scene)}\nNối từ: {prior}\n"
                f"Các mã địa điểm đang dùng: {', '.join(sorted(known))}.\n"
                'Trả JSON {"shots":[{"duration":5,"location":"nha-mai-ngoi","cast":["Đen","Vằn"],"visual":"bố cục, thời gian, vị trí",'
                '"action":"hành động tự nhiên","camera":"góc và chuyển động máy","sound":"ambience/foley cụ thể",'
                '"continuity":"trạng thái cuối, hướng đi, vị trí đạo cụ","lines":[{"who":"Đen","text":"nguyên văn",'
                '"start":0,"end":4}]}]}. cast chỉ liệt kê ai nhìn thấy. Shot 3–10 giây nguyên. '
                'location là mã ASCII thường có gạch nối, tối đa 48 ký tự. Dùng đúng mã đã có khi quay lại cùng địa điểm. '
                'Sân, hiên và ngưỡng cửa thuộc cùng nhà mái ngói dùng mã nha-mai-ngoi dù đổi góc máy, thời tiết hoặc giờ. '
                'Chỉ đặt mã mới cho một nơi thực sự khác. '
                f"Tổng đúng {scene['seconds']} giây. Giữ mỗi câu thoại nguyên văn, dành đủ thời gian nói. Shot không thoại dùng [].")
        subset = folder / f"canh-{i:02d}-{signature(task)[:12]}.json"

        def validate(obj):
            validate_shots(obj["shots"], scene["seconds"])
            if any(not location_code(s.get("location")) for s in obj["shots"]):
                raise ValueError("Mỗi shot cần mã location hợp lệ.")
            check_dialogue(scene["content"], obj["shots"])

        group = checked_json(subset, role("planner", "voice", "visual"), task, validate)["shots"]
        for shot in group:
            known.add(shot["location"])
            shots.append(dict(shot, id=f"S{len(shots)+1:03d}", scene=scene["name"]))
        prior = group[-1]["continuity"]
    return shots


def reference_files(ep):
    data = load(ep / "refs.json") if (ep / "refs.json").exists() else {}
    result = {c: [] for c in CAST}
    for c in CAST:
        for name in data.get(c, []):
            path = (ep / "refs" / name).resolve()
            if path.parent != (ep / "refs").resolve() or not path.is_file():
                raise ValueError(f"Ảnh tham chiếu {c} không còn ở thư mục refs.")
            result[c].append(path)
    return result


def location_spec(ep, shots):
    places = {}
    inherited = inherited_locations(ep)
    notes_path = ep / "retakes.json"
    marks = load(notes_path) if notes_path.exists() else {}
    layout = world_context(ep)
    for shot in shots:
        code = shot.get("location")
        if code is None:
            continue  # Tương thích với shot list đã lưu trước khi có mã địa điểm.
        if not location_code(code):
            raise ValueError(f"Mã địa điểm không hợp lệ ở {shot['id']}.")
        if code in places:
            continue
        base = inherited.get(code)
        note = marks.get("location/" + code, {})
        if base and not note:
            places[code] = (base, None, "")
            continue
        if note.get("base"):
            source = (ep / note["base"]).resolve()
            if not source.is_relative_to(ep / "locations") or not source.is_file() or source.suffix != ".png":
                raise ValueError(f"Thiếu ảnh bối cảnh làm gốc để sửa {code}.")
            base = source
        prompt = ("Create one photorealistic 16:9 establishing reference image for this Vietnamese location. "
                  "Wide eye-level view, neutral daylight and clear landmarks. Empty location, no animals or people. "
                  "Show fixed architecture, paths, surfaces and spatial relationships so other angles can match. "
                  "Ignore temporary action, weather and movable props unless specified as a permanent landmark. "
                  f"Vietnamese location ID: {code}.\nLayout guide:\n{layout}"
                  f"\nShot context: {shot['visual']}\nRequested revision: {note.get('reason', '')}")
        key = signature(prompt, note, digest(base) if base else None)
        places[code] = (ep / "locations" / "drafts" / f"{code}-{key}.png", base, prompt)
    return places


def generate_locations(places):
    for path, base, prompt in places.values():
        cached(path, lambda: providers.frame(prompt, [base] if base else []))


def character_profile(ep, identity, name):
    return ep / "character" / (identity + "-" + name + ".md")


def board_spec(ep, shots, refs, locations):
    marks = load(ep / "retakes.json") if (ep / "retakes.json").exists() else {}
    ids = {c: [digest(p) for p in refs[c]] for c in CAST}
    identity = signature(ids, digest(ep / "bible.md"))
    location_hashes = {code: digest(path) for code, path in locations.items()}
    rows = []
    for shot in shots:
        note = marks.get("frame/" + shot["id"], {})
        code = shot.get("location")
        key = signature(shot, identity, note, location_hashes[code]) if code else signature(shot, identity, note)
        rows.append((shot, ep / "frames" / (key + ".png"), note))
    return identity, rows


def generate_frames(ep, identity, rows, refs, locations):
    profiles = {}
    visual_guide = read(ep / "bible.md")
    for char in CAST:
        f = cached(character_profile(ep, identity, char),
                   lambda: providers.response(role("character"),
                   f"Đây là ảnh thật của {char}. Ghi dấu nhận diện quan sát được và phần khuất chưa rõ, tiếng Việt.",
                   refs[char]))
        profiles[char] = read(f)
    for shot, path, note in rows:
        sources = [p for c in shot["cast"] for p in refs[c]]
        labels = [c for c in shot["cast"] for _ in refs[c]]
        place = locations.get(shot.get("location"))
        if place:
            sources.append(place)
        prompt = ("Create the opening frame BEFORE the action begins. Leave room for movement towards the described ending. "
                  "One photorealistic cinematic 16:9 film still in rural Vietnam. Natural quadruped anatomy. "
                  "No human face, human gestures, outfits, speech bubbles or letters. Preserve the identities in the attached references. "
                  + ("The last attached image is the location reference. Keep its landmarks, materials and spatial layout. "
                     "Follow the shot for camera angle, time, weather and movable props.\n" if place else "")
                  + ("Character reference image order: " + ", ".join(labels) + ".\n" if labels else "")
                  + "Series visual guide:\n" + visual_guide
                  + "\n" + "\n".join(c + ": " + profiles[c] for c in shot["cast"])
                  + "\n" + encoded({k: shot[k] for k in ("scene", "visual", "cast", "action", "camera", "continuity")})
                  + "\nGóp ý chỉnh hình: " + note.get("reason", ""))
        cached(path, lambda: providers.frame(prompt, sources))


def board_key(identity, rows):
    return signature(identity, [(s, digest(f)) for s, f, _ in rows]) if all(f.exists() for _, f, _ in rows) else None


def storyboard(ep, rows, refs, key, identity, locations):
    blocks = ['<!doctype html><html lang="vi"><meta charset="utf-8"><title>Storyboard | Đen &amp; Vằn</title>',
              '<style>body{max-width:1000px;margin:3rem auto;font:16px/1.6 system-ui;padding:0 1rem}img{width:min(100%,650px)}article{border-top:1px solid #aaa;padding:1rem 0}pre{white-space:pre-wrap}</style>',
              '<h1>Storyboard Đen &amp; Vằn</h1><p>Phiên bản ' + key + '</p>']
    for c in CAST:
        blocks.append('<h2>' + c + '</h2>')
        for p in refs[c]:
            blocks.append(f'<img style="width:180px" alt="{c}" src="{escape(p.relative_to(ep).as_posix())}">')
        blocks.append('<pre>' + escape(read(character_profile(ep, identity, c))) + '</pre>')
    if locations:
        blocks.append("<h2>Ảnh chuẩn bối cảnh</h2>")
        for code, path in locations.items():
            blocks.append(f'<h3>{code}</h3><img loading="lazy" alt="{code}" src="{escape(path.relative_to(ep).as_posix())}">')
    pos = 0
    for s, f, _ in rows:
        blocks.append(f'<article><h2>{s["id"]} · {escape(s["scene"])} · {pos}–{pos+s["duration"]}s</h2>')
        if s.get("location"):
            blocks.append(f'<p>Bối cảnh {s["location"]}</p>')
        blocks.append(f'<img loading="lazy" alt="{s["id"]}" src="{escape(f.relative_to(ep).as_posix())}">')
        for k in ("visual", "action", "camera", "sound", "continuity"):
            blocks.append("<p>" + escape(s[k]) + "</p>")
        for line in s["lines"]:
            blocks.append("<p>" + escape(f'{line["start"]}–{line["end"]}s · {line["who"]}: {line["text"]}') + "</p>")
        blocks.append("</article>")
        pos += s["duration"]
    save(ep / "storyboard.html", "\n".join(blocks) + "</html>")
