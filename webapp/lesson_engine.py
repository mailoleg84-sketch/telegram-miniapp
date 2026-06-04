"""Deterministic lesson-state engine shared by text, hybrid voice, and Realtime."""
from __future__ import annotations

import hashlib
import re
from typing import Any


PHASE_LABELS = {
    "welcome": "Начало урока",
    "choose_topic": "Выбираем тему",
    "mini_lesson": "Новые слова и фраза",
    "dialogue": "Разговорная практика",
    "challenge": "Мини-задание",
    "wrapup": "Итог урока",
}

PHASE_PROGRESS = {
    "welcome": 5,
    "choose_topic": 15,
    "mini_lesson": 35,
    "dialogue": 65,
    "challenge": 85,
    "wrapup": 100,
}


def _topic(
    topic_id: str,
    label: str,
    goal: str,
    phrase: str,
    words: list[str],
    aliases: list[str],
) -> dict[str, Any]:
    return {
        "id": topic_id,
        "label": label,
        "goal": goal,
        "phrase": phrase,
        "words": words,
        "aliases": aliases,
    }


TOPIC_PLANS = {
    "5_7": [
        _topic("animals", "Животные", "назвать любимое животное", "I like cats.", ["cat", "dog", "rabbit"], ["animals", "animal", "животные", "животное", "животных", "кошка", "собака"]),
        _topic("colors", "Цвета", "назвать цвет предмета", "It is blue.", ["red", "blue", "green"], ["colors", "colour", "цвета", "цвет"]),
        _topic("toys", "Игрушки", "рассказать о любимой игрушке", "This is my toy.", ["ball", "doll", "car"], ["toys", "toy", "игрушки", "игрушка"]),
        _topic("family", "Семья", "назвать членов семьи", "This is my family.", ["mum", "dad", "sister"], ["family", "семья", "мама", "папа"]),
        _topic("food", "Еда", "сказать, что нравится из еды", "I like apples.", ["apple", "banana", "pizza"], ["food", "еда", "еду", "яблоко", "пицца"]),
        _topic("cartoons", "Мультфильмы", "описать любимого героя", "My hero is funny.", ["hero", "funny", "strong"], ["cartoons", "cartoon", "мультфильм", "герой"]),
        _topic("my_room", "Моя комната", "назвать предметы в комнате", "I have a bed.", ["bed", "lamp", "chair"], ["room", "my room", "комната"]),
        _topic("pets", "Питомцы", "коротко рассказать о питомце", "My pet is small.", ["pet", "small", "cute"], ["pets", "pet", "питомец", "питомцы"]),
        _topic("clothes", "Одежда", "назвать одежду и цвет", "My shirt is red.", ["shirt", "hat", "shoes"], ["clothes", "одежда", "шапка", "обувь"]),
        _topic("weather", "Погода", "сказать о погоде", "It is sunny.", ["sunny", "rainy", "cold"], ["weather", "погода", "дождь", "солнце"]),
    ],
    "8_10": [
        _topic("school", "Школа", "рассказать об одном школьном предмете", "My favorite subject is English.", ["subject", "lesson", "break"], ["school", "школа", "школу", "урок"]),
        _topic("friends", "Друзья", "описать друга доброй фразой", "My friend is funny.", ["friend", "kind", "funny"], ["friends", "friend", "друзья", "друг"]),
        _topic("games", "Игры", "рассказать о любимой игре", "I like this game because it is fun.", ["game", "level", "team"], ["games", "game", "игры", "игра"]),
        _topic("sports", "Спорт", "сказать, каким спортом нравится заниматься", "I like playing football.", ["sport", "team", "score"], ["sports", "sport", "спорт", "футбол"]),
        _topic("animals", "Животные", "описать любимое животное", "My favorite animal is a dolphin.", ["wild", "fast", "friendly"], ["animals", "animal", "животные", "животное", "животных", "кошка", "собака"]),
        _topic("superheroes", "Супергерои", "описать способность героя", "My hero can fly.", ["hero", "power", "brave"], ["superheroes", "superhero", "супергерой", "герой"]),
        _topic("holidays", "Каникулы", "рассказать об идеальном дне каникул", "On holiday, I want to swim.", ["holiday", "trip", "beach"], ["holidays", "holiday", "каникулы", "отпуск"]),
        _topic("food", "Любимая еда", "заказать любимую еду", "Can I have a pizza, please?", ["menu", "pizza", "juice"], ["food", "еда", "еду", "пицца", "кафе"]),
        _topic("daily_routine", "Мой день", "описать часть своего дня", "I get up at seven.", ["morning", "school", "evening"], ["routine", "daily routine", "мой день", "распорядок"]),
        _topic("dream_house", "Дом мечты", "описать одну комнату мечты", "My dream house has a game room.", ["house", "room", "garden"], ["dream house", "house", "дом мечты", "дом"]),
    ],
    "11_13": [
        _topic("hobbies", "Хобби", "объяснить, почему нравится хобби", "I enjoy drawing because it helps me relax.", ["hobby", "enjoy", "practice"], ["hobbies", "hobby", "хобби"]),
        _topic("video_games", "Видеоигры", "описать игру и дать мнение", "I like this game because the story is exciting.", ["character", "level", "story"], ["video games", "gaming", "games", "видеоигры", "игры"]),
        _topic("youtube", "YouTube", "описать интересный формат видео", "I usually watch videos about science.", ["channel", "video", "creator"], ["youtube", "ютуб", "видео"]),
        _topic("music", "Музыка", "рассказать о любимой музыке", "This song makes me feel happy.", ["song", "band", "playlist"], ["music", "музыка", "песня"]),
        _topic("movies", "Фильмы", "кратко порекомендовать фильм", "I recommend this film because it is funny.", ["film", "scene", "character"], ["movies", "movie", "films", "фильмы", "кино"]),
        _topic("sport", "Спорт", "обсудить тренировку или матч", "Our team played well today.", ["training", "match", "team"], ["sport", "sports", "спорт"]),
        _topic("travel", "Путешествия", "описать желаемую поездку", "I would like to visit London.", ["trip", "ticket", "hotel"], ["travel", "trip", "путешествия", "поездка"]),
        _topic("technology", "Технологии", "объяснить пользу устройства", "I use this app to learn new things.", ["app", "device", "useful"], ["technology", "tech", "технологии"]),
        _topic("school_life", "Школьная жизнь", "рассказать о школьном событии", "We are working on a school project.", ["project", "classmate", "club"], ["school life", "school", "школа"]),
        _topic("funny_stories", "Смешные истории", "рассказать короткую историю в прошлом", "Yesterday, something funny happened.", ["yesterday", "happened", "laughed"], ["funny stories", "story", "смешная история", "история"]),
    ],
    "14_18": [
        _topic("future_career", "Будущая профессия", "объяснить выбор профессии", "I would like to work as a designer.", ["career", "skill", "experience"], ["future career", "career", "профессия", "карьера"]),
        _topic("travel", "Путешествия", "уверенно решить ситуацию в поездке", "Could you tell me how to get to the station?", ["luggage", "booking", "directions"], ["travel", "trip", "путешествия", "поездка"]),
        _topic("music", "Музыка", "аргументировать музыкальное мнение", "What I like most about this artist is the lyrics.", ["lyrics", "artist", "concert"], ["music", "музыка"]),
        _topic("films_series", "Фильмы и сериалы", "обсудить сюжет без пересказа", "The series is worth watching because the characters feel real.", ["plot", "episode", "character"], ["films", "series", "movies", "фильмы", "сериалы"]),
        _topic("technology", "Технологии", "обсудить пользу и риски технологии", "Technology is useful when we use it thoughtfully.", ["privacy", "device", "feature"], ["technology", "tech", "технологии"]),
        _topic("social_media", "Социальные сети", "выразить взвешенное мнение", "Social media can be useful, but it can also be distracting.", ["content", "privacy", "audience"], ["social media", "соцсети", "социальные сети"]),
        _topic("exams", "Экзамены", "дать развернутый экзаменационный ответ", "One effective way to prepare is to practice regularly.", ["prepare", "focus", "result"], ["exams", "exam", "экзамены", "экзамен"]),
        _topic("business", "Бизнес", "предложить простую бизнес-идею", "My idea solves a simple everyday problem.", ["customer", "idea", "value"], ["business", "бизнес"]),
        _topic("real_life_english", "Английский для жизни", "поддержать естественный small talk", "How has your week been so far?", ["actually", "probably", "sounds good"], ["real life english", "small talk", "английский для жизни", "разговор"]),
        _topic("interviews", "Собеседования", "уверенно ответить на вопрос о себе", "One of my strengths is that I learn quickly.", ["strength", "experience", "improve"], ["interviews", "interview", "собеседование", "интервью"]),
    ],
}


