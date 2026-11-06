import logging
import sys
from logging.handlers import RotatingFileHandler

from swifttr.config import config_dir


def _setup_logging() -> None:
    handler = RotatingFileHandler(config_dir() / "app.log", maxBytes=300_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def hook(exc_type, exc, tb):
        logging.getLogger("crash").error("uncaught", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook


def main() -> int:
    _setup_logging()
    from PySide6.QtCore import QDir, QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Swift Translate Win")

    lock = QLockFile(QDir.temp().absoluteFilePath("swifttranslatewin.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Swift Translate Win", "Already running (look for the tray icon).")
        return 0

    from swifttr.controller import Controller
    from swifttr.ui_bubble import make_icon

    app.setWindowIcon(make_icon())
    ctrl = Controller(app)
    ctrl.start()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
