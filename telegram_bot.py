"""
telegram_bot.py
Telegram-бот на aiogram v3. Команди (вимога ТЗ п.2, мінімум 3 — тут 6):
  /start        — привітання
  /newchat      — почати новий чат (очищення контексту користувача)
  /screenshot   — зробити скріншот екрана комп'ютера і надіслати
  /learn <text> — додати інструкцію для AI
  /open <app>   — відкрити програму на ПК
  /search <text>— знайти файли за іменем у домашній директорії
  /status       — CPU/RAM + статистика бота

Будь-яке інше текстове повідомлення передається в AI Core, відповідь
форматується в Markdown і надсилається користувачу.

Усі потенційно повільні синхронні виклики (Gemini API, обхід файлової
системи, скріншот) обгорнуті в asyncio.to_thread — інакше вони блокують
event loop бота цілком, і поки один користувач чекає на відповідь AI,
бот не реагує на повідомлення інших користувачів.

Бот запускається в окремому QThread (див. bot_thread.py) зі своїм власним
asyncio event loop, щоб GUI не блокувався мережевими викликами бота.
"""

import asyncio
import logging
import os
import platform
import subprocess
import time
from io import BytesIO
from pathlib import Path

import psutil
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

logger = logging.getLogger("telegram_bot")

# /search свідомо обмежений домашньою директорією, а не всім диском —
# інакше перший же виклик на реальній машині зависне на хвилини.
SEARCH_ROOT = Path.home()
SEARCH_MAX_RESULTS = 15
START_TIME = time.time()


def _search_files(query: str) -> list[str]:
    """Синхронна (потенційно повільна) частина /search — виконується в
    окремому потоці через asyncio.to_thread."""
    results = []
    for root, dirs, files in os.walk(SEARCH_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # без прихованих/системних тек
        for name in files:
            if query in name.lower():
                results.append(str(Path(root) / name))
                if len(results) >= SEARCH_MAX_RESULTS:
                    return results
    return results


def _take_screenshot_png() -> bytes:
    """Синхронна частина /screenshot — виконується через asyncio.to_thread."""
    from PIL import ImageGrab

    img = ImageGrab.grab()
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_dispatcher(ai_core, history_manager, log_cb, stats: dict) -> Dispatcher:
    """log_cb(str) — callback для показу подій у GUI (у main_gui це
    TelegramBotThread.log_signal.emit). stats — спільний dict лічильників
    (messages_total, commands_total) для /status."""

    dp = Dispatcher()

    def _log(action: str, message: Message, is_command: bool = True):
        line = f"[Telegram] {message.from_user.id} ({message.from_user.username}): {action}"
        logger.info(line)
        log_cb(line)
        if is_command:
            stats["commands_total"] = stats.get("commands_total", 0) + 1

    def _chat_id_for(telegram_user_id: int) -> str:
        chat_id = f"tg_{telegram_user_id}"
        history_manager.ensure_chat(chat_id)
        return chat_id

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        _log("/start", message)
        await message.answer(
            "Привіт! Я твій AI-помічник.\n"
            "Команди: /newchat /screenshot /learn /open /search /status\n"
            "Або просто напиши повідомлення — відповість AI."
        )

    @dp.message(Command("newchat"))
    async def cmd_newchat(message: Message):
        chat_id = _chat_id_for(message.from_user.id)
        history_manager.clear_chat(chat_id)
        _log("/newchat", message)
        await message.answer("✅ Новий чат почато. Історію попереднього діалогу очищено.")

    @dp.message(Command("screenshot"))
    async def cmd_screenshot(message: Message):
        _log("/screenshot", message)
        try:
            png_bytes = await asyncio.to_thread(_take_screenshot_png)
            photo = BufferedInputFile(png_bytes, filename="screenshot.png")
            await message.answer_photo(photo, caption="Скріншот екрана")
        except Exception as e:
            logger.exception("Помилка /screenshot")
            await message.answer(
                f"⚠️ Не вдалося зробити скріншот: {e}\n"
                "(На Linux без графічного середовища скріншот неможливий.)"
            )

    @dp.message(Command("learn"))
    async def cmd_learn(message: Message, command: CommandObject):
        instruction = (command.args or "").strip()
        if not instruction:
            await message.answer("Використання: /learn <інструкція для AI>")
            return
        ai_core.add_learned_instruction(instruction)
        _log(f"/learn {instruction}", message)
        await message.answer("✅ Інструкцію додано до системного промпту AI.")

    @dp.message(Command("open"))
    async def cmd_open(message: Message, command: CommandObject):
        app = (command.args or "").strip()
        if not app:
            await message.answer("Використання: /open <назва програми>")
            return
        _log(f"/open {app}", message)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(app)  # noqa: S606
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", app])
            else:
                subprocess.Popen([app])
            await message.answer(f"✅ Спроба відкрити: {app}")
        except Exception as e:
            await message.answer(f"⚠️ Не вдалося відкрити '{app}': {e}")

    @dp.message(Command("search"))
    async def cmd_search(message: Message, command: CommandObject):
        query = (command.args or "").strip().lower()
        if not query:
            await message.answer("Використання: /search <текст у назві файлу>")
            return
        _log(f"/search {query}", message)
        results = await asyncio.to_thread(_search_files, query)
        if results:
            await message.answer("Знайдено:\n" + "\n".join(results))
        else:
            await message.answer("Нічого не знайдено.")

    @dp.message(Command("status"))
    async def cmd_status(message: Message):
        _log("/status", message)
        uptime = int(time.time() - START_TIME)
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory().percent
        text = (
            f"*Статус бота*\n"
            f"Аптайм: {uptime // 60} хв {uptime % 60} с\n"
            f"CPU: {cpu}%\n"
            f"RAM: {ram}%\n"
            f"Повідомлень оброблено: {stats.get('messages_total', 0)}\n"
            f"Команд виконано: {stats.get('commands_total', 0)}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)

    @dp.message(F.text)
    async def handle_text(message: Message):
        """Будь-яке звичайне повідомлення (не команда) — запит до AI."""
        chat_id = _chat_id_for(message.from_user.id)
        _log(f"AI query: {message.text[:80]}", message, is_command=False)
        stats["messages_total"] = stats.get("messages_total", 0) + 1

        context = history_manager.get_ai_context(chat_id)
        history_manager.add_message(chat_id, "user", message.text)

        await message.bot.send_chat_action(message.chat.id, "typing")
        # to_thread — без цього виклик Gemini (кілька секунд) заблокував би
        # весь event loop бота, і інші користувачі не отримали б відповіді.
        reply = await asyncio.to_thread(ai_core.generate_response, context, message.text)

        history_manager.add_message(chat_id, "ai", reply)
        try:
            await message.answer(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Telegram відхиляє Markdown, якщо AI згенерував "биті" спецсимволи —
            # у такому разі шлемо як звичайний текст, аби користувач не лишився без відповіді.
            await message.answer(reply)

    return dp


async def run_bot(token: str, dispatcher: Dispatcher):
    bot = Bot(token=token)
    await dispatcher.start_polling(bot)
