#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_HOME="${VOICE_CONVERT_HOME:-$SCRIPT_DIR}"
TOOLS_DIR="${VOICE_TOOLS_DIR:-$SCRIPT_DIR/tools}"
RESULTS_DIR="$APP_HOME/results"
MODEL_PATH="${VOICE_MODEL_PATH:-$APP_HOME/models/ggml-large-v3-turbo-q5_0.bin}"
FFMPEG="${FFMPEG_BIN:-$(command -v ffmpeg || true)}"
WHISPER="${WHISPER_BIN:-/opt/homebrew/opt/whisper.cpp/bin/whisper-cli}"
PYTHON="${PYTHON_BIN:-$(command -v python3 || true)}"
THREADS="${VOICE_THREADS:-8}"

usage() {
  printf 'Usage: %s <Voice Memo audio file>\n' "$(basename "$0")" >&2
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

INPUT_PATH="$1"
[[ -f "$INPUT_PATH" ]] || fail "audio file not found: $INPUT_PATH"
[[ -n "$FFMPEG" && -x "$FFMPEG" ]] || fail "ffmpeg is not installed or executable"
[[ -x "$WHISPER" ]] || fail "whisper.cpp is not installed: $WHISPER"
[[ -n "$PYTHON" && -x "$PYTHON" ]] || fail "python3 is not installed or executable"
[[ -f "$MODEL_PATH" ]] || fail "Whisper model is missing: $MODEL_PATH"

FILE_NAME="$(basename "$INPUT_PATH")"
if [[ "$FILE_NAME" == *.* ]]; then
  STEM="${FILE_NAME%.*}"
  EXTENSION=".${FILE_NAME##*.}"
else
  STEM="$FILE_NAME"
  EXTENSION=""
fi

SAFE_STEM="$(printf '%s' "$STEM" | sed -E 's#[/:]+#_#g; s/[[:space:]]+/_/g; s/^_+//; s/_+$//')"
[[ -n "$SAFE_STEM" ]] || SAFE_STEM="recording"
RUN_ID="${VOICE_RUN_ID:-$(date '+%Y-%m-%d_%H%M%S')}"
RESULT_DIR="$RESULTS_DIR/${RUN_ID}_${SAFE_STEM}"

if [[ -e "$RESULT_DIR" ]]; then
  fail "result directory already exists: $RESULT_DIR"
fi

WORK_DIR="$RESULT_DIR/.work"
LOG_FILE="$RESULT_DIR/运行日志.log"
mkdir -p "$WORK_DIR"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG_FILE"
}

log "处理开始：$INPUT_PATH"
cp "$INPUT_PATH" "$RESULT_DIR/原始录音$EXTENSION"
log "已保存原始录音"

TEMP_AUDIO="$WORK_DIR/audio.mp3"
log "正在转换为 16 kHz 单声道音频"
"$FFMPEG" -hide_banner -loglevel error -y -i "$INPUT_PATH" \
  -vn -map 0:a:0 -ac 1 -ar 16000 -c:a libmp3lame -b:a 48k "$TEMP_AUDIO" \
  >>"$LOG_FILE" 2>&1

RAW_PREFIX="$WORK_DIR/raw"
log "正在进行离线中文语音识别"
"$WHISPER" -m "$MODEL_PATH" -f "$TEMP_AUDIO" -l zh -t "$THREADS" \
  -oj -of "$RAW_PREFIX" -np >>"$LOG_FILE" 2>&1

[[ -s "$RAW_PREFIX.json" ]] || fail "Whisper did not produce JSON output"
mv "$RAW_PREFIX.json" "$RESULT_DIR/原始识别.json"
"$PYTHON" "$TOOLS_DIR/json_to_timed_text.py" \
  "$RESULT_DIR/原始识别.json" "$RESULT_DIR/完整转写_带时间戳.txt"

cat > "$RESULT_DIR/会议总结.md" <<'EOF'
# 会议总结

> 待 Codex 根据完整转写生成。

## 会议主题与背景

## 核心讨论与结论

## 待办事项

## 未解决问题

## 精炼会议纪要
EOF

log "处理完成"
printf '%s\n' "$RESULT_DIR"
