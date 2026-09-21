import asyncio
import logging
import os
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import AuthKeyError, SessionPasswordNeededError

load_dotenv()

# === Конфигурация ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SESSION_NAME = "telegram_account"
SESSION_FILE = Path(f"{SESSION_NAME}.session")

if not all([BOT_TOKEN, API_ID, API_HASH, OWNER_ID]):
    raise SystemExit("Ошибка: заполните BOT_TOKEN, API_ID, API_HASH и OWNER_ID в .env")

# === Логирование ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("session_bot")

# === Клиент Telethon ===
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

router = Router()

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статус")],
        [
            KeyboardButton(text="🚪 Выйти из сессии"),
            KeyboardButton(text="ℹ️ Помощь"),
        ],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def is_owner(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == OWNER_ID)


# === Команды и кнопки ===

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_owner(message):
        return

    await message.answer(
        "<b>Панель управления</b>\n\n"
        "Выбери действие на клавиатуре ниже.",
        reply_markup=main_menu,
        parse_mode="HTML",
    )


@router.message(Command("status"))
@router.message(F.text == "📊 Статус")
async def cmd_status(message: Message):
    if not is_owner(message):
        return

    try:
        if not client.is_connected():
            await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            name = me.first_name or ""
            username = f"@{me.username}" if me.username else "без username"
            await message.answer(
                f"✅ <b>Авторизован</b>\n"
                f"• ID: <code>{me.id}</code>\n"
                f"• Имя: {name}\n"
                f"• Username: {username}",
                parse_mode="HTML",
            )
        else:
            await message.answer("❌ Telegram-аккаунт не авторизован.")
    except Exception as e:
        logger.exception("Ошибка при проверке статуса")
        await message.answer(f"❌ Ошибка проверки статуса: <code>{e}</code>", parse_mode="HTML")


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    if not is_owner(message):
        return

    await message.answer(
        "<b>Доступные действия</b>\n\n"
        "📊 <b>Статус</b> — проверить авторизацию Telegram-аккаунта.\n"
        "🚪 <b>Выйти из сессии</b> — завершить текущую сессию и удалить локальный файл.\n\n"
        "Также можно отправить файл <code>.session</code> — бот попытается выйти из этой сессии.",
        parse_mode="HTML",
    )


@router.message(Command("logout"))
@router.message(F.text == "🚪 Выйти из сессии")
async def cmd_logout(message: Message):
    if not is_owner(message):
        return

    try:
        if not client.is_connected():
            await client.connect()

        if not await client.is_user_authorized():
            await message.answer("ℹ️ Аккаунт уже не авторизован.")
            # Всё равно пытаемся удалить файл сессии
            if SESSION_FILE.exists():
                SESSION_FILE.unlink(missing_ok=True)
            return

        await client.log_out()
        logger.info("Локальная сессия успешно завершена")

        if SESSION_FILE.exists():
            SESSION_FILE.unlink(missing_ok=True)

        await message.answer("✅ Telegram-аккаунт вышел из текущей сессии. Локальный файл удалён.")
    except Exception as e:
        logger.exception("Ошибка при выходе из сессии")
        await message.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")


@router.message(F.document)
async def handle_session_file(message: Message):
    if not is_owner(message):
        return

    document = message.document
    filename = (document.file_name or "").lower()

    if not filename.endswith(".session"):
        await message.answer("❌ Отправь файл с расширением <code>.session</code>.", parse_mode="HTML")
        return

    temp_path: Path | None = None
    uploaded_client: TelegramClient | None = None

    try:
        # Создаём временный файл
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tmp:
            temp_path = Path(tmp.name)

        await message.bot.download(document, destination=temp_path)
        logger.info("Загружен session-файл: %s → %s", filename, temp_path)

        uploaded_client = TelegramClient(str(temp_path.with_suffix("")), API_ID, API_HASH)
        await uploaded_client.connect()

        if not await uploaded_client.is_user_authorized():
            await message.answer("❌ Эта сессия недействительна или уже завершена.")
            return

        await uploaded_client.log_out()
        logger.info("Успешно вышли из загруженной сессии")
        await message.answer("✅ Из отправленной .session успешно вышел. Временный файл удалён.")

    except AuthKeyError:
        await message.answer("❌ Сессия повреждена или ключ авторизации недействителен.")
    except SessionPasswordNeededError:
        await message.answer("❌ Сессия требует пароль двухфакторной аутентификации.")
    except Exception as e:
        logger.exception("Ошибка обработки session-файла")
        await message.answer(f"❌ Не удалось обработать сессию: <code>{e}</code>", parse_mode="HTML")
    finally:
        if uploaded_client and uploaded_client.is_connected():
            await uploaded_client.disconnect()
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        # Telethon также может создавать .session-journal — удаляем и его
        if temp_path:
            journal = temp_path.with_suffix(".session-journal")
            if journal.exists():
                journal.unlink(missing_ok=True)


# === Запуск ===

async def on_startup():
    """Пытаемся подключиться к существующей сессии при старте."""
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            logger.info("Telethon-клиент авторизован как %s (id=%s)", me.username or me.first_name, me.id)
        else:
            logger.info("Telethon-клиент запущен, но не авторизован")
    except Exception:
        logger.exception("Не удалось подключить Telethon-клиент при старте")


async def on_shutdown():
    if client.is_connected():
        await client.disconnect()
        logger.info("Telethon-клиент отключён")


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Бот запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
