import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
FORMATTER = PROJECT_DIR / "tools" / "json_to_timed_text.py"
PIPELINE = PROJECT_DIR / "voice-convert.sh"


class VoiceConversionTests(unittest.TestCase):
    def write_fake_launchctl(self, path: Path) -> Path:
        marker = path / "launchctl-called"
        launcher = path / "fake-launchctl"
        launcher.write_text(
            "#!/bin/sh\n"
            "printf 'called\\n' > \"$FAKE_LAUNCHCTL_MARKER\"\n"
            "stdout=/dev/null\n"
            "stderr=/dev/null\n"
            "while [ $# -gt 0 ] && [ \"$1\" != '--' ]; do\n"
            "  if [ \"$1\" = '-o' ]; then stdout=$2; shift 2;\n"
            "  elif [ \"$1\" = '-e' ]; then stderr=$2; shift 2;\n"
            "  else shift; fi\n"
            "done\n"
            "shift\n"
            "(cd \"${FAKE_LAUNCH_CWD:-$PWD}\"; "
            "sleep \"${FAKE_LAUNCH_DELAY:-0}\"; \"$@\") "
            ">\"$stdout\" 2>\"$stderr\" </dev/null &\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        return marker

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

    def test_formatter_replaces_invalid_utf8_from_whisper_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "raw.json"
            target = tmp_path / "timed.txt"
            source.write_bytes(
                b'{"transcription":[{"timestamps":{"from":"00:00:01,000",'
                b'"to":"00:00:02,000"},"text":"broken-\xe7\xab"}]}'
            )

            completed = subprocess.run(
                ["python3", str(FORMATTER), str(source), str(target)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "[00:00:01.000 --> 00:00:02.000] broken-�\n",
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
                "threads=''\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = '-of' ]; then out=$2; shift 2;\n"
                "  elif [ \"$1\" = '-t' ]; then threads=$2; shift 2;\n"
                "  else shift; fi\n"
                "done\n"
                "if [ \"$threads\" != '4' ]; then\n"
                "  printf 'expected 4 threads, got %s\\n' \"$threads\" >&2\n"
                "  exit 9\n"
                "fi\n"
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
                ["bash", str(PIPELINE), "--foreground", str(input_path)],
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

    def test_default_mode_runs_in_background_and_marks_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "长录音处理"
            input_path = tmp_path / "长 会议.qta"
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
                "sleep 0.2\n"
                "printf '%s' '{\"transcription\":[]}' > \"${out}.json\"\n",
                encoding="utf-8",
            )
            fake_whisper.chmod(0o755)

            model = tmp_path / "model.bin"
            model.write_bytes(b"model")
            marker = self.write_fake_launchctl(tmp_path)
            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(app_home),
                    "FFMPEG_BIN": str(fake_ffmpeg),
                    "WHISPER_BIN": str(fake_whisper),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_RUN_ID": "2026-09-16_190000",
                    "VOICE_LAUNCHCTL_BIN": str(tmp_path / "fake-launchctl"),
                    "FAKE_LAUNCHCTL_MARKER": str(marker),
                    "FAKE_LAUNCH_DELAY": "0.2",
                    "FAKE_LAUNCH_CWD": "/",
                }
            )

            completed = subprocess.run(
                ["bash", str(PIPELINE), input_path.name],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp_path,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("已启动后台转写", completed.stdout)
            self.assertTrue(marker.is_file())

            result_dir = app_home / "results" / "2026-09-16_190000_长_会议"
            self.assertEqual(
                (result_dir / "状态.txt").read_text(encoding="utf-8").strip(),
                "处理中",
            )
            deadline = time.monotonic() + 5
            status = result_dir / "状态.txt"
            while time.monotonic() < deadline:
                if status.exists() and status.read_text(encoding="utf-8").strip() == "完成":
                    break
                time.sleep(0.05)

            self.assertEqual(status.read_text(encoding="utf-8").strip(), "完成")
            self.assertTrue((result_dir / "原始识别.json").is_file())
            self.assertTrue((result_dir / "完整转写_带时间戳.txt").is_file())
            self.assertFalse((result_dir / ".work").exists())

    def test_background_failure_is_recorded_in_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "失败任务"
            input_path = tmp_path / "无法识别.qta"
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
            fake_whisper.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            fake_whisper.chmod(0o755)

            model = tmp_path / "model.bin"
            model.write_bytes(b"model")
            marker = self.write_fake_launchctl(tmp_path)
            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(app_home),
                    "FFMPEG_BIN": str(fake_ffmpeg),
                    "WHISPER_BIN": str(fake_whisper),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_RUN_ID": "2026-09-18_120000",
                    "VOICE_LAUNCHCTL_BIN": str(tmp_path / "fake-launchctl"),
                    "FAKE_LAUNCHCTL_MARKER": str(marker),
                }
            )

            completed = subprocess.run(
                ["bash", str(PIPELINE), str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            status = app_home / "results" / "2026-09-18_120000_无法识别" / "状态.txt"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if status.exists() and status.read_text(encoding="utf-8").startswith("失败"):
                    break
                time.sleep(0.05)

            self.assertEqual(status.read_text(encoding="utf-8").strip(), "失败（退出码：7）")
            self.assertFalse((status.parent / ".work").exists())

    def test_repeated_run_id_allocates_distinct_result_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "重复任务"
            input_path = tmp_path / "同名录音.qta"
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
                "printf '%s' '{\"transcription\":[]}' > \"${out}.json\"\n",
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
                    "VOICE_RUN_ID": "2026-09-18_130000",
                }
            )

            first = subprocess.run(
                ["bash", str(PIPELINE), "--foreground", str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )
            second = subprocess.run(
                ["bash", str(PIPELINE), "--foreground", str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_result = Path(first.stdout.strip().splitlines()[-1])
            second_result = Path(second.stdout.strip().splitlines()[-1])
            self.assertNotEqual(first_result, second_result)
            self.assertEqual(
                sorted(path.name for path in (app_home / "results").iterdir()),
                [
                    "2026-09-18_130000_同名录音",
                    "2026-09-18_130000_同名录音_2",
                ],
            )

    def test_launcher_failure_records_launchctl_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "启动失败"
            input_path = tmp_path / "录音.qta"
            input_path.write_bytes(b"original-audio")

            fake_ffmpeg = tmp_path / "fake-ffmpeg"
            fake_ffmpeg.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_ffmpeg.chmod(0o755)
            fake_whisper = tmp_path / "fake-whisper"
            fake_whisper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_whisper.chmod(0o755)
            fake_launchctl = tmp_path / "fake-launchctl"
            fake_launchctl.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
            fake_launchctl.chmod(0o755)
            model = tmp_path / "model.bin"
            model.write_bytes(b"model")

            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(app_home),
                    "FFMPEG_BIN": str(fake_ffmpeg),
                    "WHISPER_BIN": str(fake_whisper),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_LAUNCHCTL_BIN": str(fake_launchctl),
                    "VOICE_RUN_ID": "2026-09-18_140000",
                }
            )
            completed = subprocess.run(
                ["bash", str(PIPELINE), str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertNotEqual(completed.returncode, 0)
            status = app_home / "results" / "2026-09-18_140000_录音" / "状态.txt"
            self.assertEqual(
                status.read_text(encoding="utf-8").strip(),
                "失败（退出码：23）",
            )

    def test_uncreatable_result_name_fails_without_retrying_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "录音.qta"
            input_path.write_bytes(b"audio")
            fake_tool = tmp_path / "fake-tool"
            fake_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_tool.chmod(0o755)
            model = tmp_path / "model.bin"
            model.write_bytes(b"model")
            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(tmp_path / "app"),
                    "FFMPEG_BIN": str(fake_tool),
                    "WHISPER_BIN": str(fake_tool),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_RUN_ID": "x" * 300,
                }
            )

            process = subprocess.Popen(
                ["bash", str(PIPELINE), "--foreground", str(input_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.communicate(timeout=2)
                self.fail("result directory allocation retried forever")

            self.assertNotEqual(process.returncode, 0)

    def test_worker_setup_failure_updates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result_dir = tmp_path / "reserved-result"
            result_dir.mkdir()
            (result_dir / "状态.txt").write_text("处理中\n", encoding="utf-8")
            (result_dir / ".work").write_text("blocks mkdir", encoding="utf-8")
            input_path = tmp_path / "录音.qta"
            input_path.write_bytes(b"audio")
            fake_tool = tmp_path / "fake-tool"
            fake_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_tool.chmod(0o755)
            model = tmp_path / "model.bin"
            model.write_bytes(b"model")
            env = os.environ.copy()
            env.update(
                {
                    "VOICE_RESULT_DIR": str(result_dir),
                    "FFMPEG_BIN": str(fake_tool),
                    "WHISPER_BIN": str(fake_tool),
                    "VOICE_MODEL_PATH": str(model),
                }
            )

            completed = subprocess.run(
                ["bash", str(PIPELINE), "--foreground", str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(
                (result_dir / "状态.txt")
                .read_text(encoding="utf-8")
                .strip()
                .startswith("失败")
            )

    def test_launcher_setup_failure_updates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            app_home = tmp_path / "app"
            app_home.mkdir()
            (app_home / "jobs").write_text("blocks mkdir", encoding="utf-8")
            input_path = tmp_path / "录音.qta"
            input_path.write_bytes(b"audio")
            fake_tool = tmp_path / "fake-tool"
            fake_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_tool.chmod(0o755)
            model = tmp_path / "model.bin"
            model.write_bytes(b"model")
            env = os.environ.copy()
            env.update(
                {
                    "VOICE_CONVERT_HOME": str(app_home),
                    "FFMPEG_BIN": str(fake_tool),
                    "WHISPER_BIN": str(fake_tool),
                    "VOICE_MODEL_PATH": str(model),
                    "VOICE_RUN_ID": "2026-09-18_150000",
                }
            )

            completed = subprocess.run(
                ["bash", str(PIPELINE), str(input_path)],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertNotEqual(completed.returncode, 0)
            status = app_home / "results" / "2026-09-18_150000_录音" / "状态.txt"
            self.assertTrue(status.read_text(encoding="utf-8").strip().startswith("失败"))


if __name__ == "__main__":
    unittest.main()
