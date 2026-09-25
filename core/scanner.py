from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import tempfile

from .database import Database
from .verifier import verify_audio


SUPPORTED = {".mflac", ".mgg", ".qmc0", ".qmc2", ".qmc3", ".qmcflac", ".qmcogg"}
OUTPUT_EXTENSIONS = (".flac", ".ogg", ".mp3", ".m4a", ".wav", ".bin")


@dataclass
class FileEntry:
    source: Path
    relative: str
    filename: str
    extension: str
    size: int
    mtime: float
    status: str
    output_relative: str = ""
    error: str = ""


@dataclass
class ScanResult:
    entries: list[FileEntry]
    total_files: int
    supported_count: int
    new_count: int
    done_count: int
    skipped_count: int
    failed_count: int
    unsupported_count: int
    lrc_copied: int


def sync_lrcs(source: Path, output: Path, files: list[Path], keep_structure: bool) -> int:
    copied = 0
    for src in files:
        try:
            rel = src.relative_to(source)
            dst = output / rel if keep_structure else output / rel.name
            if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.read_bytes() == src.read_bytes():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".lrc-", dir=dst.parent)
            os.close(fd)
            tmp = Path(temp_name)
            try:
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
            finally:
                tmp.unlink(missing_ok=True)
            copied += 1
        except OSError:
            continue
    return copied


def scan(source: Path, output: Path, db: Database, ffprobe: str, copy_lrc: bool = True,
         keep_structure: bool = True) -> ScanResult:
    all_files = [p for p in source.rglob("*") if p.is_file()]
    audio_files = sorted((p for p in all_files if p.suffix.lower() in SUPPORTED), key=lambda p: str(p).casefold())
    lrc_files = [p for p in all_files if p.suffix.lower() == ".lrc"]
    lrc_copied = sync_lrcs(source, output, lrc_files, keep_structure) if copy_lrc else 0
    entries: list[FileEntry] = []
    counts = {"pending": 0, "success": 0, "skipped": 0, "failed": 0}

    for src in audio_files:
        rel_path = src.relative_to(source)
        rel = rel_path.as_posix()
        stat = src.stat()
        record = db.get(rel)
        status, output_rel, error = "pending", "", ""
        if record and record["source_size"] == stat.st_size and record["source_mtime"] == stat.st_mtime:
            if record["status"] == "failed":
                status, error = "failed", record["error_message"] or "Previous attempt failed"
            elif record["status"] == "success" and record["output_relative_path"]:
                previous = output / Path(record["output_relative_path"])
                valid, why = verify_audio(ffprobe, previous)
                if valid:
                    status, output_rel = "success", record["output_relative_path"]
                else:
                    status, error = "pending", why
        if status == "pending":
            db.upsert_source(rel, src.name, stat.st_size, stat.st_mtime)
            if not record:
                for ext in OUTPUT_EXTENSIONS:
                    candidate_rel = rel_path.with_name(rel_path.stem + ext)
                    if not keep_structure:
                        candidate_rel = Path(candidate_rel.name)
                    candidate = output / candidate_rel
                    if candidate.is_file():
                        valid, _ = verify_audio(ffprobe, candidate)
                        if valid:
                            status, output_rel = "skipped", candidate_rel.as_posix()
                            db.mark_success(rel, output_rel, candidate.stat().st_size)
                            break
        entries.append(FileEntry(src, rel, src.name, src.suffix[1:].upper(), stat.st_size, stat.st_mtime, status, output_rel, error))
        counts[status] += 1

    unsupported_count = sum(1 for p in all_files if p.suffix.lower() not in SUPPORTED and p.suffix.lower() != ".lrc")
    unsupported = [FileEntry(p, p.relative_to(source).as_posix(), p.name, p.suffix[1:].upper() or "FILE",
                             p.stat().st_size, p.stat().st_mtime, "unsupported")
                   for p in all_files if p.suffix.lower() not in SUPPORTED and p.suffix.lower() != ".lrc"]
    entries.extend(unsupported)
    return ScanResult(entries, len(all_files), len(audio_files), counts["pending"], counts["success"],
                      counts["skipped"], counts["failed"], unsupported_count, lrc_copied)
