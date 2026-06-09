"""Чистые помощники представления для API-слоя: безопасный доступ к строкам БД,
форматтеры меток (возраст/цель/уровень) и логика уровня по тесту.

Вынесено из webapp/server.py (шаг рефакторинга 3a) без изменения поведения.
Здесь нет зависимостей от БД/OpenAI/хранилища/aiohttp — только чистые функции и
данные из config / data.level_tests. server.py реэкспортирует эти имена, поэтому
`from webapp.server import _level_from_score, ...` продолжает работать.
"""
from config import (
    AGE_GROUPS,
    ENGLISH_LEVELS,
    LEARNING_GOALS,
    TUTOR_DEFAULT_LEVEL,
)
from data.level_tests import LEVEL_TESTS


def _record_value(row, key: str, default=None):
    if not row:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return value if value not in (None, "") else default


def _safe_int(row, key: str, default: int = 0) -> int:
    try:
        return int(_record_value(row, key, default) or 0)
    except (TypeError, ValueError):
        return default


def _safe_float(row, key: str, default: float = 0.0) -> float:
    try:
        return float(_record_value(row, key, default) or 0)
    except (TypeError, ValueError):
        return default


def _date_text(value) -> str:
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _age_label(age_group: str) -> str:
    return next((label for label, value in AGE_GROUPS if value == age_group), age_group)


def _goal_label(goal: str | None) -> str:
    return next((label for label, value in LEARNING_GOALS if value == goal), goal or "")


def _level_label(level: str | None) -> str:
    return next((label for label, value in ENGLISH_LEVELS if value == level), level or "Не определен")


def _estimated_level_for_user(user) -> str:
    goal = _record_value(user, "goal", "")
    age_group = _record_value(user, "age_group", "")
    if goal in {"exams", "travel"} or age_group == "14_18":
        return "elementary"
    if age_group in {"5_7", "8_10"} or goal == "first_steps":
        return "beginner"
    return "beginner"


def _level_for_user(user) -> str:
    return _record_value(user, "english_level") or _estimated_level_for_user(user) or TUTOR_DEFAULT_LEVEL


def _level_from_score(age_group: str, correct_count: int, total: int) -> str:
    if total <= 0:
        return _estimated_level_for_user({"age_group": age_group})
    score = correct_count / total
    if age_group == "5_7":
        return "beginner" if score >= 0.65 else "starter"
    if age_group == "8_10":
        if score < 0.35:
            return "starter"
        if score < 0.75:
            return "beginner"
        return "elementary"
    if score < 0.35:
        return "beginner"
    if score < 0.75:
        return "elementary"
    return "pre_intermediate"


def _level_result_message(level: str) -> str:
    messages = {
        "starter": "Начнем очень мягко: первые слова, короткие фразы и много поддержки.",
        "beginner": "Хорошая база для простых диалогов. Будем уверенно строить фразы.",
        "elementary": "Можно добавлять больше грамматики, мини-диалоги и школьные темы.",
        "pre_intermediate": "Отлично, можно тренировать живую речь, объяснения и более длинные ответы.",
    }
    return messages.get(level, "Репетитор подстроит задания под этот уровень.")


def _level_questions_for_age(age_group: str) -> list[dict]:
    return LEVEL_TESTS.get(age_group) or LEVEL_TESTS["8_10"]


def _public_level_question(question: dict) -> dict:
    return {
        "id": question["id"],
        "prompt": question["prompt"],
        "options": [
            {"id": option_id, "text": text}
            for option_id, text in question["options"]
        ],
    }


def _path_step(step_id: str, title: str, text: str, action: str, status: str) -> dict:
    return {
        "id": step_id,
        "title": title,
        "text": text,
        "action": action,
        "status": status,
    }


def _game_title(game_type: str) -> str:
    titles = {
        "word_hunt": "Словесная охота",
    }
    return titles.get(game_type, "Игра со словами")