CHANGE_TOPIC_MARKERS = (
    "change topic",
    "another topic",
    "different topic",
    "другая тема",
    "другую тему",
    "сменить тему",
    "сменим тему",
    "поменяй тему",
    "поменяем тему",
    "давай другое",
    "что-нибудь другое",
)
CONFUSED_MARKERS = (
    "не понимаю",
    "не понял",
    "не поняла",
    "не знаю",
    "помоги",
    "объясни проще",
    "what",
    "i don't understand",
    "i do not understand",
)
TIRED_MARKERS = ("устал", "устала", "скучно", "надоело", "tired", "boring")
AUTO_CHOOSE_MARKERS = ("выбери сам", "выбери сама", "любая", "любую", "неважно", "you choose", "any topic")
COMMON_ERROR_PATTERNS = (
    r"\bi like (?:dog|cat|game|apple)\b",
    r"\bi goed\b",
    r"\bi has\b",
    r"\bi am agree\b",
    r"\bhe have\b",
    r"\bshe have\b",
)


def normalize_age_group(age_group: str | None) -> str:
    value = str(age_group or "").strip()
    if value in TOPIC_PLANS:
        return value
    if value in {"under_12", "under12", "under_10", "default", ""}:
        return "8_10"
    return "8_10"


def _normalized_text(text: str) -> str:
    value = re.sub(r"[^\w\s'-]+", " ", str(text or "").lower(), flags=re.UNICODE)
    return " ".join(value.split())


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _language_of(text: str) -> str:
    has_ru = bool(re.search(r"[А-Яа-яЁё]", text))
    has_en = bool(re.search(r"[A-Za-z]", text))
    if has_ru and has_en:
        return "mixed"
    if has_ru:
        return "russian"
    if has_en:
        return "english"
    return "unknown"


