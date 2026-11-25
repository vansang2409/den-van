"""Sản xuất từ storyboard đã duyệt, chịu sự điều phối và khóa tập của runner."""

import os
import re
import tempfile
from pathlib import Path

from . import media, providers
from .common import cached, digest, encoded, load, nonempty, save, signature, validate_shots
from .planning import role


class VisualDefect(ValueError):
    """Nhận xét QC có thể gửi thẳng cho Agent video khi thử lại."""


def video_asset(folder, shot, image, mark):
    # Đặt góp ý trước để phần sửa luôn còn trong giới hạn 1000 ký tự của provider.
    motion = (f"{mark.get('reason', '')[:250]}\n{shot['action']}\n{shot['camera']}\n"
              f"{shot['continuity']}\nPhotorealistic, natural animal motion on four paws.").strip()[:1000]
    key = signature("gen4_turbo", motion, digest(image), shot["duration"], mark)
    target = folder / f"{key}.mp4"
    if not target.exists():
        receipt = folder / f"{key}.job.json"
        if not receipt.exists():
            job_id = providers.start_video(image, motion, shot["duration"])
            save(receipt, {"id": job_id, "shot": shot["id"], "motion": motion})
        # Timeout được xử lý bằng cách đọc lại biên nhận cũ khi chạy tiếp.
        save(target, providers.finish_video(load(receipt)["id"]))
    return target


def voice_asset(folder, shot, voices, mark):
    if not shot["lines"]:
        return None
    cues = []
    for i, line in enumerate(shot["lines"], 1):
        voice_id = voices[line["who"]]
        key = signature("eleven_flash_v2_5", "vi", voice_id, line["text"], mark)
        source = cached(folder / f"{key}.mp3", lambda: providers.speech(voice_id, line["text"]))
        duration = media.stream_duration(media.inspect_file(source), "audio", str(source))
        window = line["end"] - line["start"]
        speed = max(duration / window, 1)
        if speed > 1.18:
            raise ValueError(f"Voice Director: {shot['id']} câu {i} cần {duration:.2f}s, chỉ có "
                             f"{window:.2f}s. Dùng retake voice hoặc điều chỉnh cue và duyệt lại.")
        cues.append((source, line["start"], window, speed))

    key = signature("timeline-v1", shot["duration"], [(p.name, *v) for p, *v in cues])
    timeline = folder / (key + ".wav")
    if not timeline.exists():
        args = []
        filters = [f"anullsrc=r=48000:cl=stereo:d={shot['duration']}[base]"]
        for i, (path, start, window, speed) in enumerate(cues):
            args.extend(media.media_input(path))
            filters.append(f"[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,"
                           f"aformat=channel_layouts=stereo,atempo={speed:.8f},"
                           f"atrim=duration={window:.6f},adelay={round(start*1000)}:all=1[a{i}]")
        tracks = "".join(f"[a{i}]" for i in range(len(cues)))
        filters.append(f"[base]{tracks}amix=inputs={len(cues)+1}:duration=first:normalize=0[out]")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            dest = Path(tmp) / "voice.wav"
            media.run("ffmpeg", ["-nostdin", *args, "-filter_complex_threads", "1",
                                 "-filter_complex", ";".join(filters), "-map", "[out]",
                                 "-t", str(shot["duration"]), "-c:a", "pcm_s16le", str(dest)], timeout=45)
            dest.replace(timeline)
    return timeline


