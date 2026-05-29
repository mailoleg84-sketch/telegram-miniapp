"""Бот сводится к одному действию — открыть Mini App."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import APP_VERSION, WEBAPP_URL
from webapp.auth import make_fallback_auth_params
from webapp.openai_service import openai_config_status, test_openai_connection

router = Router()


def _webapp_url(user=None) -> str:
    parts = urlsplit(WEBAPP_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v"] = APP_VERSION
    if user:
        query.update(make_fallback_auth_params(user.id, user.first_name or ""))
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment,
    ))


def _webapp_reply_kb(user=None):
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(
        text="📱 Открыть приложение",
        web_app=WebAppInfo(url=_webapp_url(user)),
    ))
    return builder.as_markup(resize_keyboard=True)


def _webapp_inline_kb(user=None):
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Открыть приложение", web_app=WebAppInfo(url=_webapp_url(user)))
    return builder.as_markup()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я бот для изучения английского языка.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение 👇",
        reply_markup=_webapp_reply_kb(message.from_user),
    )
    await message.answer(
        "Или открой прямо отсюда:",
        reply_markup=_webapp_inline_kb(message.from_user),
    )


@router.message(Command("app"))
async def app_handler(message: Message) -> None:
    await message.answer("Открой приложение:", reply_markup=_webapp_inline_kb(message.from_user))


@router.message(Command("version"))
async def version_handler(message: Message) -> None:
    await message.answer(
        "Версия Mini App:\n"
        f"{APP_VERSION}\n\n"
        "URL кнопки:\n"
        f"{_webapp_url(message.from_user)}"
    )


@router.message(Command("diag"))
async def diag_handler(message: Message) -> None:
    openai = openai_config_status()
    await message.answer(
        "Диагностика:\n"
        f"APP_VERSION: {APP_VERSION}\n"
        f"WEBAPP_URL: {_webapp_url(message.from_user)}\n"
        f"OPENAI configured: {openai['configured']}\n"
        f"OPENAI key length: {openai['length']}\n"
        f"OPENAI key prefix: {openai['prefix']}\n"
        f"OPENAI model: {openai['model']}\n"
        f"OPENAI TTS model: {openai['tts_model']}\n"
        f"OPENAI voice TTS voice: {openai['voice_tts_voice']}\n"
        f"OPENAI realtime model: {openai['realtime_model']}\n"
        f"OPENAI realtime voice: {openai['realtime_voice']}\n"
        f"OPENAI realtime transcribe: {openai['realtime_transcribe_model']}\n"
        f"OPENAI voice reasoning: {openai['voice_reasoning_effort']}\n"
        f"OPENAI voice max tokens: {openai['voice_max_tokens']}\n"
        f"OPENAI prompt configured: {openai['prompt_id_configured']}\n"
        f"OPENAI prompt version: {openai['prompt_version'] or 'latest'}\n"
        f"OPENAI prompt for voice: {openai['prompt_for_voice']}"
    )


@router.message(Command("openai_test"))
async def openai_test_handler(message: Message) -> None:
    result = await test_openai_connection()
    if result["ok"]:
        await message.answer(
            "OpenAI test: OK\n"
            f"Model setting: {result['model']}\n"
            "Sample models:\n"
            + "\n".join(result["sample_models"])
        )
        return
    await message.answer(
        "OpenAI test: FAILED\n"
        f"Model setting: {result['model']}\n"
        f"Error: {result['error']}"
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "ℹ️ Всё происходит в приложении: регистрация, слова, тренировки, "
        "разговор с ИИ-репетитором и баллы.\n\n"
        "Команды: /start, /app, /help",
    )
