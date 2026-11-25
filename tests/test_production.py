import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import media, production as prod
from studio.common import load, save


class ProductionTests(unittest.TestCase):
    def test_resume_polling_existing_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = root / "keyframe.png"
            frame.write_bytes(b"key")
            shot = dict(id="S001", action="nghe", camera="gan", continuity="dung", duration=5)
            with patch.object(prod.providers, "start_video", return_value="job1") as start:
                with patch.object(prod.providers, "finish_video", side_effect=[ValueError("timeout"), b"clip"]):
                    with self.assertRaisesRegex(ValueError, "timeout"):
                        prod.video_asset(root, shot, frame, {})
                    self.assertEqual(prod.video_asset(root, shot, frame, {}).read_bytes(), b"clip")
                self.assertEqual(start.call_count, 1)

    def test_delivery_from_approved_timeline_using_provider_doubles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = root / "frame.png"
            save(frame, b"frame")
            shot = dict(scene="Sân", visual="toàn", action="nghe", sound="gió",
                        camera="gần", cast=[], lines=[], continuity="đứng", duration=10)
            rows = [(dict(shot, id=f"S{i:03d}"), frame, {}) for i in range(1, 49)]
            pack = {"titles": ["a", "b", "c"], "description": "mô tả", "hashtags": ["#phim"],
                    "thumbnail_at": 5, "thumbnail_direction": "sân",
                    "shorts": [{"start": 2, "end": 20, "focus_x": 0.3, "tiktok": "a",
                                "reels": "b", "youtube_shorts": "c"}]}

            def mock_render(manifest, out):
                self.assertEqual(len(load(manifest)["shots"]), 48)
                save(out / "film.mp4", b"film")
                save(out / "thumbnail.jpg", b"thumb")
                save(out / "vi.srt", "")
                save(out / "shorts" / "short-01.mp4", b"short")
                return {"film": {}, "shorts": {}}

            def selective_qc(folder, candidate, image, clip, refs, previous):
                if candidate["id"] == "S001" and clip.read_bytes() == b"first":
                    raise prod.VisualDefect("Bàn chân sau đổi vị trí")
                return {"pass": True}

            with (patch.object(prod.providers, "start_video", return_value="x"),
                  patch.object(prod.providers, "finish_video", side_effect=[b"first", b"fixed"]),
                  patch.object(prod.providers, "sound", return_value=b"s") as sound,
                  patch.object(prod, "visual_qc", side_effect=selective_qc),
                  patch.object(prod.providers, "response", return_value=pack) as writer,
                  patch.object(prod.media, "render", side_effect=mock_render) as renderer):
                output = prod.produce(root, "board1", rows, {}, {}, {})
                self.assertEqual(load(output / "qc.json")["board_version"], "board1")
                self.assertEqual(load(output / "publishing.json")["shorts"][0]["id"], "short-01")
                self.assertEqual(output, prod.produce(root, "board1", rows, {}, {}, {}))
                self.assertEqual(sound.call_count, 1)
                self.assertEqual(writer.call_count, 1)
                self.assertEqual(renderer.call_count, 1)

    @unittest.skipUnless((os.getenv("FFMPEG") or shutil.which("ffmpeg")) and
                         (os.getenv("FFPROBE") or shutil.which("ffprobe")), "cần FFmpeg và FFprobe")
    def test_real_audio_alignment_and_visual_qc_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "speech.mp3"
            media.run("ffmpeg", ["-f", "lavfi", "-i", "sine=frequency=300", "-t", "0.5", str(audio)])
            shot = dict(id="S001", action="Nằm", continuity="ngước", visual="sân",
                        camera="toàn", cast=["Đen"], duration=3,
                        lines=[dict(who="Đen", text="Ơ!", start=0.2, end=1.1),
                               dict(who="Vằn", text="Kìa!", start=1.5, end=2.4)])
            with patch.object(prod.providers, "speech", return_value=audio.read_bytes()) as voice:
                voices = {"Đen": "den", "Vằn": "van"}
                track = prod.voice_asset(root, shot, voices, {})
                self.assertEqual(media.stream_duration(media.inspect_file(track), "audio", "voice"), 3)
                self.assertEqual(prod.voice_asset(root, shot, voices, {}), track)
                self.assertEqual(voice.call_count, 2)
            clip, ref = root / "clip.mp4", root / "ref.jpg"
            media.run("ffmpeg", ["-f", "lavfi", "-i", "color=size=160x90:rate=25",
                                 "-t", "3", "-pix_fmt", "yuv420p", str(clip)])
            media.run("ffmpeg", ["-i", str(clip), "-frames:v", "1", str(ref)])
            with patch.object(prod.providers, "response", return_value={"pass": False, "reason": "sai lông"}) as qc:
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "sai lông"):
                        prod.visual_qc(root/"qc", shot, ref, clip, {"Đen": [ref]}, "")
                self.assertEqual(len(qc.call_args.args[2]), 5)
                self.assertEqual(qc.call_count, 1)


if __name__ == "__main__":
    unittest.main()
