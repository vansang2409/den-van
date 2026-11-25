"""Bàn điều phối cho một tập phim. Chạy python -m studio --help."""
import argparse
import getpass
import re
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import planning
from .common import CAST, CREATIVE, digest, load, read, save, signature, validate_shots

GATES = ("script", "board", "final")


@contextmanager
def episode_lock(ep):
    with closing(sqlite3.connect(ep / ".runner.sqlite", timeout=0.2, isolation_level=None)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise ValueError("Một tiến trình khác đang xử lý tập phim này.") from None
        try:
            yield
        finally:
            db.rollback()


def init(ep, brief, pilot, previous=None):
    if ep.exists():
        raise ValueError("Thư mục tập đã tồn tại. Chọn tên mới hoặc dùng status.")
    direction = "Tập mở màn. Giữ nguyên tính cách trong bible và nhịp hài của kịch bản đề xuất." if pilot else brief
    ep.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=ep.parent) as tmp:
        stage = Path(tmp) / "ep"
        save(stage / "dinh-huong.md", direction)
        save(stage / "bible.md", read(CREATIVE / "bible.md"))
        save(stage / "approvals.json", [])
        if pilot:
            save(stage / "kich-ban.md", read(CREATIVE / "pilot.md"))
        if previous:
            with episode_lock(previous):
                phase, context = review(previous)
                if phase not in ("voices", "produce", "final", "ready"):
                    raise ValueError("Chọn tập trước đã được duyệt storyboard để kế thừa nhân vật và bối cảnh.")
                save(stage / "tap-truoc.md", read(previous / "kich-ban.md"))
                shutil.copy2(previous / "bible.md", stage / "bible.md")
                for filename in ("refs.json", "voices.json"):
                    if (previous / filename).is_file():
                        shutil.copy2(previous / filename, stage / filename)
                for files in context["refs"].values():
                    for image in files:
                        dest = stage / "refs" / image.name
                        dest.parent.mkdir(exist_ok=True)
                        shutil.copy2(image, dest)
                for char in CAST:
                    profile = planning.character_profile(previous, context["identity"], char)
                    save(stage / "character" / profile.name, profile.read_bytes())
                locations = planning.inherited_locations(previous)
                locations.update(context["locations"])
                for code, image in locations.items():
                    save(stage / "locations" / f"{code}.png", image.read_bytes())
                save(stage / "storyboard-nguon.json", {"episode": previous.name, "board": context["board"]})
        stage.rename(ep)


def approved(ep, gate, key):
    matches = [a for a in load(ep / "approvals.json") if a["gate"] == gate]
    return bool(matches and matches[-1]["version"] == key and matches[-1]["action"] == "approve")


def take_notes(ep):
    return load(ep / "retakes.json") if (ep / "retakes.json").exists() else {}


def shotlist(path):
    rows = load(path)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Thiếu danh sách shot tại {path}.")
    total = sum(s.get("duration", 0) for s in rows)
    if not 480 <= total <= 600:
        raise ValueError("Tổng thời lượng shot cần đạt 480–600 giây.")
    validate_shots(rows, total)
    for i, shot in enumerate(rows, 1):
        if shot.get("id") != f"S{i:03d}" or not isinstance(shot.get("scene"), str) or not shot["scene"].strip():
            raise ValueError(f"Sai thứ tự ID hoặc thiếu tên cảnh ở shot {i}.")
    return rows