def _topic_lookup(age_group: str) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in TOPIC_PLANS[normalize_age_group(age_group)]}


def _topic_for_state(state: dict[str, Any]) -> dict[str, Any] | None:
    return _topic_lookup(state.get("age_group", "8_10")).get(str(state.get("current_topic") or ""))


def _select_topic(state: dict[str, Any], topic_id: str) -> dict[str, Any]:
    plan = _topic_lookup(state["age_group"]).get(topic_id)
    if not plan:
        return state
    state.update({
        "phase": "mini_lesson",
        "current_topic": plan["id"],
        "current_topic_label": plan["label"],
        "lesson_goal": plan["goal"],
        "target_phrase": plan["phrase"],
        "target_words": list(plan["words"]),
        "turn_count": 0,
        "support_mode": "",
    })
    return state


def _detect_topic(state: dict[str, Any], text: str) -> str:
    words = f" {_normalized_text(text)} "
    for topic_id in state.get("topic_suggestions") or []:
        plan = _topic_lookup(state["age_group"]).get(topic_id)
        if not plan:
            continue
        for alias in [plan["id"], plan["label"], *plan["aliases"]]:
            normalized_alias = _normalized_text(alias)
            if normalized_alias and f" {normalized_alias} " in words:
                return plan["id"]
    for plan in TOPIC_PLANS[state["age_group"]]:
        for alias in [plan["id"], plan["label"], *plan["aliases"]]:
            normalized_alias = _normalized_text(alias)
            if normalized_alias and f" {normalized_alias} " in words:
                return plan["id"]
    return ""


