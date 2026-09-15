"""
logger_setup.py
Централізоване логування: всі дії (GUI, Telegram-бот, AI-запити) пишуться
у файл logs/app.log з часом, рівнем і повідомленням (вимога ТЗ п.5).
GUI підключається через CallbackLogHandler, щоб показувати ті самі логи
в реальному часі у вкладці "Логи".
"""

import logging
from logging.handlers import RotatingFileHandler

from config import LOG_PATH

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level=logging.INFO) -> logging.Logger:
    """Налаштовує кореневий логер: файл (з ротацією) + консоль.
    Викликати один раз при старті застосунку."""
    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    return root


class CallbackLogHandler(logging.Handler):
    """
    Хендлер, що передає кожен відформатований лог-рядок у зовнішній callback.
    У GUI callback = pyqtSignal.emit — Qt сам гарантує безпечну передачу між
    потоками (потік бота -> потік GUI), тому додаткові локи тут не потрібні.
    """

    def __init__(self, callback, level=logging.INFO):
        super().__init__(level)
        self._callback = callback
        self.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    def emit(self, record):
        try:
            self._callback(self.format(record))
        except Exception:
            self.handleError(record)
