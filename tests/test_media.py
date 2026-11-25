import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import media


class EditorTest(unittest.TestCase):
    def test_short_subtitles_crossing_cut(self):
        with tempfile.TemporaryDirectory() as name:
            subtitle = Path(name) / "clip.srt"
            media.subtitles(subtitle, [(0, 2, "Đen"), (2, 4, "Vằn"), (5, 6, "xa")], 1, 3)
            self.assertEqual(subtitle.read_text(encoding="utf-8"),
                             "1\n00:00:00,000 --> 00:00:01,000\nĐen\n\n"
                             "2\n00:00:01,000 --> 00:00:02,000\nVằn\n")

    @unittest.skipUnless((os.getenv("FFMPEG") or shutil.which("ffmpeg")) and
                         (os.getenv("FFPROBE") or shutil.which("ffprobe")), "cần FFmpeg và FFprobe")
    def test_render_with_silent_clip_voice_ambience_music(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            ffmpeg = os.getenv("FFMPEG") or shutil.which("ffmpeg")
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                            "color=green:size=160x90:rate=25", "-t", "1", "-pix_fmt",
                            "yuv420p", str(root / "khung.mp4")], check=True)
            subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300",
                            "-t", "0.35", str(root / "âm.wav")], check=True)
            manifest = root / "manifest.json"
            data = {"shots": [
                {"id": "s01", "clip": "khung.mp4", "duration": 0.6, "ambience": "âm.wav",
                 "cues": [{"start": 0.2, "end": 0.6, "text": "Đen đứng lại!"}]},
                {"id": "s02", "clip": "khung.mp4", "duration": 0.8, "voice": "âm.wav",
                 "ambience": "âm.wav"}], "music": "âm.wav",
                "thumbnail_at": 0.5, "shorts": [{"id": "trich", "start": 0.4, "end": 1.2}]}
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(media.MediaError, "480"):
                media.check(manifest)
            out = root / "ket-qua"
            report = media.render(manifest, out, sample=True)
            self.assertAlmostEqual(report["film"]["video_seconds"], 1.4, places=2)
            self.assertEqual(report["shorts"]["trich"]["width"], 1080)
            self.assertGreater((out / "thumbnail.jpg").stat().st_size, 100)
            self.assertIn("Đen", (out / "shorts" / "trich.srt").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(media.MediaError, "đã tồn tại"):
                media.render(manifest, out, sample=True)
            data["shots"][1]["duration"] = 2
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(media.MediaError, "ngắn hơn"):
                media.check(manifest, sample=True)


if __name__ == "__main__":
    unittest.main()