def _suggestion_ids(age_group: str, goal: str, seed: str, count: int = 3) -> list[str]:
    plans = list(TOPIC_PLANS[normalize_age_group(age_group)])
    goal_text = _normalized_text(goal)
    preferred = [
        plan
        for plan in plans
        if goal_text and (plan["id"] in goal_text or goal_text in _normalized_text(plan["goal"]))
    ]
    remaining = [plan for plan in plans if plan not in preferred]
    ranked = sorted(
        remaining,
        key=lambda plan: hashlib.sha256(f"{seed}:{age_group}:{goal}:{plan['id']}".encode("utf-8")).hexdigest(),
    )
    return [plan["id"] for plan in (preferred + ranked)[:count]]


def create_lesson_state(age_group: str, goal: str = "", seed: str = "") -> dict[str, Any]:
    normalized_age_group = normalize_age_group(age_group)
    return {
        "age_group": normalized_age_group,
        "phase": "welcome",
        "current_topic": "",
        "current_topic_label": "",
        "topic_suggestions": _suggestion_ids(normalized_age_group, goal, seed),
        "lesson_goal": "",
        "target_phrase": "",
        "target_words": [],
        "turn_count": 0,
        "correction_count": 0,
        "last_language": "unknown",
        "support_mode": "",
    }


def advance_lesson_state(state: dict[str, Any], role: str, text: str) -> dict[str, Any]:
    updated = dict(state)
    updated["topic_suggestions"] = list(state.get("topic_suggestions") or [])
    updated["target_words"] = list(state.get("target_words") or [])
    updated["age_group"] = normalize_age_group(updated.get("age_group"))
    updated["phase"] = updated.get("phase") if updated.get("phase") in PHASE_LABELS else "welcome"
    clean = _normalized_text(text)

    if role == "user":
        updated["last_language"] = _language_of(text)
        updated["support_mode"] = ""
        if _contains_marker(clean, CHANGE_TOPIC_MARKERS):
            requested_topic = _detect_topic(updated, clean)
            if requested_topic:
                return _select_topic(updated, requested_topic)
            updated.update({
                "phase": "choose_topic",
                "current_topic": "",
                "current_topic_label": "",
                "lesson_goal": "",
                "target_phrase": "",
                "target_words": [],
                "turn_count": 0,
                "support_mode": "change_topic",
            })
            return updated

        if not updated.get("current_topic"):
            topic_id = _detect_topic(updated, clean)
            if topic_id:
                return _select_topic(updated, topic_id)
        else:
            mentioned_topic = _detect_topic(updated, clean)
            if mentioned_topic and mentioned_topic != updated.get("current_topic"):
                updated["support_mode"] = "bridge"

        if not updated.get("current_topic") and _contains_marker(clean, AUTO_CHOOSE_MARKERS):
            suggestions = updated.get("topic_suggestions") or []
            if suggestions:
                return _select_topic(updated, suggestions[0])

        if _contains_marker(clean, CONFUSED_MARKERS):
            updated["support_mode"] = "confused"
        elif _contains_marker(clean, TIRED_MARKERS):
            updated["support_mode"] = "tired"

        if any(re.search(pattern, clean) for pattern in COMMON_ERROR_PATTERNS):
            updated["correction_count"] = int(updated.get("correction_count") or 0) + 1
            if not updated["support_mode"]:
                updated["support_mode"] = "correction"
        if updated["phase"] == "welcome":
            updated["phase"] = "choose_topic"
        return updated

    if role != "assistant":
        return updated

    if not updated.get("current_topic"):
        updated["phase"] = "choose_topic"
        return updated

    updated["turn_count"] = int(updated.get("turn_count") or 0) + 1
    turns = updated["turn_count"]
    if turns <= 2:
        updated["phase"] = "mini_lesson"
    elif turns <= 7:
        updated["phase"] = "dialogue"
    elif turns <= 9:
        updated["phase"] = "challenge"
    else:
        updated["phase"] = "wrapup"
    return updated


