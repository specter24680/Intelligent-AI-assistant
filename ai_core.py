"""
ai_core.py
Обгортка над Gemini API через пакет google-genai — офіційний уніфікований
SDK. Старий пакет google-generativeai (import google.generativeai as genai,
genai.GenerativeModel(...)) остаточно знятий з підтримки 30.11.2025 —
НЕ використовувати, приклади з застарілих туторіалів працювати не будуть.

Тримає системну інструкцію (задається в GUI) + список "вивчених" інструкцій,
доданих через /learn у Telegram — вони підклеюються до системного промпту,
а не до кожного окремого повідомлення.
"""

import json
import logging

from google import genai
from google.genai import types

from config import DATA_DIR

logger = logging.getLogger("ai_core")

LEARNED_PATH = DATA_DIR / "learned_instructions.json"
DEFAULT_MODEL = "gemini-2.5-flash"


class AICore:
    def __init__(self, api_key: str, model_name: str, temperature: float,
                 max_tokens: int, system_instruction: str):
        self.model_name = model_name or DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_instruction = system_instruction
        self.learned: list[str] = self._load_learned()

        self.client = genai.Client(api_key=api_key) if api_key else None
        if not self.client:
            logger.warning("GEMINI_API_KEY не задано — AI-відповіді працювати не будуть.")

    # --- налаштування (викликається з GUI при збереженні панелі налаштувань) ---
    def update_settings(self, temperature=None, max_tokens=None, system_instruction=None):
        if temperature is not None:
            self.temperature = temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if system_instruction is not None:
            self.system_instruction = system_instruction

    # --- /learn ---
    def _load_learned(self) -> list[str]:
        if LEARNED_PATH.exists():
            try:
                with open(LEARNED_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def add_learned_instruction(self, instruction: str):
        self.learned.append(instruction)
        with open(LEARNED_PATH, "w", encoding="utf-8") as f:
            json.dump(self.learned, f, ensure_ascii=False, indent=2)
        logger.info("Додано нову інструкцію через /learn: %s", instruction)

    def _full_system_instruction(self) -> str:
        if not self.learned:
            return self.system_instruction
        extra = "\n".join(f"- {ins}" for ins in self.learned)
        return f"{self.system_instruction}\n\nДодаткові вивчені інструкції:\n{extra}"

    @staticmethod
    def _to_genai_history(history: list[dict]) -> list["types.Content"]:
        """Наш внутрішній формат [{'role': 'user'/'model', 'parts': ['текст']}]
        (див. chat_history.get_ai_context) -> список types.Content для SDK."""
        result = []
        for item in history:
            text = item["parts"][0] if item.get("parts") else ""
            result.append(
                types.Content(role=item["role"], parts=[types.Part.from_text(text=text)])
            )
        return result

    # --- генерація відповіді ---
    def generate_response(self, history: list[dict], user_message: str) -> str:
        """Синхронний (блокуючий, мережевий) виклик. У GUI обгортається в
        AIWorker(QThread), у Telegram-боті — в asyncio.to_thread(), щоб не
        блокувати відповідно GUI-потік і event loop бота (вимога ТЗ п.6)."""
        if not self.client:
            return "⚠️ GEMINI_API_KEY не налаштовано. Додайте ключ у файл .env і перезапустіть застосунок."
        try:
            chat = self.client.chats.create(
                model=self.model_name,
                history=self._to_genai_history(history),
                config=types.GenerateContentConfig(
                    system_instruction=self._full_system_instruction(),
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                ),
            )
            response = chat.send_message(user_message)
            return response.text or "(порожня відповідь від моделі)"
        except Exception as e:
            logger.exception("Помилка виклику Gemini API")
            return f"⚠️ Помилка AI: {e}"
