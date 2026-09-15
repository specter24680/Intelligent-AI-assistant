"""
chat_history.py
Зберігання історії чатів у JSON (формат прямо зі ТЗ):
{
  "chat_1": [{"role": "user", "message": "...", "ts": "..."}, ...],
  "chat_2": [...]
}
Ключі "chat_N" — чати, створені в GUI кнопкою New Chat.
Ключі "tg_<user_id>" — по одному на кожного Telegram-користувача.

Один менеджер використовується і GUI, і Telegram-ботом одночасно (різні
потоки), тому доступ до self._data захищений threading.Lock.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from config import HISTORY_PATH


class ChatHistoryManager:
    def __init__(self, path: Path = HISTORY_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def list_chats(self) -> list[str]:
        with self._lock:
            return sorted(self._data.keys())

    def create_new_chat(self) -> str:
        """Створює новий чат chat_N і повертає його id. Попередні чати нікуди
        не зникають — вони залишаються в history.json і доступні через
        випадаючий список у GUI."""
        with self._lock:
            existing = [
                int(c.split("_")[1]) for c in self._data if c.startswith("chat_")
            ]
            chat_id = f"chat_{max(existing, default=0) + 1}"
            self._data[chat_id] = []
            self._save()
            return chat_id

    def ensure_chat(self, chat_id: str):
        with self._lock:
            if chat_id not in self._data:
                self._data[chat_id] = []
                self._save()

    def clear_chat(self, chat_id: str):
        """Очищає контекст конкретного чату, не видаляючи сам чат."""
        with self._lock:
            self._data[chat_id] = []
            self._save()

    def add_message(self, chat_id: str, role: str, message: str):
        """role: 'user' або 'ai'."""
        with self._lock:
            self._data.setdefault(chat_id, [])
            self._data[chat_id].append(
                {
                    "role": role,
                    "message": message,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                }
            )
            self._save()

    def get_history(self, chat_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._data.get(chat_id, []))[-limit:]

    def get_ai_context(self, chat_id: str, limit: int = 20) -> list[dict]:
        """Формат для Gemini: role 'user'/'model', parts: ['текст']."""
        history = self.get_history(chat_id, limit)
        return [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["message"]]}
            for m in history
        ]