def lesson_prompt_context(state: dict[str, Any] | None) -> dict[str, str]:
    if not state:
        return {}
    phase = str(state.get("phase") or "welcome")
    plan = _topic_for_state(state)
    suggestion_labels = [
        _topic_lookup(state.get("age_group", "8_10"))[topic_id]["label"]
        for topic_id in state.get("topic_suggestions") or []
        if topic_id in _topic_lookup(state.get("age_group", "8_10"))
    ]
    topic_label = str(state.get("current_topic_label") or (plan or {}).get("label") or "")
    phrase = str(state.get("target_phrase") or (plan or {}).get("phrase") or "")
    words = list(state.get("target_words") or (plan or {}).get("words") or [])
    goal = str(state.get("lesson_goal") or (plan or {}).get("goal") or "")
    support_mode = str(state.get("support_mode") or "")

    if not topic_label:
        instruction = (
            "Урок еще не выбрал тему. Тепло отреагируй на ребенка и предложи ровно три темы: "
            + ", ".join(suggestion_labels)
            + ". Задай один короткий вопрос и дождись выбора."
        )
    elif phase == "mini_lesson":
        instruction = (
            f"Оставайся в теме «{topic_label}». Дай только один маленький учебный шаг: "
            f"одно слово из {', '.join(words)} или фразу «{phrase}», затем одну легкую практику."
        )
    elif phase == "dialogue":
        instruction = (
            f"Продолжай живой диалог строго в теме «{topic_label}» и веди к цели «{goal}». "
            f"Используй фразу «{phrase}» естественно, исправляй максимум одну важную ошибку."
        )
    elif phase == "challenge":
        instruction = (
            f"Дай одно короткое итоговое задание по теме «{topic_label}» с фразой «{phrase}». "
            "Не начинай новую тему и не задавай несколько вопросов."
        )
    else:
        instruction = (
            f"Коротко заверши тему «{topic_label}»: назови один успех, одну мягкую точку роста "
            "и предложи продолжить позже. Не начинай новый урок самостоятельно."
        )
    if support_mode == "confused":
        instruction += " Ребенок запутался: сначала объясни по-русски проще и дай выбор из двух вариантов."
    elif support_mode == "tired":
        instruction += " Ребенок устал: сохрани тему, но замени следующий шаг на очень легкую игру или закончи урок."
    elif support_mode == "correction":
        instruction += " Исправь только одну главную ошибку мягко: похвали попытку, дай естественный вариант и одну легкую практику."
    elif support_mode == "bridge":
        instruction += (
            " Ребенок упомянул другую тему. Не переключай урок и не говори, что возвращаешь его к теме. "
            "Естественно свяжи его мысль с текущей темой через один живой вопрос."
        )

    avatar_state = "idle"
    if state.get("phase") == "wrapup":
        avatar_state = "praising"
    elif state.get("support_mode") == "correction":
        avatar_state = "correcting"
    elif state.get("support_mode") in {"confused", "tired", "bridge"}:
        avatar_state = "encouraging"
    return {
        "lesson_phase": phase,
        "lesson_phase_label": PHASE_LABELS.get(phase, PHASE_LABELS["welcome"]),
        "lesson_progress": str(PHASE_PROGRESS.get(phase, 5)),
        "current_topic": topic_label or "тема еще не выбрана",
        "lesson_goal": goal or "выбрать подходящую тему и начать короткий урок",
        "target_phrase": phrase or "пока не выбрана",
        "target_words": ", ".join(words) or "пока не выбраны",
        "topic_suggestions": ", ".join(suggestion_labels),
        "support_mode": support_mode or "обычный темп",
        "avatar_state": avatar_state,
        "lesson_state_instruction": instruction,
        "lesson_focus": instruction,
    }


def public_lesson_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    context = lesson_prompt_context(state)
    return {
        "phase": state.get("phase") or "welcome",
        "phase_label": context.get("lesson_phase_label") or PHASE_LABELS["welcome"],
        "progress_percent": int(context.get("lesson_progress") or 5),
        "current_topic": state.get("current_topic") or "",
        "topic_label": "" if not state.get("current_topic") else context.get("current_topic", ""),
        "lesson_goal": context.get("lesson_goal", ""),
        "target_phrase": "" if not state.get("current_topic") else context.get("target_phrase", ""),
        "topic_suggestions": [
            _topic_lookup(state.get("age_group", "8_10"))[topic_id]["label"]
            for topic_id in state.get("topic_suggestions") or []
            if topic_id in _topic_lookup(state.get("age_group", "8_10"))
        ],
        "support_mode": state.get("support_mode") or "",
        "avatar_state": context.get("avatar_state") or "idle",
    }
