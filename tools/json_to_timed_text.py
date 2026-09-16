#!/usr/bin/env python3
"""Convert whisper.cpp JSON output into a readable timestamped transcript."""

import json
import sys
from pathlib import Path


def format_timestamp(value: str) -> str:
    return value.replace(",", ".")


def convert(source: Path, target: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    lines: list[str] = []

    for segment in payload.get("transcription", []):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        timestamps = segment.get("timestamps", {})
        start = format_timestamp(str(timestamps.get("from", "")))
        end = format_timestamp(str(timestamps.get("to", "")))
        lines.append(f"[{start} --> {end}] {text}")

    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {Path(sys.argv[0]).name} INPUT.json OUTPUT.txt", file=sys.stderr)
        return 2

    convert(Path(sys.argv[1]), Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