def visual_qc(folder, shot, keyframe, clip, refs, previous, location=None):
    sources = [(name, path) for name in shot["cast"] for path in refs[name]]
    expected = {k: shot[k] for k in ("id", "action", "visual", "camera", "continuity", "cast", "duration")}
    order = ["ảnh thật của " + name for name, _ in sources]
    if location:
        order.append("ảnh chuẩn bối cảnh " + shot["location"])
    order += ["keyframe đã duyệt", "ba khung hình thực đầu/giữa/cuối"]
    prompt = ("Đánh giá shot đối với yêu cầu và continuity trước. Các ảnh lần lượt gồm "
              + ", ".join(order) + ". "
              "Với shot trống không thêm động vật. Khi có ảnh chuẩn bối cảnh, đối chiếu mốc cố định nhìn thấy được "
              "trong góc máy này và chấp nhận thay đổi hợp lý về ánh sáng, thời tiết và đạo cụ di động. "
              "Đánh giá dấu hiệu nhìn thấy về nhận diện, giải phẫu, bố cục, địa điểm, logic. "
              "Ba ảnh không đủ xác minh nhịp chuyển động và tiếng. Trả JSON "
              '{"pass":true,"reason":"ghi nhận quan sát hoặc lỗi cụ thể cần sửa"}. '
              + encoded({"shot": expected, "previous_continuity": previous}))
    instruction = role("qc")
    key = signature(prompt, instruction, os.getenv("STUDIO_TEXT_MODEL"), digest(clip),
                    digest(keyframe), [digest(p) for _, p in sources], digest(location) if location else None)
    receipt = folder / (key + ".json")
    if not receipt.exists():
        folder.mkdir(parents=True, exist_ok=True)
        seconds = shot["duration"]
        if media.stream_duration(media.inspect_file(clip), "video", shot["id"]) + 1/media.FPS < seconds:
            raise ValueError(f"{shot['id']} thiếu thời lượng hình. Dùng retake video cho shot này.")
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            frames = []
            for i, t in enumerate((0, seconds / 2, max(0, seconds - 0.1))):
                path = Path(tmp) / f"frame{i}.jpg"
                media.run("ffmpeg", ["-nostdin", "-ss", str(t), *media.media_input(clip),
                                     "-frames:v", "1", "-vf", "scale=-2:480", str(path)])
                if not path.exists():
                    raise ValueError(f"Không đọc được {shot['id']} tại {t}s. Dùng retake video.")
                frames.append(path)
            images = [p for _, p in sources] + ([location] if location else []) + [keyframe] + frames
            decision = providers.response(instruction, prompt, images, structured=True)
        nonempty(decision, ["reason"])
        if type(decision.get("pass")) is not bool:
            raise ValueError(f"QC trả kết quả sai kiểu cho {shot['id']}. Chạy lại run.")
        save(receipt, {"shot": shot["id"], "pass": decision["pass"], "reason": decision["reason"]})
    result = load(receipt)
    if not result["pass"]:
        raise VisualDefect(f"QC {shot['id']}: {result['reason']}")
    return result


def publishing(folder, timeline):
    duration = timeline[-1]["end"]
    instruction = role("publishing")
    prompt = ("Viết gói đăng tiếng Việt cho tập phim. Chọn 1–3 đoạn 9:16, mỗi đoạn 1–60 giây "
              "có mở và kết, giữ chủ thể trong khung. Thời gian tính bằng giây từ đầu tập, "
              "focus_x là vị trí crop từ 0 đến 1 (0 trái, 1 phải). Trả JSON đúng cấu trúc "
              '{"titles":["...","...","..."],"description":"...","hashtags":["#..."],'
              '"thumbnail_at":1,"thumbnail_direction":"...", "shorts":[{"start":5,"end":20,'
              '"focus_x":0.5,"tiktok":"...","reels":"...","youtube_shorts":"..."}]}. '
              + encoded(timeline))
    path = folder / (signature(instruction, prompt, os.getenv("STUDIO_TEXT_MODEL")) + ".json")
    if not path.exists():
        pack = providers.response(instruction, prompt, structured=True)
        nonempty(pack, ("description", "thumbnail_direction"))
        for field in ("titles", "hashtags"):
            values = pack.get(field)
            if not isinstance(values, list) or not values or not all(isinstance(x, str) and x.strip() for x in values):
                raise ValueError(f"Gói đăng thiếu {field}. Chạy lại run.")
        if len(pack["titles"]) != 3:
            raise ValueError("Gói đăng cần đủ ba tiêu đề. Chạy lại run.")
        media.number(pack.get("thumbnail_at"), "thumbnail_at", 0, duration - 1/media.FPS)
        for i, short in enumerate(media.items(pack, "shorts", 3, required=True), 1):
            nonempty(short, ("tiktok", "reels", "youtube_shorts"))
            start = media.number(short.get("start"), "short.start", 0, duration - 1)
            media.number(short.get("end"), "short.end", start+1, min(duration, start+60))
            media.number(short.get("focus_x"), "short.focus_x", 0, 1)
            short["id"] = f"short-{i:02d}"
        save(path, pack)
    return load(path)


