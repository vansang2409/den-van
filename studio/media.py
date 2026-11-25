"""Dựng phim ngoại tuyến bằng FFmpeg. Chạy python -m studio.media --help."""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FPS = 25
MAX_SHOTS = 400
FORMATS = "mov,matroska,webm,avi,wav,mp3,flac,ogg,aac,aiff,image2"


class MediaError(ValueError):
    """Lỗi dữ liệu hoặc công cụ dành cho người dựng phim."""


def number(value, name, low, high):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high):
        raise MediaError(f"{name} phải là số trong khoảng {low:g}–{high:g}")
    return float(value)


def asset(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise MediaError("Asset cần đường dẫn tương đối so với manifest")
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise MediaError(f"Asset thiếu hoặc nằm ngoài thư mục tập phim: {name}")
    return str(candidate)


def run(program, args, cwd=None, timeout=1800):
    binary = (os.getenv(program.upper()) or os.getenv(f"STUDIO_{program.upper()}")
              or shutil.which(program))
    if not binary:
        raise MediaError(f"Thiếu {program}. Thêm vào PATH hoặc đặt {program.upper()}.")
    try:
        proc = subprocess.run([binary, "-v", "error", *args], cwd=cwd,
                              capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"Không chạy được {program}: {exc}") from exc
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip()[-1500:]
        raise MediaError(f"{program} thất bại ({proc.returncode}): {detail}")
    return proc.stdout


def inspect_file(path):
    return json.loads(run("ffprobe", [
        "-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-show_entries",
        "stream=index,codec_type,codec_name,width,height,duration,disposition:format=duration",
        "-of", "json", str(path)
    ], timeout=60))


def stream_duration(meta, kind, label):
    streams = [s for s in meta.get("streams", []) if s["codec_type"] == kind]
    if not streams:
        raise MediaError(f"{label} thiếu track {kind}")
    stream = streams[0]
    duration = stream.get("duration", meta.get("format", {}).get("duration"))
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        raise MediaError(f"{label} thiếu thời lượng {kind} hợp lệ") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise MediaError(f"{label} có thời lượng {kind} không hợp lệ")
    return seconds


def items(data, name, limit, required=False):
    rows = data.get(name, [])
    if (not isinstance(rows, list) or len(rows) > limit or (required and not rows)
            or any(not isinstance(row, dict) for row in rows)):
        raise MediaError(f"{name} cần danh sách đối tượng, tối đa {limit} mục")
    return rows


def identifier(row, seen):
    name = row.get("id")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise MediaError("ID cần 1–64 chữ Latin, số, gạch dưới hoặc gạch ngang")
    if name.casefold() in seen:
        raise MediaError(f"ID lặp: {name}")
    seen.add(name.casefold())
    return name


def check(manifest_path, sample=False):
    path = Path(manifest_path).resolve()
    if path.stat().st_size > 4_000_000:
        raise MediaError("Manifest vượt quá 4 MB")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise MediaError("Manifest cần một đối tượng JSON")
    shots = []
    cues = []
    seen = set()
    elapsed = 0.0
    frames = 0
    for row in items(data, "shots", MAX_SHOTS, required=True):
        name = identifier(row, seen)
        seconds = number(row.get("duration"), f"{name}.duration", 1/FPS, 600)
        clip = asset(path.parent, row.get("clip"))
        meta = inspect_file(clip)
        if stream_duration(meta, "video", name) + 1/FPS < seconds:
            raise MediaError(f"Clip {name} ngắn hơn shot {seconds:g}s")
        voice = None
        if row.get("voice") is not None:
            voice = asset(path.parent, row["voice"])
            if stream_duration(inspect_file(voice), "audio", name) > seconds + 0.05:
                raise MediaError(f"Voice của {name} dài hơn shot")
        ambience = None
        if row.get("ambience") is not None:
            ambience = asset(path.parent, row["ambience"])
            stream_duration(inspect_file(ambience), "audio", name)
        before = 0
        for cue in items(row, "cues", 100):
            start = number(cue.get("start"), f"{name}.cue.start", before, seconds)
            end = number(cue.get("end"), f"{name}.cue.end", start, seconds)
            line = cue.get("text")
            if end - start < 0.001 or not isinstance(line, str) or not line.strip():
                raise MediaError(f"Phụ đề rỗng hoặc quá ngắn ở {name}")
            cues.append((elapsed + start, elapsed + end, " ".join(line.split())))
            before = end
        elapsed += seconds
        next_frames = round(elapsed * FPS)
        shots.append({"id": name, "clip": clip, "voice": voice, "ambience": ambience,
                      "seconds": (next_frames - frames) / FPS,
                      "has_audio": any(s["codec_type"] == "audio" for s in meta["streams"])})
        frames = next_frames
    if (not sample and elapsed < 480 - 1e-7) or elapsed > 600 + 1e-7:
        raise MediaError(f"Tổng {elapsed:g}s. Bản tập phải dài 480–600s, mẫu tối đa 600s.")
    total = frames / FPS
    seen.clear()
    shorts = []
    for row in items(data, "shorts", 20):
        name = identifier(row, seen)
        start = number(row.get("start"), f"{name}.start", 0, total)
        end = number(row.get("end"), f"{name}.end", start, total)
        if end - start < 1/FPS or end - start > 180:
            raise MediaError(f"Thời lượng bản dọc {name} phải từ 1 frame đến 180s")
        focus = number(row.get("focus_x", 0.5), f"{name}.focus_x", 0, 1)
        shorts.append({"id": name, "start": start, "end": end, "focus_x": focus})
    cover = number(data.get("thumbnail_at", 0), "thumbnail_at", 0, total - 1/FPS)
    music = None
    if data.get("music") is not None:
        music = asset(path.parent, data["music"])
        stream_duration(inspect_file(music), "audio", "music")
    return {"shots": shots, "shorts": shorts, "duration": total, "cues": cues,
            "thumbnail_at": cover, "music": music}


def timestamp(seconds):
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def subtitles(path, cues, start, end):
    blocks = []
    for left, right, line in cues:
        left, right = max(left, start) - start, min(right, end) - start
        if round(right * 1000) > round(left * 1000):
            blocks.append(f"{len(blocks)+1}\n{timestamp(left)} --> {timestamp(right)}\n{line}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def media_input(path):
    return ["-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-i", str(path)]


def segment(shot, target):
    args = media_input(shot["clip"])
    duration = f"{shot['seconds']:.4f}"
    stereo = "aformat=sample_rates=48000:channel_layouts=stereo"
    # Chuẩn hóa track nền, kể cả khi clip gốc không có âm thanh.
    if shot["has_audio"]:
        volume = 0.35 if shot["voice"] else 1
        bed = f"[0:a:0]asetpts=PTS-STARTPTS,{stereo},volume={volume},apad"
    else:
        bed = "anullsrc=r=48000:cl=stereo"
    audio = f"{bed},atrim=duration={duration}[bed]"
    tracks = ["[bed]"]
    if shot["voice"]:
        args += media_input(shot["voice"])
        audio += f";[1:a:0]asetpts=PTS-STARTPTS,{stereo}[voice]"
        tracks.append("[voice]")
    if shot["ambience"]:
        args += ["-stream_loop", "-1", *media_input(shot["ambience"])]
        index = len(tracks)
        audio += f";[{index}:a:0]asetpts=PTS-STARTPTS,{stereo},volume=0.30[env]"
        tracks.append("[env]")
    track = "[bed]"
    if len(tracks) > 1:
        audio += (f";{''.join(tracks)}amix=inputs={len(tracks)}:duration=first:normalize=0,"
                  "alimiter=limit=0.95:latency=1[mix]")
        track = "[mix]"
    visual = (f"setpts=PTS-STARTPTS,fps={FPS},scale=1920:1080:"
              "force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,"
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,tpad=stop_duration=0.04:stop_mode=clone")
    run("ffmpeg", ["-nostdin", *args, "-filter_complex", audio, "-map", "0:v:0",
                   "-map", track, "-vf", visual, "-t", duration, "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                   "-c:a", "pcm_s16le", str(target)])


def qc_video(path, width, height, seconds):
    meta = inspect_file(path)
    video = next((s for s in meta["streams"] if s["codec_type"] == "video"), {})
    actual = stream_duration(meta, "video", path.name)
    sound = stream_duration(meta, "audio", path.name)
    if (video.get("width"), video.get("height")) != (width, height):
        raise MediaError(f"{path.name} sai kích thước")
    if max(abs(actual - seconds), abs(sound - seconds), abs(actual - sound)) > 0.10:
        raise MediaError(f"{path.name} lệch thời lượng: hình {actual:g}s, âm {sound:g}s, dự kiến {seconds:g}s")
    return {"width": width, "height": height, "video_seconds": actual, "audio_seconds": sound}


def render(manifest_path, output_path, sample=False):
    output = Path(output_path).resolve()
    if output.exists():
        raise MediaError(f"Thư mục đích đã tồn tại: {output}")
    plan = check(manifest_path, sample)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Chỉ chuyển trọn bộ file sang tên đích sau khi QC hoàn tất.
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        work = Path(tmp)
        delivery = work / "delivery"
        delivery.mkdir()
        names = []
        for index, shot in enumerate(plan["shots"]):
            name = f"shot-{index:04d}.mkv"
            segment(shot, work / name)
            names.append("file " + name)
        (work / "concat.txt").write_text("\n".join(names) + "\n", encoding="ascii")
        args = ["-f", "concat", "-safe", "1", "-i", "concat.txt"]
        track = "0:a:0"
        if plan["music"]:
            args += ["-stream_loop", "-1", *media_input(plan["music"])]
            args += ["-filter_complex", "[1:a:0]volume=0.12[m];[0:a:0][m]amix="
                     "inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[out]"]
            track = "[out]"
        film = delivery / "film.mp4"
        run("ffmpeg", ["-nostdin", *args, "-map", "0:v:0", "-map", track, "-c:v", "copy",
                       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(film)], cwd=work)
        total = plan["duration"]
        report = {"sample": sample, "shot_count": len(plan["shots"]),
                  "film": qc_video(film, 1920, 1080, total), "shorts": {}}
        subtitles(delivery / "vi.srt", plan["cues"], 0, total)
        run("ffmpeg", ["-nostdin", "-ss", str(plan["thumbnail_at"]), "-i", str(film),
                       "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "2",
                       str(delivery / "thumbnail.jpg")])
        if not (delivery / "thumbnail.jpg").is_file():
            raise MediaError("FFmpeg chưa xuất thumbnail tại mốc đã chọn")
        for short in plan["shorts"]:
            folder = delivery / "shorts"
            folder.mkdir(exist_ok=True)
            key = short["id"]
            target = folder / f"{key}.mp4"
            length = short["end"] - short["start"]
            crop = f"crop=ih*9/16:ih:(iw-ow)*{short['focus_x']}:0,scale=1080:1920,setsar=1"
            run("ffmpeg", ["-nostdin", "-ss", str(short["start"]), "-i", str(film), "-t",
                           str(length), "-vf", crop, "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                           str(target)])
            report["shorts"][key] = qc_video(target, 1080, 1920, length)
            subtitles(folder / f"{key}.srt", plan["cues"], short["start"], short["end"])
        (delivery / "qc.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        delivery.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for name in ("check", "render"):
        cmd = subs.add_parser(name)
        cmd.add_argument("manifest", type=Path)
        if name == "render":
            cmd.add_argument("output", type=Path, help="Thư mục xuất mới")
        cmd.add_argument("--sample", action="store_true", help="Cho phép đoạn mẫu dưới 480 giây")
    args = parser.parse_args()
    try:
        if args.action == "check":
            plan = check(args.manifest, args.sample)
            info = {"duration": plan["duration"], "shot_count": len(plan["shots"])}
        else:
            info = render(args.manifest, args.output, args.sample)
        print(json.dumps(info, indent=2))
    except (ValueError, OSError) as exc:
        print(f"Lỗi dựng phim: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
