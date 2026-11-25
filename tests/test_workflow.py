import base64
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from studio import __main__ as runner
from studio import planning, production
from studio.common import CAST, load, save, signature


# Ảnh PNG 1 x 1 chỉ dùng để thử cơ chế lưu ảnh và đổi phiên bản.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42"
    "mP8/x8AAwMCAO+jD8sAAAAASUVORK5CYII="
)


def respond(instruction, prompt, *images, structured=False):
    if not structured:
        return "Hồ sơ nhận diện thử trong bộ kiểm thử."
    if '"scenes"' in prompt:
        return {"scenes": [{"name": f"Mưa {i}", "content": "Hai bạn ngồi đợi.",
                            "seconds": 80} for i in range(6)]}
    if '"shots"' in prompt:
        return {"shots": [
            {"duration": 10, "location": "nha-mai-ngoi", "cast": list(CAST), "visual": "Mái hiên",
             "action": "Hai bạn nằm trên nền gạch.", "camera": "Ngang tầm mắt",
             "sound": "Mưa rơi", "continuity": f"Dấu chân thứ {i}", "lines": []}
            for i in range(8)
        ]}
    raise AssertionError("Bài kiểm thử không chờ loại yêu cầu này.")


def produce_fixture(ep, board, rows, refs, voices, marks, locations):
    # Chỉ thay phần tạo media; CLI vẫn tự lập biên nhận và tính mã bản cuối.
    folder = ep / "deliveries" / signature(board, marks)
    for filename in ("film.mp4", "thumbnail.jpg", "shorts/mua.mp4"):
        save(folder / filename, b"test fixture")
    save(folder / "vi.srt", "")
    save(folder / "publishing.json", {"titles": ["Buổi mưa"]})
    save(folder / "qc.json", {"shot_count": len(rows)})
    return folder


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.ep = self.root / "episode"
        self.dest = self.root / "release"
        self.den = self.root / "den.png"
        self.van = self.root / "van.png"
        self.den.write_bytes(PNG)
        self.van.write_bytes(PNG)
        self.enterContext(patch("socket.socket.connect",
                                side_effect=AssertionError("Bài kiểm thử phải chạy offline.")))
        self.respond = self.enterContext(patch.object(planning.providers, "response", side_effect=respond))
        self.frame = self.enterContext(patch.object(planning.providers, "frame", return_value=PNG))
        self.produce = self.enterContext(patch.object(production, "produce", side_effect=produce_fixture))
        self.cli("init", "--pilot")
        save(self.ep / "kich-ban.md", "Tập thử bằng hình. Đen và Vằn nghe mưa dưới mái hiên.")

    def cli(self, command, *args):
        argv = ["studio", command, str(self.ep), *map(str, args)]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as stdout:
            runner.main()
        return stdout.getvalue()

    def at(self, stage):
        current, context = runner.review(self.ep)
        self.assertEqual(current, stage)
        return context

    def approve(self, stage):
        version = self.at(stage)["version"]
        self.cli("approve", stage, version, "--by", "Chủ dự án")
        return version

    def blocked_release(self):
        with self.assertRaises(ValueError):
            self.cli("release", self.dest)
        self.assertFalse(self.dest.exists())

    def test_new_brief_runs_to_script_gate_once(self):
        self.ep = self.root / "episode-two"
        self.cli("init", "--brief", "Hai bạn tìm đường về trong mưa.")
        self.at("write")
        self.cli("run")
        self.respond.assert_not_called()
        self.respond.side_effect = ["Ba ý tưởng cho tập mới.", "Kịch bản chờ duyệt."]
        self.cli("run", "--live")
        self.at("script")
        self.cli("run", "--live")
        self.assertEqual(self.respond.call_count, 2)
        self.assertFalse((self.ep / "plans").exists())

    def create_board(self):
        self.approve("script")
        self.cli("run", "--live")
        self.at("refs")
        self.cli("ref", "Đen", self.den)
        self.cli("ref", "Vằn", self.van)
        self.cli("run", "--live")
        return self.at("board")["version"]

    def create_final(self):
        self.create_board()
        self.approve("board")
        self.cli("voices", "voice-den", "voice-van")
        self.cli("run", "--live")
        return self.at("final")

    def test_three_owner_decisions_required_before_release(self):
        self.cli("run", "--live")
        self.at("script")
        self.respond.assert_not_called()
        self.blocked_release()
        self.create_board()
        self.produce.assert_not_called()
        self.blocked_release()
        self.approve("board")
        self.at("voices")
        self.assertTrue((self.ep / "storyboard.html").is_file())
        self.cli("voices", "voice-den", "voice-van")
        self.cli("run")
        self.produce.assert_not_called()
        self.cli("run", "--live")
        self.produce.assert_called_once()
        self.at("final")
        self.blocked_release()
        self.approve("final")
        self.cli("release", self.dest)
        self.assertEqual((self.dest / "shorts/mua.mp4").read_bytes(), b"test fixture")
        self.assertEqual([x["gate"] for x in load(self.ep / "approvals.json")],
                         ["script", "board", "final"])

    def test_missing_reference_and_stale_script_version(self):
        self.approve("script")
        self.cli("run", "--live")
        self.cli("ref", "Đen", self.den)
        self.cli("run", "--live")
        self.assertIn("Vằn", self.cli("status"))
        self.frame.assert_not_called()
        self.produce.assert_not_called()
        self.at("refs")
        previous = load(self.ep / "approvals.json")[0]["version"]
        with (self.ep / "kich-ban.md").open("a", encoding="utf-8") as script:
            script.write("\nĐen bước trở vào nhà.")
        self.at("script")
        with self.assertRaises(ValueError):
            self.cli("approve", "script", previous)
        self.blocked_release()

    def test_changed_reference_requires_new_board(self):
        self.create_final()
        self.approve("final")
        self.cli("ref", "Đen", self.den)
        self.at("ready")
        old_board = load(self.ep / "approvals.json")[1]["version"]
        self.den.write_bytes(PNG + b"new source")
        self.cli("ref", "Đen", self.den, "--replace")
        self.at("frames")
        self.blocked_release()
        self.cli("run", "--live")
        self.assertNotEqual(self.at("board")["version"], old_board)
        with self.assertRaises(ValueError):
            self.cli("approve", "board", old_board)

    def test_retake_and_changed_release_media_require_new_final(self):
        first = self.create_final()
        self.approve("final")
        (first["file"] / "shorts/mua.mp4").write_bytes(b"replacement short")
        self.assertNotEqual(self.at("final")["version"], first["version"])
        self.blocked_release()
        with self.assertRaises(ValueError):
            self.cli("approve", "final", first["version"])
        self.approve("final")
        self.cli("retake", "video", "S001", "Sửa bước chân")
        self.at("produce")
        self.blocked_release()
        self.cli("run", "--live")
        self.at("final")
        self.assertEqual(self.produce.call_count, 2)

    def test_retry_reuses_finished_frames(self):
        self.approve("script")
        self.cli("run", "--live")
        self.cli("ref", "Đen", self.den)
        self.cli("ref", "Vằn", self.van)
        self.frame.side_effect = [PNG, PNG, TimeoutError("mất kết nối")]
        with self.assertRaises(TimeoutError):
            self.cli("run", "--live")
        self.assertEqual(len(list((self.ep / "frames").glob("*.png"))), 1)
        self.at("frames")
        self.frame.reset_mock()
        self.frame.side_effect = None
        self.cli("run", "--live")
        self.assertEqual(self.frame.call_count, 47)
        self.at("board")

    def test_next_episode_reuses_approved_location_and_character_profiles(self):
        previous = self.ep
        self.create_board()
        self.assertIn("nha-mai-ngoi", (previous / "storyboard.html").read_text(encoding="utf-8"))
        self.ep = self.root / "next"
        with self.assertRaisesRegex(ValueError, "duyệt storyboard"):
            self.cli("init", "--brief", "Hai bạn trở lại sân.", "--from-episode", previous)
        self.ep = previous
        first_board = self.approve("board")
        old = self.at("voices")

        self.ep = self.root / "next"
        self.cli("init", "--brief", "Hai bạn trở lại sân.", "--from-episode", previous)
        saved_location = self.ep / "locations" / "nha-mai-ngoi.png"
        self.assertEqual(saved_location.read_bytes(), old["locations"]["nha-mai-ngoi"].read_bytes())
        self.assertEqual(load(self.ep / "storyboard-nguon.json")["board"], first_board)
        for char in CAST:
            source = planning.character_profile(previous, old["identity"], char)
            self.assertEqual(planning.character_profile(self.ep, old["identity"], char).read_bytes(),
                             source.read_bytes())
        save(self.ep / "kich-ban.md", "Đen và Vằn trở lại mái hiên trong nắng.")
        self.approve("script")
        self.respond.reset_mock()
        self.frame.reset_mock()
        self.cli("run", "--live")
        self.assertEqual(self.at("board")["locations"]["nha-mai-ngoi"], saved_location)
        self.assertEqual(self.frame.call_count, 48)
        self.assertTrue(all(call.args[1][-1] == saved_location for call in self.frame.call_args_list))
        self.assertTrue(all(call.kwargs.get("structured") for call in self.respond.call_args_list))

    def test_location_retake_reuses_source_and_requires_approval(self):
        self.create_board()
        original_version = self.approve("board")
        original = self.at("voices")["locations"]["nha-mai-ngoi"]
        self.cli("retake", "location", "nha-mai-ngoi", "Giữ mặt sân, mở góc thấy cột hiên.")
        self.at("locations")
        self.frame.reset_mock()
        self.frame.side_effect = [PNG + b"new location"] + [PNG] * 48
        self.cli("run", "--live")
        current = self.at("board")
        self.assertEqual(self.frame.call_args_list[0].args[1], [original])
        self.assertNotEqual(current["version"], original_version)
        self.assertNotEqual(current["locations"]["nha-mai-ngoi"], original)
        with self.assertRaises(ValueError):
            self.cli("approve", "board", original_version)

    def test_retry_resumes_video_job_using_saved_id(self):
        folder = self.ep / "assets/clips"
        shot = {"id": "S001", "duration": 10, "action": "Đen đi", "camera": "Tĩnh",
                "continuity": "Đen bên trái"}
        with patch.object(production.providers, "start_video", return_value="job-42") as start, \
             patch.object(production.providers, "finish_video",
                          side_effect=[TimeoutError("đang tạo"), b"clip"]) as finish:
            with self.assertRaises(TimeoutError):
                production.video_asset(folder, shot, self.den, {})
            asset = production.video_asset(folder, shot, self.den, {})
            self.assertEqual(asset.read_bytes(), b"clip")
            self.assertEqual(production.video_asset(folder, shot, self.den, {}), asset)
            start.assert_called_once()
            self.assertEqual([c.args for c in finish.call_args_list], [("job-42",), ("job-42",)])

    def test_planned_lines_match_approved_dialogue(self):
        script = "**Đen** — Mưa rồi.\n\n**Vằn** — Tới."
        a = {"who": "Đen", "text": "Mưa rồi."}
        b = {"who": "Vằn", "text": "Tới."}
        planning.check_dialogue(script, [{"lines": [a]}, {"lines": [b]}])
        for reason, lines in (
            ("đổi lời", [dict(a, text="Mưa."), b]),
            ("đổi vai", [a, dict(b, who="Đen")]),
            ("đảo thứ tự", [b, a]),
            ("trùng", [a, a, b]),
            ("thiếu", [a]),
        ):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                planning.check_dialogue(script, [{"lines": lines}])


if __name__ == "__main__":
    unittest.main()
