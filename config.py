"""
config.py
Управління налаштуваннями застосунку: параметри AI (температура, макс. токени,
системні інструкції) та шляхи до файлів. Секрети (API-ключі) читаються з .env,
а не з config.json, щоб їх не можна було випадково закомітити в git.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # читає .env у корені проєкту

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "history.json"
LOG_PATH = LOGS_DIR / "app.log"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# --- Секрети (з .env, ніколи не зберігаються в config.json) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ВАЖЛИВО щодо моделі: температура/max_output_tokens підтримуються Gemini
# включно до 3.5 Flash. Починаючи з Gemini 3.6 Flash Google прибрав ці
# параметри з generation_config (модель сама вирішує "рівень міркування").
# ТЗ прямо вимагає регулятор температури в GUI, тому за замовчуванням
# використовується стабільна gemini-2.5-flash, яка ще підтримує ці параметри.
# Якщо зміните model_name на gemini-3.6-flash/3.7-flash — температура
# з панелі налаштувань просто ігноруватиметься API.
DEFAULT_SETTINGS = {
    "temperature": 0.7,
    "max_tokens": 1024,
    "system_instruction": (
        "Ти — особистий AI-помічник користувача. Відповідай стисло, по суті, "
        "форматуй відповіді в Markdown (списки, код, таблиці), коли це доречно."
    ),
    "model_name": "gemini-2.5-flash",
    "gui_history_limit": 50,
}


class Settings:
    """Обгортка над config.json з автозбереженням при кожній зміні."""

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # доповнюємо відсутні ключі дефолтами (напр. після оновлення проєкту)
                return {**DEFAULT_SETTINGS, **data}
            except (json.JSONDecodeError, OSError):
                pass
        return dict(DEFAULT_SETTINGS)

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, **kwargs):
        self._data.update(kwargs)
        self.save()

    @property
    def all(self) -> dict:
        return dict(self._data)
