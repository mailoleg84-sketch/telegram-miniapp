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


# _topic + TOPIC_PLANS вынесены в data/topic_plans.py (чистые данные).
from data.topic_plans import TOPIC_PLANS  # re-export для lesson_engine/тестов


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


def detect_common_error(text: str) -> str:
    """Возвращает фрагмент реплики с типичной ошибкой (для адресной отработки)
    или пустую строку. Те же паттерны, что и support_mode=correction."""
    clean = _normalized_text(text)
    for pattern in COMMON_ERROR_PATTERNS:
        match = re.search(pattern, clean)
        if match:
            return match.group(0)
    return ""


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
        "target_hits": 0,
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
        "target_hits": 0,
        "last_language": "unknown",
        "support_mode": "",
    }


def _used_target(state: dict[str, Any], clean_text: str) -> bool:
    """True, если ребёнок реально произнёс целевую фразу или целевое слово —
    сигнал усвоения, по которому фаза урока движется вперёд (а не только по числу ходов)."""
    if not clean_text:
        return False
    padded = f" {clean_text} "
    for word in state.get("target_words") or []:
        normalized_word = _normalized_text(word)
        if normalized_word and f" {normalized_word} " in padded:
            return True
    phrase = _normalized_text(state.get("target_phrase") or "")
    if not phrase:
        return False
    if phrase in clean_text:
        return True
    tokens = [token for token in phrase.split() if len(token) > 2]
    if len(tokens) >= 2:
        matched = sum(1 for token in tokens if f" {token} " in padded)
        return matched >= 2
    return False


def advance_lesson_state(state: dict[str, Any], role: str, text: str) -> dict[str, Any]:
    updated = dict(state)
    updated["topic_suggestions"] = list(state.get("topic_suggestions") or [])
    updated["target_words"] = list(state.get("target_words") or [])
    updated["age_group"] = normalize_age_group(updated.get("age_group"))
    updated["target_hits"] = int(updated.get("target_hits") or 0)
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
                "target_hits": 0,
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
        if updated.get("current_topic") and _used_target(updated, clean):
            updated["target_hits"] = int(updated.get("target_hits") or 0) + 1
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
    hits = int(updated.get("target_hits") or 0)
    # Фазу двигаем по реальному мастерству (ребёнок произнёс цель), но с потолком
    # по числу ходов, чтобы урок продвигался даже без попаданий (старое поведение
    # сохраняется как «пол»). Условия монотонны — фаза не откатывается назад.
    if turns <= 2 and hits == 0:
        updated["phase"] = "mini_lesson"
    elif (hits >= 2 and turns >= 6) or turns >= 10:
        updated["phase"] = "wrapup"
    elif (hits >= 1 and turns >= 4) or turns >= 8:
        updated["phase"] = "challenge"
    else:
        updated["phase"] = "dialogue"
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
        suggested_topic = suggestion_labels[0] if suggestion_labels else "простая тема дня"
        if support_mode == "confused":
            instruction = (
                "Урок еще не выбрал тему, а ребенок запутался. Не перечисляй темы. "
                "Сначала спокойно объясни по-русски, затем сам начни один суперлегкий английский шаг "
                f"в теме «{suggested_topic}» и дай выбор из двух простых вариантов."
            )
        elif support_mode == "tired":
            instruction = (
                "Урок еще не выбрал тему, а ребенок устал или скучает. Не перечисляй темы. "
                f"Сам начни очень легкую игру в теме «{suggested_topic}» одним вопросом."
            )
        elif support_mode == "correction":
            instruction = (
                "Урок еще не выбрал тему, но ребенок уже пробует английскую фразу. "
                "Не перечисляй темы. Мягко исправь одну ошибку, дай правильный вариант "
                "и один связанный вопрос по смыслу фразы ребенка."
            )
        else:
            instruction = (
                "Урок еще не выбрал тему. ВЕДИ урок сам, не жди, пока ребенок предложит тему, и не "
                f"перечисляй меню тем. Тепло поздоровайся и уверенно начни тему «{suggested_topic}»: дай одно "
                "простое английское слово или короткую фразу строго по этой теме и задай один лёгкий вопрос по ней."
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
            "и дай один конкретный совет по учёбе, как лучше запомнить — по возрасту ребёнка "
            "(например: повтори эти слова завтра, скажи фразу вслух три раза или используй её сегодня "
            "в реальной ситуации). Предложи продолжить позже. Не начинай новый урок самостоятельно."
        )
    if support_mode == "confused":
        instruction += " Ребенок запутался: сначала объясни по-русски проще и дай выбор из двух вариантов."
    elif support_mode == "tired":
        instruction += " Ребенок устал: сохрани тему, но замени следующий шаг на очень легкую игру или закончи урок."
    elif support_mode == "correction":
        instruction += " Исправь только одну главную ошибку мягко: похвали попытку, дай естественный вариант и одну легкую практику."
    elif support_mode == "bridge":
        instruction += (
            " Ребенок упомянул другую тему. Его фразу НЕ исправляй и не говори «почти» или «лучше так» — "
            "это не ошибка. Тепло поддержи его мысль и мягко свяжи её с текущей темой одним живым вопросом, "
            "не переключая урок."
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
