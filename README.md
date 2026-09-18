# Voice Memo Transcriber

面向 macOS 的本地离线语音转写工具。将语音备忘录等音频文件交给一个脚本，即可通过 `whisper.cpp` 生成带时间戳的完整转写、原始识别 JSON 和会议总结模板。

> 识别全程在本机运行，脚本不会将录音或转写结果上传到云端。

## 功能

- 接收 `.qta`、`.m4a`、`.mp3`、`.wav` 等 `ffmpeg` 可解码的音频文件
- 自动转换为 16 kHz 单声道中间音频
- 使用 `whisper.cpp` 离线进行中文识别
- 默认以后台任务运行，不需要让终端或 AI Agent 持续等待
- 默认使用 4 个 CPU 线程的均衡模式，兼顾识别质量与发热
- 保存带时间戳的完整转写和原始 JSON
- 保留原始录音和运行日志
- 生成可继续填充的会议总结模板
- 处理完成后自动删除临时音频

## 环境要求

- macOS（当前默认配置适用于 Apple Silicon Mac）
- [Homebrew](https://brew.sh/)
- Python 3
- 约 550 MB 磁盘空间用于默认 Whisper 模型

## 安装

1. 克隆仓库：

   ```bash
   git clone https://github.com/Mxxx9008/voice-memo-transcriber.git
   cd voice-memo-transcriber
   ```

2. 安装依赖：

   ```bash
   brew install ffmpeg whisper-cpp python
   ```

3. 下载默认模型：

   ```bash
   mkdir -p models
   curl -L \
     -o models/ggml-large-v3-turbo-q5_0.bin \
     https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
   ```

## 使用

```bash
./voice-convert.sh "/path/to/语音备忘录.qta"
```

命令会立即返回 `launchd` 任务名称、结果目录和任务日志路径。转写由 macOS 后台服务托管，不再需要 Codex 或终端会话持续等待；任务结束后会自动从 `launchd` 注销。

可以随时查看任务状态：

```bash
cat "results/<任务目录>/状态.txt"
```

状态为 `处理中`、`完成` 或 `失败（退出码：N）`。需要调试时，可显式使用前台模式：

```bash
./voice-convert.sh --foreground "/path/to/语音备忘录.qta"
```

结果默认保存在：

```text
results/
└── 2026-09-16_150000_录音名称/
    ├── 原始录音.qta
    ├── 完整转写_带时间戳.txt
    ├── 原始识别.json
    ├── 会议总结.md
    ├── 运行日志.log
    └── 状态.txt
```

`voice-convert.sh` 只生成会议总结的结构化模板，不会自动调用云端 AI 生成总结。可以将完整转写交给 Codex 或其他工具进一步整理。

## 可选配置

可通过环境变量替换默认组件：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `VOICE_MODEL_PATH` | Whisper 模型路径 | `models/ggml-large-v3-turbo-q5_0.bin` |
| `WHISPER_BIN` | `whisper-cli` 可执行文件 | `/opt/homebrew/opt/whisper.cpp/bin/whisper-cli` |
| `FFMPEG_BIN` | `ffmpeg` 可执行文件 | `PATH` 中的 `ffmpeg` |
| `PYTHON_BIN` | Python 3 可执行文件 | `PATH` 中的 `python3` |
| `VOICE_THREADS` | 识别线程数 | `4` |
| `VOICE_CONVERT_HOME` | 结果根目录 | 项目目录 |

例如，Intel Mac 或自定义 Homebrew 路径可以这样运行：

```bash
WHISPER_BIN="$(brew --prefix whisper-cpp)/bin/whisper-cli" \
  ./voice-convert.sh "/path/to/recording.m4a"
```

## 测试

测试使用模拟的 `ffmpeg` 和 `whisper.cpp` 验证整个文件处理流程，不需要下载模型：

```bash
python3 -m unittest discover -s tests -v
```

## 隐私与仓库内容

`models/`、`results/` 和 `jobs/` 已经加入 `.gitignore`，因此本地模型、录音、转写、总结和日志不会被常规 Git 操作提交。公开分享仓库前仍建议使用 `git status` 检查待提交文件。

## 当前限制

- 默认识别语言固定为中文。
- 结果中的会议总结是模板，需要后续填充。
- 识别速度取决于音频时长、模型大小和 Mac 硬件性能。
- 仓库目前未添加开源许可证，默认不授予复制、修改或分发权利。
