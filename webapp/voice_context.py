"""Контекст промптов чата/голоса и состояние голосового урока (вынесено из
webapp/server.py, шаг 3e-2).

Сборщики prompt_context для текстового чата, гибридного голосового хода и
Realtime-сессии + персистентное состояние голосового урока (lesson_state).

Зависимости направлены только «вниз» (config-данных нет, database, formatters,
lesson_engine) — модуль НЕ импортирует server.py, циклов нет. server.py
реэкспортирует имена: импорты и патчи в тестах работают как раньше.
"""
import random

import database
from webapp.formatters import (
    _age_label,
    _goal_label,
    _level_for_user,
    _normalized_age_group_for_user,
)
from webapp.lesson_engine import (
    advance_lesson_state,
    create_lesson_state,
    lesson_prompt_context,
)


def _style_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    if age_group in {"5_7", "8_10"}:
        return "игровой, очень доброжелательный, с простыми фразами и мини-играми"
    if age_group == "14_18":
        return "спокойный, дружелюбный, с диалогами и реальными ситуациями"
    return "дружелюбный, короткими репликами, с понятными примерами"


def _topics_for_user(user) -> str:
    goal = user["goal"] if user else ""
    age_group = user["age_group"] if user else ""
    if goal == "travel":
        return "путешествия, аэропорт, кафе, покупки, знакомство, карта города"
    if goal == "exams":
        return "школа, хобби, планы, короткие диалоги, экзаменационные темы без стресса"
    if goal == "speaking":
        return "игры, друзья, спорт, музыка, фильмы, хобби, повседневные диалоги"
    if age_group in {"5_7", "8_10"}:
        return "животные, цвета, еда, игрушки, игры, школа, сказочные истории"
    return "школа, игры, спорт, путешествия, хобби, истории, повседневные ситуации"


def _prompt_context_for_user(user) -> dict:
    return {
        "age": str(user["child_age"] or _age_label(user["age_group"])) if user else "не указан",
        "age_group": _normalized_age_group_for_user(user),
        "level": _level_for_user(user),
        "goal": _goal_label(user["goal"]) if user else "устная практика",
        "style": _style_for_user(user),
        "topics": _topics_for_user(user),
    }


def _voice_topic_bank(user) -> list[str]:
    age_group = user["age_group"] if user else ""
    goal = user["goal"] if user else ""
    if goal == "travel":
        return [
            "airport adventure", "hotel check-in", "cafe order", "city map",
            "souvenir shop", "beach day", "train station", "lost backpack",
            "photo walk", "weather talk", "ice cream kiosk", "museum quest",
            "passport helper", "bus stop", "theme park", "family trip",
            "restaurant mistake", "ask for directions",
        ]
    if goal == "exams":
        return [
            "school day", "favorite hobby", "weekend plans", "short interview",
            "picture description", "study routine", "sports club", "my room",
            "healthy food", "future job", "friendship", "small presentation",
            "compare two pictures", "tell a mini story", "opinion practice",
            "exam calm-down", "daily routine challenge", "question cards",
        ]
    if age_group in {"5_7", "8_10"}:
        return [
            "magic shop", "space picnic", "robot friend", "treasure map",
            "funny cafe", "toy store", "school bag", "secret door",
            "superhero training", "rainbow colors", "little chef", "sports day",
            "pet doctor", "birthday party", "snowy park", "music game",
            "dragon library", "pirate bakery", "dino museum", "jungle camera",
            "monster picnic", "art studio", "weather machine", "lost teddy",
            "train of words", "moon playground", "detective game", "tiny theater",
        ]
    if age_group == "11_13":
        return [
            "school project", "gaming club", "sports practice", "music playlist",
            "movie scene", "travel vlog", "cafe dialogue", "new classmate",
            "weekend plan", "pet story", "shopping challenge", "mystery quest",
            "YouTube plan", "comic book idea", "science fair", "escape room",
            "football commentary", "birthday planning", "school club pitch",
            "phone call practice",
        ]
    return [
        "real conversation", "travel problem", "school debate", "job interview mini",
        "movie discussion", "music and hobbies", "daily routine", "exam warm-up",
        "ordering food", "city directions", "online safety", "future plans",
        "small talk practice", "opinion challenge", "presentation opener",
        "friendly disagreement", "study abroad scene", "interview with a blogger",
    ]


def _choose_voice_topics(user, messages: list[dict], count: int = 3) -> list[str]:
    bank = _voice_topic_bank(user)
    recent_text = " ".join(m["content"] for m in messages[-10:]).lower()
    fresh = [topic for topic in bank if topic.lower() not in recent_text]
    if len(fresh) < count:
        fresh = bank[:]
    random.shuffle(fresh)
    return fresh[:count]


def _voice_lesson_focus(messages: list[dict]) -> str:
    recent = [
        " ".join(str(message.get("content") or "").split())
        for message in messages[-6:]
        if str(message.get("content") or "").strip()
    ]
    if not recent:
        return "урок только начинается"
    return (
        "Текущая линия урока — последние реплики: "
        + " | ".join(recent[-4:])
        + ". Продолжай эту тему и мини-сцену, пока ребенок сам не попросит сменить тему."
    )


_REVIEW_PHASES = {"welcome", "choose_topic", "mini_lesson"}