def review(ep):
    """Chỉ đọc. Trả về bước kế và đúng tập đầu vào của bước đó."""
    ctx = {}
    if (ep / "yeu-cau-sua.json").exists():
        return "rewrite", ctx
    if not (ep / "kich-ban.md").exists():
        return "write", ctx
    if not read(ep / "kich-ban.md").strip():
        raise ValueError("Kịch bản đang trống.")
    script = planning.script_key(ep)
    ctx.update(version=script, file=ep / "kich-ban.md")
    if not approved(ep, "script", script):
        return "script", ctx
    folder = ep / "plans" / script
    path = folder / "shots.json"
    ctx.update(folder=folder, file=path)
    if not path.exists():
        return "plan", ctx
    refs = planning.reference_files(ep)
    shots = shotlist(path)
    planning.check_dialogue(read(ep / "kich-ban.md"), shots)
    ctx.update(shots=shots, refs=refs)
    if any(not refs[c] for c in CAST):
        return "refs", ctx
    places = planning.location_spec(ep, shots)
    if any(not path.is_file() for path, _, _ in places.values()):
        ctx["places"] = places
        return "locations", ctx
    locations = {code: spec[0] for code, spec in places.items()}
    identity, rows = planning.board_spec(ep, shots, refs, locations)
    ctx["locations"] = locations
    ctx.update(identity=identity, rows=rows)
    board = planning.board_key(identity, rows)
    if not board:
        return "frames", ctx
    profiles = [planning.character_profile(ep, identity, c) for c in CAST]
    if not all(p.is_file() for p in profiles):
        return "frames", ctx
    board = signature(script, board, [digest(p) for p in profiles])
    if locations:
        board = signature(board, {code: digest(path) for code, path in locations.items()})
    ctx.update(version=board, file=ep / "storyboard.html", board=board)
    if not approved(ep, "board", board):
        return "board", ctx
    vpath = ep / "voices.json"
    if not vpath.exists():
        return "voices", ctx
    voices = load(vpath)
    if any(not isinstance(voices.get(c), str) or not voices[c].strip() for c in CAST) or voices[CAST[0]] == voices[CAST[1]]:
        raise ValueError("Cần hai voice ID khác nhau trong voices.json.")
    marks = take_notes(ep)
    music = ep / "music.mp3"
    key = signature(board, voices, marks, digest(music) if music.exists() else "")
    receipt = ep / "renders" / (key + ".json")
    ctx.update(receipt=receipt, voices=voices, marks=marks)
    if not receipt.exists():
        return "produce", ctx
    output = (ep / load(receipt)["output"]).resolve()
    if not output.is_relative_to(ep) or not output.is_dir():
        raise ValueError(f"Thiếu thư mục bản dựng được ghi tại {receipt}.")
    expected = ("film.mp4", "vi.srt", "thumbnail.jpg", "publishing.json", "qc.json")
    if any(not (output / n).is_file() for n in expected) or not any((output / "shorts").glob("*.mp4")):
        raise ValueError(f"Bản dựng thiếu thành phần tại {output}.")
    contents = [(p.relative_to(output).as_posix(), digest(p)) for p in sorted(output.rglob("*")) if p.is_file()]
    final = signature(key, contents)
    ctx.update(version=final, file=output)
    return ("ready" if approved(ep, "final", final) else "final"), ctx


def describe(stage, ctx):
    if stage in GATES:
        labels = {"script": "kịch bản", "board": "ngoại hình, bối cảnh và storyboard", "final": "phim, Shorts và gói đăng"}
        return f"Chờ bạn duyệt {labels[stage]}.\n{ctx['file']}\n{stage} {ctx['version']}"
    if stage == "ready":
        return f"Bạn đã duyệt bản cuối. Gói phát hành ở {ctx['file']}"
    if stage == "refs":
        return "Chờ ảnh thật: " + ", ".join(c for c in CAST if not ctx["refs"][c])
    if stage == "voices":
        return "Chờ chọn hai giọng cố định. Dùng lệnh voices để lưu ID Đen và Vằn."
    return {"write": "Sẵn sàng phát triển ý tưởng và viết kịch bản.",
            "rewrite": "Đã nhận góp ý. Sẵn sàng sửa bản kịch bản.",
            "plan": "Kịch bản đã duyệt. Sẵn sàng chia cảnh.",
            "locations": "Sẵn sàng dựng ảnh chuẩn cho các địa điểm mới hoặc được yêu cầu sửa.",
            "frames": "Sẵn sàng dựng keyframe theo ảnh thật.",
            "produce": "Storyboard đã duyệt. Sẵn sàng tạo clip, thu tiếng, QC và dựng phim."}[stage]


