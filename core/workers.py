from __future__ import annotations

import threading
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from .database import Database
from .processor import process_one
from .scanner import FileEntry, scan


class ScanWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: Path, output: Path, database: Path, ffprobe: str,
                 copy_lrc: bool, keep_structure: bool):
        super().__init__()
        self.args = source, output, database, ffprobe, copy_lrc, keep_structure

    def run(self):
        try:
            source, output, database, ffprobe, copy_lrc, keep_structure = self.args
            db = Database(database)
            result = scan(source, output, db, ffprobe, copy_lrc, keep_structure)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ProcessWorker(QThread):
    file_started = Signal(str, int, int)
    file_finished = Signal(str, str, str)
    completed = Signal(bool)

    def __init__(self, entries: list[FileEntry], source: Path, output: Path, database: Path,
                 qmdec: str, ffprobe: str, keep_structure: bool, keep_filename: bool, log_path: Path):
        super().__init__()
        self.entries = entries
        self.source = source
        self.output = output
        self.database = database
        self.qmdec = qmdec
        self.ffprobe = ffprobe
        self.keep_structure = keep_structure
        self.keep_filename = keep_filename
        self.log_path = log_path
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()

    def run(self):
        db = Database(self.database)
        total = len(self.entries)
        completed_count = 0
        for entry in self.entries:
            if self.stop_event.is_set():
                break
            self.pause_event.wait()
            if self.stop_event.is_set():
                break
            completed_count += 1
            self.file_started.emit(entry.relative, completed_count, total)
            status, error = process_one(entry, self.source, self.output, db, self.qmdec, self.ffprobe,
                                        self.keep_structure, self.keep_filename, self.log_path)
            self.file_finished.emit(entry.relative, status, error)
        self.completed.emit(self.stop_event.is_set())
