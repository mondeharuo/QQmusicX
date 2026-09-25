from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys

from PySide6.QtCore import QSettings, Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

from core.database import Database
from core.scanner import FileEntry, ScanResult, scan
from core.workers import ProcessWorker, ScanWorker


def app_root() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1]
    executable_dir = Path(sys.executable).resolve().parent
    # PyInstaller replaces dist/QQmusicX during each build. Keep user data
    # outside that directory so rebuilding the executable cannot erase it.
    if executable_dir.parent.name.lower() == "dist":
        return executable_dir.parent.parent
    return executable_dir


APP_ROOT = app_root()
DB_PATH = APP_ROOT / "data" / "music_process.db"
LOG_PATH = APP_ROOT / "logs" / "app.log"

STATUS_TEXT = {"pending": "等待", "processing": "正在处理", "success": "已完成",
               "failed": "失败", "skipped": "已跳过", "unsupported": "不支持"}
STATUS_COLOR = {"pending": "#e8edf4", "processing": "#dbeafe", "success": "#dcfce7",
                "failed": "#fee2e2", "skipped": "#fef3c7", "unsupported": "#f1f5f9"}


def find_qmdec() -> str:
    found = shutil.which("qmdec") or shutil.which("qmdec.exe")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    packages = local / "Packages"
    if packages.exists():
        for path in packages.glob("PythonSoftwareFoundation.Python*/LocalCache/local-packages/Python*/Scripts/qmdec.exe"):
            return str(path)
    return ""


def find_ffprobe() -> str:
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        return found
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.exists():
        for folder in winget.glob("Gyan.FFmpeg.Shared_*"):
            matches = list(folder.glob("*/bin/ffprobe.exe"))
            if matches:
                return str(matches[0])
    return ""


