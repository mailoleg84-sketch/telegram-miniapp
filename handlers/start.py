"""Бот сводится к одному действию — открыть Mini App."""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    KeyboardButton,
    Message,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import WEBAPP_URL

router = Router()


def _webapp_reply_kb():
    """Reply-кнопка под полем ввода — открывает Mini App."""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(
        text="📱 Открыть приложение",
        web_app=WebAppInfo(url=WEBAPP_URL),
    ))
    return builder.as_markup(resize_keyboard=True)


def _webapp_inline_kb():
    """Inline-кнопка прямо в сообщении."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📱 Открыть приложение",
        web_app=WebAppInfo(url=WEBAPP_URL),
    )
    return builder.as_markup()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я бот для изучения английских слов.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение 👇",
        reply_markup=_webapp_reply_kb(),
    )
    await message.answer(
        "Или открой прямо отсюда:",
        reply_markup=_webapp_inline_kb(),
    )


@router.message(Command("app"))
async def app_handler(message: Message) -> None:
    await message.answer(
        "Открой приложение:",
        reply_markup=_webapp_inline_kb(),
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>Как пользоваться</b>\n\n"
        "Всё происходит в приложении — там регистрация, обучение, тренировки и баллы.\n\n"
        "Команды:\n"
        "/start — приветствие и кнопка приложения\n"
        "/app — снова показать кнопку\n"
        "/help — эта справка",
    )
