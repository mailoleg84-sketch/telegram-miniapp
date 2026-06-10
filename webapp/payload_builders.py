"""Чистые сборщики JSON-payload'ов для API-слоя.

Вынесено из webapp/server.py (шаг рефакторинга 3b) без изменения поведения.
Здесь только чистые функции: строят словари ответов из строк БД и констант.
Зависят от webapp/formatters (доступ к строкам, метки) и config — без БД/OpenAI/
хранилища/aiohttp и без обращений к runtime-состоянию server.py. server.py
реэкспортирует эти имена, поэтому существующие импорты/вызовы продолжают работать.

Намеренно НЕ вынесены сборщики, завязанные на server.py: `_admin_overview_payload`
(`GENERATED_VOCAB_DIR`/`_file_cache_summary`), `_admin_user_detail_payload`
(`_normalized_age_group_for_user`), `_problem_word_dict`/`_dictionary_word_dict`
(`_word_dict` → визуализатор), `_learning_path_payload`/`_motivation_payload`.
"""
import json

from config import AI_DAILY_MESSAGE_LIMIT, DAILY_LESSON_STEPS
from webapp.formatters import (
    _safe_int,
    _record_value,
    _age_label,
    _goal_label,
    _level_label,
    _date_text,
)


def _chat_usage_payload(stats) -> dict:
    used = int(stats["requests"] if stats else 0)
    limit = AI_DAILY_MESSAGE_LIMIT
    unlimited = limit <= 0
    remaining = None if unlimited else max(0, limit - used)
    return {
        "used_today": used,
        "daily_limit": None if unlimited else limit,
        "remaining_today": remaining,
        "unlimited": unlimited,
        "limit_reached": (not unlimited) and used >= limit,
        "input_tokens_today": int(stats["input_tokens"] if stats else 0),
        "output_tokens_today": int(stats["output_tokens"] if stats else 0),
        "total_tokens_today": int(stats["total_tokens"] if stats else 0),
        "cost_usd_today": round(float(stats["cost_usd"] if stats else 0), 6),
    }


def _daily_lesson_payload(status, reward_points: int = 0, points: int | None = None) -> dict:
    completed_steps = int(status["completed_steps"] if status else 0)
    return {
        "lesson_date": status["lesson_date"] if status else "",
        "completed_steps": completed_steps,
        "total_steps": DAILY_LESSON_STEPS,
        "completed": bool(status["completed"] if status else False),
        "rewarded": bool(status["rewarded"] if status else False),
        "reward_points": reward_points,
        "points": points,
    }


def _admin_user_dict(row) -> dict:
    total_answers = _safe_int(row, "total_correct") + _safe_int(row, "total_wrong")
    accuracy = round(_safe_int(row, "total_correct") / total_answers * 100) if total_answers else 0
    age_group = _record_value(row, "age_group", "")
    return {
        "id": _safe_int(row, "user_id"),
        "child_name": _record_value(row, "name", ""),
        "parent_name": _record_value(row, "parent_name", "") or "",
        "child_age": _record_value(row, "child_age", None),
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "goal_label": _goal_label(_record_value(row, "goal", "")),
        "level_label": _level_label(_record_value(row, "english_level", "")),
        "level_test_score": _record_value(row, "level_test_score", None),
        "level_test_completed": bool(_record_value(row, "level_test_completed_at")),
        "points": _safe_int(row, "points"),
        "registered_at": _date_text(_record_value(row, "registered_at")),
        "words_learned": _safe_int(row, "words_learned"),
        "total_correct": _safe_int(row, "total_correct"),
        "total_wrong": _safe_int(row, "total_wrong"),
        "accuracy": accuracy,
        "completed_lessons": _safe_int(row, "completed_lessons"),
        "completed_word_tests": _safe_int(row, "completed_word_tests"),
        "completed_games": _safe_int(row, "completed_games"),
    }