def produce(ep, board_version, rows, refs, voices, marks, locations=None):
    ep = Path(ep).resolve()
    assets = ep / "assets"
    shots = [shot for shot, _, _ in rows]
    total = sum(s["duration"] for s in shots)
    validate_shots(shots, total)
    if not 480 <= total <= 600:
        raise ValueError("Bản tập cần tổng thời lượng 480–600 giây.")
    ids = [s.get("id", "") for s in shots]
    if len(set(ids)) != len(ids) or not all(re.fullmatch(r"S\d{3,}", i) for i in ids):
        raise ValueError("ID shot thiếu, sai định dạng hoặc bị lặp.")
    for shot, image, _ in rows:
        if not image.is_file() or any(not refs.get(c) for c in shot["cast"]):
            raise ValueError(f"Thiếu keyframe hoặc ảnh thật của {shot['id']}.")
        if any(not voices.get(line["who"]) for line in shot["lines"]):
            raise ValueError(f"Thiếu voice ID đã chọn cho {shot['id']}.")

    edit = {"shots": []}
    results = []
    timeline = []
    pos = 0
    for shot, image, _ in rows:
        sid = shot["id"]
        d = shot["duration"]
        previous = timeline[-1]["continuity"] if timeline else ""
        place = (locations or {}).get(shot.get("location"))
        qc_options = {"location": place} if place else {}
        mark = marks.get("video/" + sid, {})
        clip = video_asset(assets / "clips", shot, image, mark)
        try:
            result = visual_qc(assets / "visual-qc", shot, image, clip, refs, previous, **qc_options)
        except VisualDefect as defect:
            repair = {"reason": str(defect), "source": clip.name, "request": mark}
            clip = video_asset(assets / "clips", shot, image, repair)
            try:
                result = visual_qc(assets / "visual-qc", shot, image, clip, refs, previous, **qc_options)
            except VisualDefect as remaining:
                raise ValueError(f"{remaining}. Đã thử sửa hình một lần. Dùng retake video hoặc frame cho {sid}.") from None
        results.append(result)
        voice = voice_asset(assets / "voices", shot, voices, marks.get("voice/" + sid, {}))
        sound_mark = marks.get("sound/" + sid, {})
        sound_prompt = ("Ambient sound and foley only. No speech or music. "
                        + shot["sound"] + "\n" + sound_mark.get("reason", ""))
        key = signature("eleven-sound-v1", d, sound_prompt, sound_mark)
        ambient = cached(assets / "ambience" / (key + ".mp3"), lambda: providers.sound(sound_prompt, d))
        row = {"id": sid, "duration": d, "clip": clip.relative_to(ep).as_posix(),
               "ambience": ambient.relative_to(ep).as_posix(),
               "cues": [{"start": line["start"], "end": line["end"],
                         "text": f"{line['who']}: {line['text']}"} for line in shot["lines"]]}
        if voice:
            row["voice"] = voice.relative_to(ep).as_posix()
        edit["shots"].append(row)
        timeline.append({"id": sid, "scene": shot["scene"], "start": pos, "end": pos+d,
                         "action": shot["action"], "continuity": shot["continuity"], "cues": row["cues"]})
        pos += d
    pack = publishing(assets / "publishing", timeline)
    edit.update(thumbnail_at=pack["thumbnail_at"], shorts=pack["shorts"])
    music = ep / "music.mp3"
    if music.is_file():
        edit["music"] = music.name
    version = signature("delivery-v1", board_version, edit, pack, results,
                        digest(music) if music.is_file() else None)
    manifest = ep / f"edit-{version}.json"
    save(manifest, edit)
    releases = ep / "deliveries"
    releases.mkdir(exist_ok=True)
    output = releases / version
    if not output.exists():
        with tempfile.TemporaryDirectory(dir=releases) as tmp:
            stage = Path(tmp) / "out"
            report = media.render(manifest, stage)
            report.update(board_version=board_version, visual_qc=results,
                          human_review=["Xem chuyển động, continuity và khung dọc.",
                                        "Nghe thoại, nhạc, ambience và kiểm tra đồng bộ toàn tập."])
            save(stage / "qc.json", report)
            save(stage / "publishing.json", pack)
            stage.rename(output)
    return output
