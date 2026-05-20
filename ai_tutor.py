import os
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """
Ты — строгий, но дружелюбный репетитор английского языка.

Твоя задача:
- исправлять ошибки пользователя
- объяснять грамматику простым языком
- всегда показывать правильный вариант
- давать короткое объяснение
- в конце давать мини-задание

Формат ответа:

❌ Ошибка
✔ Правильно
📘 Объяснение
✏️ Задание
"""

def ask_ai(user_text: str):
    response = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=600,
        temperature=0.7,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": user_text
            }
        ]
    )

    return response.content[0].text
