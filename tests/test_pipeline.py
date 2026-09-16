import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
FORMATTER = PROJECT_DIR / "tools" / "json_to_timed_text.py"
PIPELINE = PROJECT_DIR / "voice-convert.sh"


class VoiceConversionTests(unittest.TestCase):
    def test_formatter_writes_timestamped_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "raw.json"
            target = tmp_path / "timed.txt"
            source.write_text(
                json.dumps(
                    {
                        "transcription": [
                            {
                                "timestamps": {
                                    "from": "00:00:01,250",
                                    "to": "00:00:03,500",
                                },
                                "text": "第一句",
                            },
                            {
                                "timestamps": {
                                    "from": "00:00:04,000",
                                    "to": "00:00:05,125",
                                },
                                "text": "  第二句  ",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                ["python3", str(FORMATTER), str(source), str(target)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "[00:00:01.250 --> 00:00:03.500] 第一句\n"
                "[00:00:04.000 --> 00:00:05.125] 第二句\n",
            )

    def test_pipeline_preserves_source_and_creates_expected_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "语音 转换"
            input_path = tmp_path / "组会 录音.qta"
            input_path.write_bytes(b"original-audio")

            fake_ffmpeg = tmp_path / "fake-ffmpeg"
            fake_ffmpeg.write_text(
                "#!/bin/sh\n"
                "for last_arg do :; done\n"
                "printf 'converted-audio' > \"$last_arg\"\n",
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(0o755)

            fake_whisper = tmp_path / "fake-whisper"
            fake_whisper.write_text(
                "#!/bin/sh\n"
                "out=''\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '-of' ]; then out=$2; shift 2; else shift; fi\n"
                "done\n"
                "cat > \"${out}.json\" <<'JSON'\n"
                "{\"transcription\":[{\"timestamps\":{\"from\":\"00:00:00,000\",\"to\":\"00:00:02,000\"},\"text\":\"会议内容\"}]}\n"
                "JSON\n",
                encoding="utf-8",
            )
            fake_whisper.chmod(0o755)

            model = tmp_path / "model.bin"
            model.write_bytes(b"model")

            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(app_home),
                    "FFMPEG_BIN": str(fake_ffmpeg),
                    "WHISPER_BIN": str(fake_whisper),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_RUN_ID": "2026-09-16_150000",
                }
            )
            completed = subprocess.run(
                ["bash", str(PIPELINE), str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result_dir = app_home / "results" / "2026-09-16_150000_组会_录音"
            self.assertEqual(
                (result_dir / "原始录音.qta").read_bytes(), b"original-audio"
            )
            self.assertEqual(
                (result_dir / "完整转写_带时间戳.txt").read_text(encoding="utf-8"),
                "[00:00:00.000 --> 00:00:02.000] 会议内容\n",
            )
            raw = json.loads(
                (result_dir / "原始识别.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw["transcription"][0]["text"], "会议内容")
            summary = (result_dir / "会议总结.md").read_text(encoding="utf-8")
            self.assertIn("待 Codex 根据完整转写生成", summary)
            self.assertIn("## 会议主题与背景", summary)
            self.assertIn("## 核心讨论与结论", summary)
            self.assertIn("## 待办事项", summary)
            self.assertIn("## 未解决问题", summary)
            self.assertTrue((result_dir / "运行日志.log").is_file())
            self.assertFalse((result_dir / ".work").exists())
            self.assertIn(str(result_dir), completed.stdout)


if __name__ == "__main__":
    unittest.main()
