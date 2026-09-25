from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def verify_audio(ffprobe: str, path: Path) -> tuple[bool, str]:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False, "Output is missing or empty"
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
            "-of", "json", str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode:
            return False, result.stderr.strip()[:1000] or f"ffprobe exit {result.returncode}"
        info = json.loads(result.stdout)
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        duration = float(info.get("format", {}).get("duration") or 0)
        if not has_audio or duration <= 0:
            return False, "No audio stream or positive duration"
        return True, ""
    except Exception as exc:
        return False, f"Verifier error: {exc}"