class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QQmusicX 设置")
        self.setMinimumWidth(560)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QLineEdit(settings.value("source", r"G:\Music\VipSongsDownload"))
        self.output = QLineEdit(settings.value("output", r"G:\Music\Decoded"))
        self.ffprobe = QLineEdit(settings.value("ffprobe", find_ffprobe()))
        form.addRow("默认源目录", self._browse_row(self.source, directory=True))
        form.addRow("默认输出目录", self._browse_row(self.output, directory=True))
        form.addRow("ffprobe 路径", self._browse_row(self.ffprobe, directory=False))
        layout.addLayout(form)
        self.copy_lrc = QCheckBox("自动复制 LRC（保持文件内容不变）")
        self.copy_lrc.setChecked(settings.value("copy_lrc", True, type=bool))
        self.keep_structure = QCheckBox("保留源目录结构")
        self.keep_structure.setChecked(settings.value("keep_structure", True, type=bool))
        self.keep_filename = QCheckBox("保留原始歌曲 basename")
        self.keep_filename.setChecked(settings.value("keep_filename", True, type=bool))
        self.open_after = QCheckBox("处理完成后打开输出目录")
        self.open_after.setChecked(settings.value("open_after", False, type=bool))
        for check in (self.copy_lrc, self.keep_structure, self.keep_filename, self.open_after):
            layout.addWidget(check)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("保存")
        cancel = QPushButton("取消")
        save.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _browse_row(self, edit: QLineEdit, directory: bool):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        button = QPushButton("浏览…")
        if directory:
            button.clicked.connect(lambda: self._browse_dir(edit))
        else:
            button.clicked.connect(lambda: self._browse_file(edit))
        row.addWidget(button)
        return box

    def _browse_dir(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
        if path:
            edit.setText(path)

    def _browse_file(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "选择 ffprobe.exe", edit.text(), "Programs (ffprobe.exe);;All files (*)")
        if path:
            edit.setText(path)

    def save_values(self):
        self.settings.setValue("source", self.source.text())
        self.settings.setValue("output", self.output.text())
        self.settings.setValue("ffprobe", self.ffprobe.text())
        self.settings.setValue("copy_lrc", self.copy_lrc.isChecked())
        self.settings.setValue("keep_structure", self.keep_structure.isChecked())
        self.settings.setValue("keep_filename", self.keep_filename.isChecked())
        self.settings.setValue("open_after", self.open_after.isChecked())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QQmusicX — 本地音乐批处理")
        self.resize(1120, 760)
        self.settings = QSettings("QQmusicX", "QQmusicX")
        self.entries: list[FileEntry] = []
        self.row_by_rel: dict[str, int] = {}
        self.scan_result: ScanResult | None = None
        self.worker = None
        self.close_after_task = False
        self.rescan_after_process = False
        self._build_ui()
        self._load_settings()
        self._style()
        QTimer.singleShot(250, self.start_scan)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(22, 18, 22, 18)
        main.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("QQmusicX")
        title.setObjectName("appTitle")
        subtitle = QLabel("QQ Music 本地批处理")
        subtitle.setObjectName("subtitle")
        titles = QVBoxLayout()
        titles.addWidget(title)
        titles.addWidget(subtitle)
        title_row.addLayout(titles)
        title_row.addStretch(1)
        self.settings_button = QPushButton("⚙ 设置")
        self.settings_button.clicked.connect(self.open_settings)
        title_row.addWidget(self.settings_button)
        main.addLayout(title_row)

        paths = QFormLayout()
        self.source_edit = QLineEdit()
        self.output_edit = QLineEdit()
        paths.addRow("源文件夹", self._path_row(self.source_edit, True))
        paths.addRow("输出文件夹", self._path_row(self.output_edit, True))
        main.addLayout(paths)

        checks = QHBoxLayout()
        self.structure_check = QCheckBox("保留目录结构")
        self.lrc_check = QCheckBox("自动复制 LRC")
        self.skip_check = QCheckBox("跳过已处理文件")
        self.skip_check.setChecked(True)
        self.name_check = QCheckBox("保留原始文件名")
        for item in (self.structure_check, self.lrc_check, self.skip_check, self.name_check):
            checks.addWidget(item)
        checks.addStretch(1)
        main.addLayout(checks)

        action_row = QHBoxLayout()
        self.scan_button = QPushButton("扫描")
        self.scan_button.clicked.connect(self.start_scan)
        self.start_button = QPushButton("▶ 开始处理")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_processing)
        action_row.addWidget(self.scan_button)
        action_row.addStretch(1)
        action_row.addWidget(self.start_button)
        main.addLayout(action_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件名", "相对目录", "类型", "大小", "状态"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        main.addWidget(self.table, 1)

        self.counts = QLabel("总计 0   新增 0   完成 0   跳过 0   失败 0   不支持 0")
        main.addWidget(self.counts)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)
        self.current = QLabel("当前：等待扫描")
        self.current.setObjectName("currentLabel")
        main.addWidget(self.current)

        bottom = QHBoxLayout()
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止")
        self.retry_button = QPushButton("重试失败项")
        self.open_button = QPushButton("打开输出文件夹")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button.clicked.connect(self.stop_processing)
        self.retry_button.clicked.connect(self.retry_failures)
        self.open_button.clicked.connect(self.open_output)
        for button in (self.pause_button, self.stop_button, self.retry_button):
            bottom.addWidget(button)
        bottom.addStretch(1)
        bottom.addWidget(self.open_button)
        main.addLayout(bottom)
        self._set_busy(False)

    def _path_row(self, edit: QLineEdit, directory: bool):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        button = QPushButton("选择")
        button.clicked.connect(lambda: self._choose_dir(edit) if directory else self._choose_file(edit))
        row.addWidget(button)
        return box

    def _choose_dir(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", edit.text())
        if path:
            edit.setText(path)

    def _choose_file(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", edit.text())
        if path:
            edit.setText(path)

    def _load_settings(self):
        self.source_edit.setText(self.settings.value("source", r"G:\Music\VipSongsDownload"))
        self.output_edit.setText(self.settings.value("output", r"G:\Music\Decoded"))
        self.lrc_check.setChecked(self.settings.value("copy_lrc", True, type=bool))
        self.structure_check.setChecked(self.settings.value("keep_structure", True, type=bool))
        self.name_check.setChecked(self.settings.value("keep_filename", True, type=bool))

    def _save_settings(self):
        self.settings.setValue("source", self.source_edit.text())
        self.settings.setValue("output", self.output_edit.text())
        self.settings.setValue("copy_lrc", self.lrc_check.isChecked())
        self.settings.setValue("keep_structure", self.structure_check.isChecked())
        self.settings.setValue("keep_filename", self.name_check.isChecked())

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.save_values()
            self._load_settings()
            if self.scan_result:
                self.start_scan()

    def _paths(self):
        source = Path(self.source_edit.text()).expanduser()
        output = Path(self.output_edit.text()).expanduser()
        ffprobe = self.settings.value("ffprobe", "") or find_ffprobe()
        qmdec = find_qmdec()
        return source, output, Path(ffprobe) if ffprobe else None, qmdec

    def start_scan(self):
        if self._running():
            return
        self._save_settings()
        source, output, ffprobe, _ = self._paths()
        if not source.is_dir():
            QMessageBox.warning(self, "找不到源目录", f"请选择有效的源文件夹：\n{source}")
            return
        source_resolved, output_resolved = source.resolve(), output.resolve()
        if output_resolved == source_resolved or source_resolved in output_resolved.parents:
            QMessageBox.critical(self, "输出目录不安全", "输出目录不能位于源目录内部，以确保源文件夹保持只读。")
            return
        if ffprobe is None or not ffprobe.is_file():
            QMessageBox.warning(self, "找不到 ffprobe", "请在设置中选择本机 ffprobe.exe。")
            return
        output.mkdir(parents=True, exist_ok=True)
        self.scan_button.setEnabled(False)
        self.current.setText("当前：正在递归扫描并校验已处理项目…")
        self.worker = ScanWorker(source, output, DB_PATH, str(ffprobe), self.lrc_check.isChecked(),
                                 self.structure_check.isChecked())
        self.worker.completed.connect(self._scan_complete)
        self.worker.failed.connect(self._scan_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _scan_complete(self, result: ScanResult):
        self.scan_result = result
        self.entries = result.entries
        self._populate_table()
        self._update_counts()
        self.current.setText(f"扫描完成；新增 LRC {result.lrc_copied} 个")
        self.progress.setValue(0)

    def _scan_failed(self, error: str):
        QMessageBox.critical(self, "扫描失败", error)
        self.current.setText("当前：扫描失败")

    def _worker_finished(self):
        self._set_busy(False)
        if self.close_after_task:
            QTimer.singleShot(0, self.close)
        elif self.rescan_after_process:
            self.rescan_after_process = False
            QTimer.singleShot(0, self.start_scan)

    def _populate_table(self):
        self.table.setRowCount(len(self.entries))
        self.row_by_rel.clear()
        for row, entry in enumerate(self.entries):
            self.row_by_rel[entry.relative] = row
            self._set_row(row, entry, entry.status)

    def _set_row(self, row: int, entry: FileEntry, status: str):
        values = [entry.filename, str(Path(entry.relative).parent) if str(Path(entry.relative).parent) != "." else "",
                  entry.extension, self._format_size(entry.size), STATUS_TEXT.get(status, status)]
        for col, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setBackground(QColor(STATUS_COLOR.get(status, "#ffffff")))
            if col == 0:
                cell.setToolTip(entry.error or entry.relative)
            self.table.setItem(row, col, cell)

    @staticmethod
    def _format_size(size: int) -> str:
        return f"{size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"

    def _update_counts(self):
        tally = {key: sum(e.status == key for e in self.entries) for key in STATUS_TEXT}
        supported = sum(e.status != "unsupported" for e in self.entries)
        self.counts.setText(f"总计 {supported}   新增 {tally['pending']}   完成 {tally['success']}   跳过 {tally['skipped']}   失败 {tally['failed']}   不支持 {tally['unsupported']}")
        self.retry_button.setEnabled(tally["failed"] > 0)
        self.start_button.setEnabled(tally["pending"] > 0 and not self._running())

    def start_processing(self):
        pending = [e for e in self.entries if e.status == "pending"]
        self._launch_process(pending)

    def retry_failures(self):
        failed = [e for e in self.entries if e.status == "failed"]
        self._launch_process(failed)

    def _launch_process(self, entries: list[FileEntry]):
        if not entries:
            return
        source, output, ffprobe, qmdec = self._paths()
        if not qmdec:
            QMessageBox.critical(self, "找不到 qmdec", "当前 Python 环境中没有找到已安装的 qmdec CLI。")
            return
        if ffprobe is None or not ffprobe.is_file():
            QMessageBox.critical(self, "找不到 ffprobe", "请在设置中选择本机 ffprobe.exe。")
            return
        output.mkdir(parents=True, exist_ok=True)
        self.progress.setRange(0, len(entries))
        self.progress.setValue(0)
        self.current.setText(f"当前：准备处理 {len(entries)} 个文件")
        self.worker = ProcessWorker(entries, source, output, DB_PATH, qmdec, str(ffprobe),
                                    self.structure_check.isChecked(), self.name_check.isChecked(), LOG_PATH)
        self.worker.file_started.connect(self._file_started)
        self.worker.file_finished.connect(self._file_finished)
        self.worker.completed.connect(self._process_complete)
        self.worker.finished.connect(self._worker_finished)
        self._set_busy(True)
        self.worker.start()

    def _file_started(self, rel: str, index: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(index - 1)
        self.current.setText(f"当前：{rel}  ({index}/{total})")
        row = self.row_by_rel.get(rel)
        if row is not None:
            self._set_row(row, self.entries[row], "processing")

    def _file_finished(self, rel: str, status: str, error: str):
        row = self.row_by_rel.get(rel)
        if row is not None:
            self.entries[row].status = status
            self.entries[row].error = error
            self._set_row(row, self.entries[row], status)
        self._update_counts()
        self.progress.setValue(self.progress.value() + 1)

    def _process_complete(self, stopped: bool):
        self.current.setText("当前：已停止（当前文件已完成）" if stopped else "当前：处理完成")
        if not stopped and self.settings.value("open_after", False, type=bool):
            self.open_output()
        self.rescan_after_process = True

    def toggle_pause(self):
        if not isinstance(self.worker, ProcessWorker):
            return
        if self.worker.pause_event.is_set():
            self.worker.pause()
            self.pause_button.setText("继续")
            self.current.setText("当前：已暂停，正在完成当前文件…")
        else:
            self.worker.resume()
            self.pause_button.setText("暂停")

    def stop_processing(self):
        if isinstance(self.worker, ProcessWorker):
            self.worker.stop()
            self.current.setText("当前：停止请求已发送，将在当前文件完成后停止")

    def open_output(self):
        _, output, _, _ = self._paths()
        output.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output)))

    def _running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_busy(self, busy: bool):
        self.scan_button.setEnabled(not busy)
        self.settings_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy and bool(self.scan_result and self.scan_result.new_count))
        self.pause_button.setEnabled(busy and isinstance(self.worker, ProcessWorker))
        self.stop_button.setEnabled(busy and isinstance(self.worker, ProcessWorker))
        if not busy:
            self.pause_button.setText("暂停")
            self._update_counts()

    def _style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#f6f8fb; color:#172033; font-family:'Segoe UI'; font-size:10pt; }
            QLabel#appTitle { font-size:22pt; font-weight:700; color:#14213d; }
            QLabel#subtitle { color:#64748b; }
            QLabel#currentLabel { color:#475569; }
            QLineEdit, QTableWidget { background:white; border:1px solid #d8e0eb; border-radius:7px; padding:6px; }
            QPushButton { background:white; border:1px solid #cbd5e1; border-radius:7px; padding:8px 14px; }
            QPushButton:hover { background:#eff6ff; border-color:#93c5fd; }
            QPushButton:disabled { color:#94a3b8; }
            QPushButton#primary { background:#2563eb; color:white; border:0; font-weight:600; }
            QPushButton#primary:hover { background:#1d4ed8; }
            QHeaderView::section { background:#edf2f7; border:0; border-bottom:1px solid #d8e0eb; padding:8px; font-weight:600; }
            QProgressBar { background:#e2e8f0; border:0; border-radius:6px; text-align:center; height:16px; }
            QProgressBar::chunk { background:#3b82f6; border-radius:6px; }
        """)

    def closeEvent(self, event):
        if self._running():
            answer = QMessageBox.question(
                self, "任务仍在运行", "当前任务尚未完成。\n\n等待当前文件完成后退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.close_after_task = True
                if isinstance(self.worker, ProcessWorker):
                    self.worker.stop()
                event.ignore()
            else:
                event.ignore()
            return
        self._save_settings()
        event.accept()
