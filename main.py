from __future__ import annotations

import os
import sys
from pathlib import Path

# PySide6's wheel places the Shiboken runtime in a sibling directory; Windows
# needs that directory registered before loading Qt extension modules.
_dll_directory_handles = []
_loaded_qt_libraries = []
if getattr(sys, "frozen", False) and hasattr(os, "add_dll_directory"):
    import ctypes
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for dll_dir in (bundle / "shiboken6", bundle / "PySide6"):
        if dll_dir.is_dir():
            _dll_directory_handles.append(os.add_dll_directory(str(dll_dir)))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    for library in (bundle / "shiboken6" / "shiboken6.abi3.dll",
                    bundle / "PySide6" / "pyside6.abi3.dll",
                    bundle / "PySide6" / "Qt6Core.dll",
                    bundle / "PySide6" / "Qt6Gui.dll",
                    bundle / "PySide6" / "Qt6Widgets.dll"):
        if library.is_file():
            _loaded_qt_libraries.append(ctypes.WinDLL(str(library), winmode=0x00001100))

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    if "--smoke-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName("QQmusicX")
    app.setOrganizationName("QQmusicX")
    window = MainWindow()
    if "--smoke-test" in sys.argv:
        print("QQmusicX UI initialized")
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