def run(ep, live):
    while True:
        stage, ctx = review(ep)
        if stage == "board":
            planning.storyboard(ep, ctx["rows"], ctx["refs"], ctx["board"], ctx["identity"], ctx["locations"])
        if stage not in {"write", "rewrite", "plan", "locations", "frames", "produce"} or not live:
            return
        if stage == "write":
            planning.episode_script(ep)
        elif stage == "rewrite":
            request = load(ep / "yeu-cau-sua.json")
            new_file = ep / "revisions" / (signature(request) + "-new.md")
            if not new_file.exists():
                from .providers import response
                revised = response(planning.role("story"), planning.world_context(ep) + "\n" + read(ep / "dinh-huong.md")
                    + "\nBản trước:\n" + read(ep / "revisions" / (request["source"] + ".md"))
                    + "\nViết lại đầy đủ theo góp ý: " + request["note"]
                    + "\nGiữ nhịp 8–10 phút. Mỗi dòng thoại theo mẫu **Đen** — lời nói hoặc **Vằn** — lời nói.")
                save(new_file, revised)
            save(ep / "kich-ban.md", read(new_file))
            (ep / "yeu-cau-sua.json").unlink()
        elif stage == "plan":
            save(ctx["file"], planning.plan(ep, ctx["folder"]))
        elif stage == "locations":
            planning.generate_locations(ctx["places"])
        elif stage == "frames":
            planning.generate_frames(ep, ctx["identity"], ctx["rows"], ctx["refs"], ctx["locations"])
        else:
            from .production import produce
            output = produce(ep, ctx["board"], ctx["rows"], ctx["refs"], ctx["voices"], ctx["marks"], ctx["locations"])
            save(ctx["receipt"], {"output": Path(output).resolve().relative_to(ep).as_posix()})


def decide(ep, args):
    stage, ctx = review(ep)
    if stage != args.gate or args.version != ctx.get("version"):
        raise ValueError("Giai đoạn hoặc phiên bản đã đổi. Xem status và duyệt đúng bản hiện hành.")
    history = load(ep / "approvals.json")
    if stage == "board":
        planning.storyboard(ep, ctx["rows"], ctx["refs"], ctx["board"], ctx["identity"], ctx["locations"])
    history.append({"gate": stage, "version": args.version, "action": "approve", "by": args.by,
                    "time": datetime.now(timezone.utc).isoformat()})
    save(ep / "approvals.json", history)


def add_ref(ep, args):
    source = args.image
    if not source.is_file() or source.stat().st_size > 15 * 1024 * 1024:
        raise ValueError("Chọn ảnh PNG/JPEG tối đa 15 MiB.")
    data = source.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    else:
        raise ValueError("Ảnh thật cần có định dạng PNG hoặc JPEG.")
    name = digest(source) + ext
    refs = planning.reference_files(ep)
    if len(refs[args.character]) >= 4 and name not in [p.name for p in refs[args.character]] and not args.replace:
        raise ValueError("Tối đa 4 góc mỗi nhân vật. Dùng --replace để thay bộ ảnh.")
    path = ep / "refs" / name
    if not path.exists():
        save(path, data)
    old = refs[args.character]
    refs[args.character] = [path] if args.replace else list(dict.fromkeys([*old, path]))
    save(ep / "refs.json", {c: [p.name for p in paths] for c, paths in refs.items()})


