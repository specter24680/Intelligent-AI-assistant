"""
bot_thread.py
Запускає Telegram-бота (aiogram, asyncio) в окремому QThread, щоб GUI
(Qt event loop) ніколи не блокувався мережевими викликами бота чи AI
(вимога ТЗ п.6). Зв'язок з GUI — виключно через pyqtSignal: Qt сам робить
його thread-safe, коли відправник і отримувач живуть у різних потоках.
"""

import asyncio
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from telegram_bot import create_dispatcher, run_bot

logger = logging.getLogger("bot_thread")


class TelegramBotThread(QThread):
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, token: str, ai_core, history_manager, parent=None):
        super().__init__(parent)
        self.token = token
        self.ai_core = ai_core
        self.history_manager = history_manager
        self.stats = {"messages_total": 0, "commands_total": 0}
        self._loop = None
        self._dp = None

    def run(self):
        if not self.token:
            self.error_signal.emit("TELEGRAM_BOT_TOKEN не задано в .env")
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._dp = create_dispatcher(
            self.ai_core, self.history_manager, self.log_signal.emit, self.stats
        )
        try:
            self._loop.run_until_complete(run_bot(self.token, self._dp))
        except Exception as e:
            logger.exception("Бот аварійно завершився")
            self.error_signal.emit(str(e))
        finally:
            self._loop.close()

    def stop(self):
        """Викликається з GUI-потоку. Диспетчер живе в потоці бота, тому
        зупинку планують через run_coroutine_threadsafe, а не викликають
        напряму (await у чужому потоці неможливий)."""
        if self._loop and self._dp and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._dp.stop_polling(), self._loop)
