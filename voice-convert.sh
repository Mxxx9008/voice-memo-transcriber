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
LAUNCHCTL="${VOICE_LAUNCHCTL_BIN:-$(command -v launchctl || true)}"
THREADS="${VOICE_THREADS:-4}"

usage() {
  printf 'Usage: %s [--foreground|--background] <Voice Memo audio file>\n' "$(basename "$0")" >&2
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

write_status() {
  status_value="$1"
  status_temp="$STATUS_FILE.tmp.$$"
  printf '%s\n' "$status_value" > "$status_temp"
  mv -f "$status_temp" "$STATUS_FILE"
}

validate_dependencies() {
  [[ -f "$INPUT_PATH" ]] || fail "audio file not found: $INPUT_PATH"
  [[ -n "$FFMPEG" && -x "$FFMPEG" ]] || fail "ffmpeg is not installed or executable"
  [[ -x "$WHISPER" ]] || fail "whisper.cpp is not installed: $WHISPER"
  [[ -n "$PYTHON" && -x "$PYTHON" ]] || fail "python3 is not installed or executable"
  [[ -f "$MODEL_PATH" ]] || fail "Whisper model is missing: $MODEL_PATH"
}

reserve_result_dir() {
  mkdir -p "$RESULTS_DIR"
  result_base="$RESULTS_DIR/${RUN_ID}_${SAFE_STEM}"
  RESULT_DIR="$result_base"
  result_suffix=2

  while ! mkdir "$RESULT_DIR" 2>/dev/null; do
    if [[ -e "$RESULT_DIR" ]]; then
      RESULT_DIR="${result_base}_${result_suffix}"
      result_suffix=$((result_suffix + 1))
    else
      fail "could not create result directory: $RESULT_DIR"
    fi
  done

  STATUS_FILE="$RESULT_DIR/状态.txt"
  write_status "处理中"
}

BACKGROUND=1
if [[ $# -eq 2 && "$1" == "--foreground" ]]; then
  BACKGROUND=0
  shift
elif [[ $# -eq 2 && "$1" == "--background" ]]; then
  shift
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

INPUT_PATH="$1"

absolute_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$PWD" "$1" ;;
  esac
}

APP_HOME="$(absolute_path "$APP_HOME")"
TOOLS_DIR="$(absolute_path "$TOOLS_DIR")"
RESULTS_DIR="$APP_HOME/results"
MODEL_PATH="$(absolute_path "$MODEL_PATH")"
[[ -z "$FFMPEG" ]] || FFMPEG="$(absolute_path "$FFMPEG")"
WHISPER="$(absolute_path "$WHISPER")"
[[ -z "$PYTHON" ]] || PYTHON="$(absolute_path "$PYTHON")"
[[ -z "$LAUNCHCTL" ]] || LAUNCHCTL="$(absolute_path "$LAUNCHCTL")"
INPUT_PATH="$(absolute_path "$INPUT_PATH")"

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

if [[ "$BACKGROUND" -eq 1 ]]; then
  validate_dependencies
  [[ -n "$LAUNCHCTL" && -x "$LAUNCHCTL" ]] || fail "launchctl is not installed or executable"
  reserve_result_dir

  launcher_cleanup() {
    exit_code=$?
    if [[ "$exit_code" -ne 0 ]]; then
      write_status "失败（退出码：${exit_code}）"
    fi
  }
  trap launcher_cleanup EXIT

  JOBS_DIR="$APP_HOME/jobs"
  JOB_ID="$(basename "$RESULT_DIR")"
  JOB_LOG="$JOBS_DIR/${JOB_ID}.log"
  JOB_LABEL="com.mxxx9008.voice-memo-transcriber.$(date '+%s').$$.$RANDOM"
  mkdir -p "$JOBS_DIR"

  if "$LAUNCHCTL" submit -l "$JOB_LABEL" -o "$JOB_LOG" -e "$JOB_LOG" -- \
    /bin/bash -c '"$@"; code=$?; launchctl remove "$0" >/dev/null 2>&1; exit "$code"' \
    "$JOB_LABEL" /usr/bin/env \
    VOICE_RUN_ID="$RUN_ID" \
    VOICE_RESULT_DIR="$RESULT_DIR" \
    VOICE_CONVERT_HOME="$APP_HOME" \
    VOICE_TOOLS_DIR="$TOOLS_DIR" \
    VOICE_MODEL_PATH="$MODEL_PATH" \
    FFMPEG_BIN="$FFMPEG" \
    WHISPER_BIN="$WHISPER" \
    PYTHON_BIN="$PYTHON" \
    VOICE_THREADS="$THREADS" \
    "$SCRIPT_DIR/voice-convert.sh" --foreground "$INPUT_PATH"; then
    :
  else
    launch_status=$?
    write_status "失败（退出码：${launch_status}）"
    trap - EXIT
    fail "launchctl could not start the background job"
  fi
  trap - EXIT

  printf '已启动后台转写（launchd 任务 %s）\n' "$JOB_LABEL"
  printf '结果目录：%s\n' "$RESULT_DIR"
  printf '任务日志：%s\n' "$JOB_LOG"
  exit 0
fi

if [[ -n "${VOICE_RESULT_DIR:-}" ]]; then
  RESULT_DIR="$VOICE_RESULT_DIR"
  [[ -d "$RESULT_DIR" ]] || fail "reserved result directory is missing: $RESULT_DIR"
  STATUS_FILE="$RESULT_DIR/状态.txt"
else
  reserve_result_dir
fi

WORK_DIR="$RESULT_DIR/.work"
LOG_FILE="$RESULT_DIR/运行日志.log"

cleanup() {
  exit_code=$?
  rm -rf "$WORK_DIR"
  if [[ "$exit_code" -eq 0 ]]; then
    write_status "完成"
  else
    write_status "失败（退出码：${exit_code}）"
  fi
}
trap cleanup EXIT

mkdir -p "$WORK_DIR"
validate_dependencies

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