def retake(ep, args):
    stage, ctx = review(ep)
    field = "location" if args.part == "location" else "id"
    if args.target not in {s.get(field) for s in ctx.get("shots", [])}:
        raise ValueError("Mã shot hoặc địa điểm chưa có trong phân cảnh hiện hành.")
    if args.part in ("video", "voice", "sound") and stage not in ("produce", "final", "ready"):
        raise ValueError("Cần duyệt storyboard và chọn giọng trước khi sửa clip/tiếng.")
    notes = take_notes(ep)
    key = f"{args.part}/{args.target}"
    note = {"revision": notes.get(key, {}).get("revision", 0) + 1, "reason": args.reason}
    if args.part == "location":
        path = ctx.get("locations", {}).get(args.target)
        if path is not None:
            note["base"] = path.relative_to(ep).as_posix()
        elif notes.get(key, {}).get("base"):
            note["base"] = notes[key]["base"]
    notes[key] = note
    save(ep / "retakes.json", notes)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(required=True, dest="cmd")
    for cmd, helptext in {"init":"Tạo tập", "status":"Xem bước và phiên bản", "run":"Điều phối đến điểm duyệt",
            "approve":"Ghi quyết định của chủ dự án", "ref":"Thêm ảnh thật", "voices":"Chọn hai voice ID",
            "rewrite":"Góp ý sửa kịch bản", "retake":"Yêu cầu sửa một shot", "release":"Chép gói đã duyệt để đăng"}.items():
        parser = sub.add_parser(cmd, help=helptext)
        parser.add_argument("episode", type=Path)
        if cmd == "init":
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument("--pilot", action="store_true")
            group.add_argument("--brief")
            parser.add_argument("--from-episode", type=Path, help="Kế thừa nhân vật, bối cảnh, giọng và diễn biến tập trước.")
        elif cmd == "run":
            parser.add_argument("--live", action="store_true", help="Cho phép gọi API sản xuất tính phí.")
            parser.add_argument("--limit", type=int, help="Giới hạn số yêu cầu tạo nội dung của lần chạy.")
        elif cmd == "rewrite":
            parser.add_argument("note")
        elif cmd == "approve":
            parser.add_argument("gate", choices=GATES)
            parser.add_argument("version")
            parser.add_argument("--by", default=getpass.getuser())
        elif cmd == "ref":
            parser.add_argument("character", choices=CAST)
            parser.add_argument("image", type=Path)
            parser.add_argument("--replace", action="store_true")
        elif cmd == "voices":
            parser.add_argument("den")
            parser.add_argument("van")
        elif cmd == "retake":
            parser.add_argument("part", choices=("location", "frame", "video", "voice", "sound"))
            parser.add_argument("target", help="Mã địa điểm hoặc mã shot.")
            parser.add_argument("reason")
        elif cmd == "release":
            parser.add_argument("destination", type=Path)
    args = p.parse_args()
    ep = args.episode.resolve()
    if args.cmd == "init":
        init(ep, args.brief, args.pilot, args.from_episode.resolve() if args.from_episode else None)
    if not (ep / "approvals.json").is_file():
        raise ValueError("Thư mục chưa được khởi tạo bằng init.")
    with episode_lock(ep):
        if args.cmd == "approve":
            decide(ep, args)
        elif args.cmd == "ref":
            add_ref(ep, args)
        elif args.cmd == "voices":
            if args.den == args.van or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", v) for v in (args.den, args.van)):
                raise ValueError("Nhập hai voice ID hợp lệ và khác nhau.")
            save(ep / "voices.json", dict(zip(CAST, (args.den, args.van))))
        elif args.cmd == "run":
            planning.providers.limit_calls(args.limit)
            try:
                run(ep, args.live)
            except planning.providers.BatchComplete as exc:
                print(exc)
            finally:
                planning.providers.limit_calls(None)
        elif args.cmd == "rewrite":
            old = read(ep / "kich-ban.md")
            source = signature(old)
            save(ep / "revisions" / (source + ".md"), old)
            save(ep / "yeu-cau-sua.json", {"source": source, "note": args.note})
        elif args.cmd == "retake":
            retake(ep, args)
        elif args.cmd == "release":
            stage, ctx = review(ep)
            if stage != "ready":
                raise ValueError("Chỉ có thể xuất gói sau khi bạn duyệt đúng bản cuối.")
            dest = args.destination.resolve()
            if dest.exists() or dest.is_relative_to(ep):
                raise ValueError("Chọn thư mục xuất mới bên ngoài thư mục tập.")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
                draft = Path(tmp) / "release"
                shutil.copytree(ctx["file"], draft)
                draft.rename(dest)
            print(f"Đã xuất gói: {dest}")
        print(describe(*review(ep)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        sys.exit(f"Studio: {exc}")