def _format_review_hint(rows, phase: str) -> str:
    """Компактная подсказка из прошлых уроков: что уже освоено (вернуть спирально)
    и что давалось труднее (мягко навестить). Пусто, если данных нет или урок уже
    в разгаре — подсказка нужна только в начале нового урока."""
    if phase not in _REVIEW_PHASES or not rows:
        return ""
    mastered: list[str] = []
    hard: list[str] = []
    for row in rows:
        phrase = str(row.get("target_phrase") or "").strip()
        label = str(row.get("topic_label") or "").strip()
        hits = int(row.get("target_hits") or 0)
        corrections = int(row.get("correction_count") or 0)
        if phrase and hits >= 2 and phrase not in mastered:
            mastered.append(phrase)
        if label and corrections >= 1 and hits < 2 and label not in hard:
            hard.append(label)
    parts: list[str] = []
    if mastered:
        parts.append("ранее ребёнок уверенно говорил: " + "; ".join(f'"{item}"' for item in mastered[:3]))
    if hard:
        parts.append("труднее давалась тема «" + hard[0] + "» — при случае мягко верни её")
    return ". ".join(parts)


async def _voice_review_focus(user_id: int, lesson_state: dict | None) -> str:
    phase = str((lesson_state or {}).get("phase") or "welcome")
    if phase not in _REVIEW_PHASES:
        return ""
    current_topic = str((lesson_state or {}).get("current_topic") or "")
    try:
        rows = await database.get_recent_completed_voice_lessons(
            user_id, limit=3, exclude_topic=current_topic
        )
    except Exception:
        return ""
    return _format_review_hint(rows, phase)


def _voice_prompt_context(user, messages: list[dict], lesson_state: dict | None = None) -> dict:
    topics = _choose_voice_topics(user, messages)
    lesson_focus = _voice_lesson_focus(messages)
    has_history = any(str(message.get("content") or "").strip() for message in messages)
    recent_user_messages = [m["content"] for m in messages if m["role"] == "user"][-3:]
    recent_assistant_messages = [m["content"] for m in messages if m["role"] == "assistant"][-3:]
    context = {
        "lesson_focus": lesson_focus,
        "topic_suggestions": (
            "не меняй текущую тему; запасные темы только если ребенок явно просит сменить тему: "
            + ", ".join(topics)
            if has_history else ", ".join(topics)
        ),
        "avoid_topics": (
            "Не меняй тему по таймеру и не начинай новый урок сам. "
            "Продолжай текущую линию урока 8-10 реплик или до явной просьбы ребенка сменить тему. "
            "Не перечисляй новые темы, если ребенок уже находится в мини-сцене."
        ),
        "recent_user_messages": " | ".join(recent_user_messages) or "пока нет",
        "recent_assistant_messages": " | ".join(recent_assistant_messages) or "пока нет",
        "activity_menu": (
            "роль: продавец/покупатель, мини-квест, угадай слово, естественный вопрос, "
            "выбор из двух вариантов, вопрос про день ребенка, короткая смешная сценка, "
            "мини-история на 2 реплики, возвращение к слову из прошлой реплики"
        ),
        "lesson_loop": (
            "Сначала живо отреагируй на смысл реплики ребенка. Затем обязательно добавь маленькую учебную пользу: "
            "одну английскую фразу вроде I want..., I like..., Can I have...?, одно слово, мягкое исправление "
            "или выбор из двух вариантов. Не требуй повторения каждый раз; иногда задай естественный вопрос "
            "или продолжи сцену. Держи одну тему урока, пока ребенок сам не сменит ее. Через несколько реплик верни одно старое слово."
        ),
        "conversation_plan": (
            "1) Сначала понять настоящий запрос ребенка: вопрос, просьба, выбор темы, усталость или ошибка. "
            "2) Ответить по сути на этот запрос, не игнорировать его ради плана урока. "
            "3) Всегда связать ответ с короткой учебной пользой: фразой, словом, исправлением, выбором или мини-практикой. "
            "4) Продолжить текущую мини-сцену 8-10 ходов, если ребенок не просит сменить тему. "
            "5) Каждые 3-4 реплики можно менять активность внутри той же темы: мини-диалог, угадай слово, роль, вопрос, исправление. "
            "6) Если ребенок отвечает коротко, упростить и дать выбор из двух вариантов. "
            "7) Если ребенок спрашивает по-русски, ответить по-русски и дать одну маленькую английскую фразу."
        ),
    }
    if lesson_state:
        context.update(lesson_prompt_context(lesson_state))
    context["review_focus"] = str((lesson_state or {}).get("review_focus") or "")
    return context


def _realtime_prompt_context(user, history: list[dict], lesson_state: dict | None = None) -> dict:
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context["age_group"] = _normalized_age_group_for_user(user) if user else "8_10"
    prompt_context.update(_voice_prompt_context(user, history, lesson_state))
    return prompt_context


async def _ensure_voice_lesson_state(user_id: int, user) -> dict:
    row = await database.get_voice_lesson_state(user_id)
    age_group = _normalized_age_group_for_user(user)
    if row and row["age_group"] == age_group:
        state = dict(row)
    else:
        state = create_lesson_state(
            age_group=age_group,
            goal=user["goal"] if user else "",
            seed=str(user_id),
        )
        await database.save_voice_lesson_state(user_id, state)
    state["review_focus"] = await _voice_review_focus(user_id, state)
    return state


async def _advance_voice_lesson_state(user_id: int, user, role: str, text: str) -> dict:
    state = await _ensure_voice_lesson_state(user_id, user)
    previous_phase = state.get("phase")
    state = advance_lesson_state(state, role, text)
    await database.save_voice_lesson_state(user_id, state)
    if previous_phase != "wrapup" and state.get("phase") == "wrapup":
        await database.save_completed_voice_lesson(user_id, state)
    return state
