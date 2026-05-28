"""Бот сводится к одному действию — открыть Mini App."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import APP_VERSION, WEBAPP_URL

router = Router()


def _webapp_url() -> str:
    parts = urlsplit(WEBAPP_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v"] = APP_VERSION
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(query),
        parts.fragment,
    ))


def _webapp_reply_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(
        text="📱 Открыть приложение",
        web_app=WebAppInfo(url=_webapp_url()),
    ))
    return builder.as_markup(resize_keyboard=True)


def _webapp_inline_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Открыть приложение", web_app=WebAppInfo(url=_webapp_url()))
    return builder.as_markup()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я бот для изучения английского языка.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение 👇",
        reply_markup=_webapp_reply_kb(),
    )
    await message.answer(
        "Или открой прямо отсюда:",
        reply_markup=_webapp_inline_kb(),
    )


@router.message(Command("app"))
async def app_handler(message: Message) -> None:
    await message.answer("Открой приложение:", reply_markup=_webapp_inline_kb())


@router.message(Command("version"))
async def version_handler(message: Message) -> None:
    await message.answer(
        "Версия Mini App:\n"
        f"{APP_VERSION}\n\n"
        "URL кнопки:\n"
        f"{_webapp_url()}"
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "ℹ️ Всё происходит в приложении: регистрация, слова, тренировки, "
        "разговор с ИИ-репетитором и баллы.\n\n"
        "Команды: /start, /app, /help",
    )