def _admin_failed_image_dict(row) -> dict:
    raw_review = _record_value(row, "generated_image_review", "") or ""
    reason = ""
    try:
        parsed = json.loads(raw_review)
        reason = str(parsed.get("reason") or "")
    except Exception:
        reason = raw_review[:180]
    return {
        "id": _safe_int(row, "id"),
        "word": _record_value(row, "word", ""),
        "translation": _record_value(row, "translation", ""),
        "topic": _record_value(row, "topic", ""),
        "age_group": _record_value(row, "age_group", ""),
        "status": _record_value(row, "generated_image_status", "failed"),
        "reason": reason,
        "checked_at": _date_text(_record_value(row, "generated_image_checked_at")),
    }


def _activity_event_dict(row) -> dict:
    event_type = row["event_type"]
    if event_type == "daily_lesson":
        title = "Урок дня"
        description = "Урок завершён"
    elif event_type == "word_game":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Игровая практика"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type == "word_test":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Учим слова"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type in {"review_training", "word_training"}:
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Работа над ошибками" if event_type == "review_training" else "Тренировка слов"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    else:
        title = "Тест уровня"
        description = f"Результат: {int(row['score'] or 0)}%"

    return {
        "type": event_type,
        "date": row["event_date"] or "",
        "event_at": _date_text(row["event_at"]),
        "title": title,
        "description": description,
        "score": row["score"],
    }


def _parent_recommendations(report: dict, dictionary_summary: dict, problem_words: list[dict]) -> list[dict]:
    words_learned = int(report.get("words_learned") or 0)
    completed_lessons = int(report.get("completed_lessons") or 0)
    completed_word_tests = int(report.get("completed_word_tests") or 0)
    avg_score = int(report.get("avg_word_test_score") or 0)
    total_wrong = int(report.get("total_wrong") or 0)
    review_words = int((dictionary_summary or {}).get("review_words") or 0)
    recommendations = []

    if completed_lessons == 0:
        recommendations.append({
            "title": "Начать с короткого урока",
            "text": "Пусть ребенок пройдет ежедневный урок на 5 минут: слова, мини-тест и простая фраза.",
            "action": "daily",
        })
    if words_learned == 0:
        recommendations.append({
            "title": "Добавить первые слова",
            "text": "Запустите набор новых слов с тестом, чтобы появился базовый словарь и первые результаты.",
            "action": "vocab",
        })
    if review_words > 0:
        recommendations.append({
            "title": "Повторить слова по расписанию",
            "text": f"{review_words} слов сегодня готовы к повторению — у них подошёл интервал. Короткая тренировка освежит их в памяти.",
            "action": "review",
        })
    if completed_word_tests > 0 and avg_score < 70:
        recommendations.append({
            "title": "Снизить сложность на один шаг",
            "text": "Средний результат тестов ниже 70%. Дайте больше повторения и короткие задания без спешки.",
            "action": "review",
        })
    if problem_words and total_wrong > 0:
        sample = ", ".join(word["word"] for word in problem_words[:3])
        recommendations.append({
            "title": "Фокус на конкретных словах",
            "text": f"Чаще всего ошибается в словах: {sample}. Их стоит повторить в короткой тренировке.",
            "action": "dictionary",
        })
    if not recommendations:
        recommendations.append({
            "title": "Продолжать текущий темп",
            "text": "Прогресс выглядит ровно. Достаточно 5-10 минут в день: урок, повторение и короткая устная практика.",
            "action": "daily",
        })
    return recommendations[:4]


def _motivation_badge(
    badge_id: str,
    title: str,
    text: str,
    value: int,
    target: int,
    action: str,
) -> dict:
    target = max(1, target)
    value = max(0, value)
    return {
        "id": badge_id,
        "title": title,
        "text": text,
        "value": value,
        "target": target,
        "progress_percent": min(100, round(value / target * 100)),
        "unlocked": value >= target,
        "action": action,
    }
