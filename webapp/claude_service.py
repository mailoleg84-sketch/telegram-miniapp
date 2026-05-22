"""Обёртка над Anthropic API: ИИ-репетитор английского."""
import logging

from anthropic import AsyncAnthropic

from config import (
    ANTHROPIC_API_KEY,
    CHAT_MAX_TOKENS,
    CLAUDE_MODEL,
)

log = logging.getLogger(__name__)

# Клиент создаётся один раз. Если ключа нет — оставляем None и отдаём понятную ошибку.
_client: AsyncAnthropic | None = None
if ANTHROPIC_API_KEY:
    _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
else:
    log.warning("ANTHROPIC_API_KEY не задан — режим репетитора работать не будет.")


# Системный промпт задаёт характер репетитора. Меняй текст под себя.
SYSTEM_PROMPT = """Ты — дружелюбный и терпеливый репетитор английского языка для русскоязычного ученика по имени {name}.

Правила общения:
- Веди живой разговор на английском, чтобы ученик практиковался.
- Подстраивай сложность под уровень ученика: если он пишет просто — отвечай простыми словами и короткими фразами; если уверенно — усложняй.
- Если ученик допустил заметную ошибку (грамматика, слово, порядок слов) — мягко поправь: покажи правильный вариант и в одну короткую строку объясни по-русски, почему так. Не придирайся к мелочам и не прерывай поток ради каждой запятой.
- Держи свои ответы короткими (2–5 предложений) — это удобно читать с телефона.
- Будь тёплым и ободряющим, хвали за прогресс.
- Если ученик пишет по-русски — мягко предложи попробовать сказать это по-английски и помоги.
- В конце реплики иногда задавай простой вопрос, чтобы поддержать разговор.

Отвечай обычным текстом, без markdown-разметки и без списков."""


async def chat_reply(history: list[dict], user_name: str) -> str:
    """
    history: список сообщений вида [{"role": "user"/"assistant", "content": "..."}].
    Возвращает текст ответа репетитора.
    """
    if _client is None:
        return ("⚠️ Репетитор пока не настроен: не задан ключ ANTHROPIC_API_KEY. "
                "Добавь его в переменные окружения на Render.")

    try:
        response = await _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CHAT_MAX_TOKENS,
            system=SYSTEM_PROMPT.format(name=user_name or "друг"),
            messages=history,
        )
        # Собираем текст из блоков ответа
        parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(parts).strip() or "…"
    except Exception as e:
        log.exception("Ошибка обращения к Claude")
        return f"⚠️ Не удалось получить ответ от репетитора: {e}"
