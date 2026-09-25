# 更新记录 / Changelog

## 0.1.0 — 2026-09-25

### 中文

- 首个 Windows x64 图形界面版本。
- 支持递归扫描，并保留子目录和原音频 basename。
- 使用 SQLite 增量记录、输出校验、LRC 原样复制和安全跳过。
- 本地调用 `qmdec` 与 `ffprobe`；Windows 下隐藏子进程命令行窗口。
- 提供便携 ZIP 和用户级安装程序。

### English

- First Windows x64 GUI release.
- Recursive scanning preserves subdirectories and original audio basenames.
- SQLite incremental state, output validation, byte-for-byte LRC copying, and safe skipping.
- Invokes local `qmdec` and `ffprobe`; hides subprocess console windows on Windows.
- Includes portable ZIP and per-user installer distributions.
