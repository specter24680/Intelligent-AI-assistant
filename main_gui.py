"""
main_gui.py
Точка входу застосунку. PyQt6 GUI:
  - вікно чату з AI (Markdown-рендеринг відповідей)
  - лог останніх дій у реальному часі
  - панель налаштувань AI (температура, макс. токени, системні інструкції)
  - Start/Stop Bot, New Chat

Запуск: python main_gui.py
"""

import logging
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QSplitter, QTabWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from ai_core import AICore
from bot_thread import TelegramBotThread
from chat_history import ChatHistoryManager
from config import GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, Settings
from logger_setup import CallbackLogHandler, setup_logging

logger = logging.getLogger("gui")


class AIWorker(QThread):
    """Викликає ai_core.generate_response в окремому потоці — інакше GUI
    "зависає" на весь час мережевого запиту до Gemini (вимога ТЗ п.6)."""

    finished_signal = pyqtSignal(str)

    def __init__(self, ai_core: AICore, history: list[dict], user_message: str):
        super().__init__()
        self.ai_core = ai_core
        self.history = history
        self.user_message = user_message

    def run(self):
        reply = self.ai_core.generate_response(self.history, self.user_message)
        self.finished_signal.emit(reply)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Інтелектуальний AI-помічник")
        self.resize(1000, 650)

        self.settings = Settings()
        self.history_manager = ChatHistoryManager()
        self.ai_core = AICore(
            api_key=GEMINI_API_KEY,
            model_name=self.settings.get("model_name"),
            temperature=self.settings.get("temperature"),
            max_tokens=self.settings.get("max_tokens"),
            system_instruction=self.settings.get("system_instruction"),
        )

        self.bot_thread: TelegramBotThread | None = None
        self.ai_worker: AIWorker | None = None

        chats = self._gui_chat_ids()
        self.current_chat_id = chats[0] if chats else self.history_manager.create_new_chat()

        self._build_ui()
        self._connect_logging()
        self._load_current_chat_into_view()

    # ---------- допоміжне ----------
    def _gui_chat_ids(self) -> list[str]:
        """Тільки чати, створені в GUI (chat_N) — чати Telegram-користувачів
        (tg_<id>) у випадаючому списку GUI не показуємо."""
        ids = [c for c in self.history_manager.list_chats() if c.startswith("chat_")]
        return sorted(ids, key=lambda c: int(c.split("_")[1]))

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        # --- ліва панель: чат ---
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)

        top_bar = QHBoxLayout()
        self.chat_selector = QComboBox()
        self.chat_selector.addItems(self._gui_chat_ids())
        self.chat_selector.setCurrentText(self.current_chat_id)
        self.chat_selector.currentTextChanged.connect(self._on_chat_switch)
        top_bar.addWidget(QLabel("Чат:"))
        top_bar.addWidget(self.chat_selector)

        self.new_chat_btn = QPushButton("New Chat")
        self.new_chat_btn.clicked.connect(self._on_new_chat)
        top_bar.addWidget(self.new_chat_btn)

        self.bot_toggle_btn = QPushButton("Start Bot")
        self.bot_toggle_btn.clicked.connect(self._on_toggle_bot)
        top_bar.addWidget(self.bot_toggle_btn)
        top_bar.addStretch()
        chat_layout.addLayout(top_bar)

        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        chat_layout.addWidget(self.chat_display, stretch=1)

        input_bar = QHBoxLayout()
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Повідомлення для AI...")
        self.input_line.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        input_bar.addWidget(self.input_line, stretch=1)
        input_bar.addWidget(self.send_btn)
        chat_layout.addLayout(input_bar)

        splitter.addWidget(chat_widget)

        # --- права панель: налаштування + логи ---
        tabs = QTabWidget()
        tabs.addTab(self._build_settings_tab(), "Налаштування")
        tabs.addTab(self._build_logs_tab(), "Логи")
        splitter.addWidget(tabs)
        splitter.setSizes([650, 350])

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Температура (0.0 - 2.0):"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(self.settings.get("temperature"))
        layout.addWidget(self.temp_spin)

        layout.addWidget(QLabel("Максимальна кількість токенів:"))
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(64, 8192)
        self.tokens_spin.setSingleStep(64)
        self.tokens_spin.setValue(self.settings.get("max_tokens"))
        layout.addWidget(self.tokens_spin)

        layout.addWidget(QLabel("Системні інструкції для AI:"))
        self.sys_instr_edit = QTextEdit()
        self.sys_instr_edit.setPlainText(self.settings.get("system_instruction"))
        layout.addWidget(self.sys_instr_edit, stretch=1)

        save_btn = QPushButton("Зберегти налаштування")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        return w

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)  # тримаємо GUI легким при довгій роботі
        layout.addWidget(self.log_view)
        return w

    def _connect_logging(self):
        """Підключає всі логи (кореневий логер) до вкладки Логи в реальному часі."""
        handler = CallbackLogHandler(self._append_log_line)
        logging.getLogger().addHandler(handler)

    def _append_log_line(self, line: str):
        # Викликається з будь-якого потоку через pyqtSignal.emit у
        # CallbackLogHandler / TelegramBotThread.log_signal — оновлення
        # QPlainTextEdit тут безпечне.
        self.log_view.appendPlainText(line)

    # ---------- чат ----------
    def _load_current_chat_into_view(self):
        limit = self.settings.get("gui_history_limit", 50)
        history = self.history_manager.get_history(self.current_chat_id, limit)
        md_lines = []
        for m in history:
            prefix = "**Ви:**" if m["role"] == "user" else "**AI:**"
            md_lines.append(f"{prefix} {m['message']}")
        self.chat_display.setMarkdown("\n\n".join(md_lines))

    def _on_chat_switch(self, chat_id: str):
        if not chat_id:
            return
        self.current_chat_id = chat_id
        self._load_current_chat_into_view()

    def _on_new_chat(self):
        new_id = self.history_manager.create_new_chat()
        self.chat_selector.addItem(new_id)
        self.chat_selector.setCurrentText(new_id)  # тригерить _on_chat_switch -> очищує поле
        logger.info("Створено новий чат: %s", new_id)

    def _on_send(self):
        text = self.input_line.text().strip()
        if not text:
            return
        self.input_line.clear()
        self.input_line.setEnabled(False)
        self.send_btn.setEnabled(False)

        context = self.history_manager.get_ai_context(self.current_chat_id)
        self.history_manager.add_message(self.current_chat_id, "user", text)
        self._load_current_chat_into_view()

        self.ai_worker = AIWorker(self.ai_core, context, text)
        self.ai_worker.finished_signal.connect(self._on_ai_reply)
        self.ai_worker.start()

    def _on_ai_reply(self, reply: str):
        self.history_manager.add_message(self.current_chat_id, "ai", reply)
        self._load_current_chat_into_view()
        self.input_line.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input_line.setFocus()
        logger.info("AI відповів у %s (%d символів)", self.current_chat_id, len(reply))

    # ---------- налаштування ----------
    def _on_save_settings(self):
        temperature = self.temp_spin.value()
        max_tokens = self.tokens_spin.value()
        system_instruction = self.sys_instr_edit.toPlainText()

        self.settings.update(
            temperature=temperature,
            max_tokens=max_tokens,
            system_instruction=system_instruction,
        )
        # той самий об'єкт ai_core використовує і бот (якщо запущений) —
        # тому зміни одразу діють і в GUI, і в Telegram без перезапуску
        self.ai_core.update_settings(temperature, max_tokens, system_instruction)
        logger.info("Налаштування AI збережено (temp=%.1f, tokens=%d)", temperature, max_tokens)
        QMessageBox.information(self, "Готово", "Налаштування збережено.")

    # ---------- бот ----------
    def _on_toggle_bot(self):
        if self.bot_thread and self.bot_thread.isRunning():
            self.bot_thread.stop()
            self.bot_thread.wait(3000)
            self.bot_toggle_btn.setText("Start Bot")
            logger.info("Telegram-бот зупинено")
        else:
            if not TELEGRAM_BOT_TOKEN:
                QMessageBox.warning(
                    self, "Помилка",
                    "TELEGRAM_BOT_TOKEN не задано. Додайте його у файл .env і перезапустіть застосунок.",
                )
                return
            self.bot_thread = TelegramBotThread(TELEGRAM_BOT_TOKEN, self.ai_core, self.history_manager)
            self.bot_thread.log_signal.connect(self._append_log_line)
            self.bot_thread.error_signal.connect(self._on_bot_error)
            self.bot_thread.start()
            self.bot_toggle_btn.setText("Stop Bot")
            logger.info("Telegram-бот запущено")

    def _on_bot_error(self, msg: str):
        self.bot_toggle_btn.setText("Start Bot")
        QMessageBox.critical(self, "Помилка бота", msg)

    def closeEvent(self, event):
        if self.bot_thread and self.bot_thread.isRunning():
            self.bot_thread.stop()
            self.bot_thread.wait(3000)
        event.accept()


def main():
    setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
