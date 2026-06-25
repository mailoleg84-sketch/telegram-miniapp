"""Word-payload слой: словари слова для API-ответов и URL-ы картинок слова.

Вынесено из webapp/server.py (шаг рефакторинга 3d-1) без изменения поведения.
Зависимости направлены только «вниз» (config, storage, vocabulary_visualizer,
svg_renderer, stdlib) — модуль НЕ импортирует server.py, циклов нет. server.py
реэкспортирует имена: существующие вызовы и импорты в тестах работают как раньше.
Этот модуль разблокирует вынос training-хендлеров (они строят word-payload'ы).
"""
import hashlib
import json
from urllib.parse import urlencode

from config import VOCAB_AI_IMAGES, APP_VERSION, VOCAB_FREE_PHOTOS
from webapp import storage
from webapp.svg_renderer import _word_image_icon
from webapp.vocabulary_visualizer import (
    allows_free_photo,
    build_vocabulary_visual,
    is_sensitive_word,
    vocabulary_image_url,
)

# Для локального backend — каталог (Path); для S3/R2 — None (производное от
# storage значение, не разделяемое состояние; так же вычисляет server.py).
GENERATED_VOCAB_DIR = getattr(storage.vocab_image_storage, "base_dir", None)


def _word_image_url(word: str, topic: str = "") -> str:
    clean_word = " ".join(str(word or "").split())[:48]
    clean_topic = " ".join(str(topic or "basic").split())[:32]
    if _word_image_icon(clean_word):
        query = urlencode({
            "w": clean_word,
            "t": clean_topic,
            "iv": APP_VERSION,  # кэш-бастинг SVG при правке художки (см. vocabulary_image_url)
        })
        return f"/word-image.svg?{query}"
    visual = build_vocabulary_visual(
        word=clean_word,
        translation="",
        example_sentence="",
        topic=clean_topic,
    )
    svg_url = visual.get("image_url") or vocabulary_image_url(clean_word, visual.get("visual_type", "no_good_visual"), clean_topic)
    return _vocab_card_image_url(
        clean_word, svg_url, visual.get("emoji", ""),
        visual.get("visual_type", ""), clean_topic,
    )


# Конкретные существительные (allows_free_photo: visual_type == "object") получают
# бесплатное child-safe фото Pixabay (/vocabulary-photo, кэш по слову, safesearch);
# действия / абстрактные существительные / прилагательные / служебные слова — единую
# контролируемую SVG-сцену. Эмодзи остаётся маленьким бейджем поверх картинки (v153).


def _vocab_card_image_url(
    word: str,
    fallback_url: str,
    emoji: str = "",
    visual_type: str = "",
    topic: str = "",
) -> str:
    """Фото Pixabay для конкретных существительных (allows_free_photo), иначе SVG/AI
    fallback. Условие «без emoji» убрано: эмодзи рендерится бейджем поверх (v153),
    поэтому apple показывает фото + 🍎. Сенситивные слова фото не получают."""
    w = " ".join(str(word or "").split()).lower()
    if (
        VOCAB_FREE_PHOTOS
        and w
        and not is_sensitive_word(w)
        and allows_free_photo(w, visual_type)
    ):
        params = {"w": w[:40]}
        t = " ".join(str(topic or "").split()).lower()[:32]
        if t:
            params["t"] = t
        return "/vocabulary-photo?" + urlencode(params)
    return fallback_url


def _vocabulary_image_prompt_hash(visual: dict) -> str:
    payload = {
        key: str(visual.get(key) or "")
        for key in (
            "word",
            "translation",
            "visual_type",
            "image_prompt",
            "example_sentence",
            "simple_meaning",
            "russian_hint",
        )
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _generated_vocab_url_exists(url: str) -> bool:
    if not url or not url.startswith("/static/generated/vocabulary/"):
        return False
    filename = url.rsplit("/", 1)[-1]
    if not filename or "/" in filename or "\\" in filename:
        return False
    if GENERATED_VOCAB_DIR is None:
        # S3/R2 — хранилище персистентно: раз URL в БД, объект существует. Доверяем
        # (в отличие от эфемерного диска, где файл мог стереться при деплое).
        return True
    return (GENERATED_VOCAB_DIR / filename).is_file()


def _generated_vocab_extension(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get((content_type or "").lower(), "png")


def _generated_vocab_static_url(filename: str) -> str:
    return f"/static/generated/vocabulary/{filename}"


def _word_dict(word, learner_level: str = "beginner") -> dict:
    if not word:
        return {}
    def value(key: str, default=""):
        try:
            item = word[key]
        except (KeyError, IndexError, TypeError):
            return default
        return default if item is None else item

    transcription = value("transcription", "")
    topic = word["topic"] or "basic"
    visual = build_vocabulary_visual(
        word=value("word", ""),
        translation=value("translation", ""),
        example_sentence=value("example", ""),
        topic=topic,
        age_group=value("age_group", ""),
        level=learner_level,
    )
    visual.update({
        "word": value("word", ""),
        "translation": value("translation", ""),
    })
    emoji = visual.get("emoji", "")
    fallback_image_url = visual["image_url"]
    image_prompt_hash = _vocabulary_image_prompt_hash(visual)
    generated_image_url = value("generated_image_url", "")
    generated_image_status = value("generated_image_status", "missing") or "missing"
    generated_prompt_hash = value("generated_image_prompt_hash", "")
    if (
        generated_image_url
        and generated_prompt_hash == image_prompt_hash
        and generated_image_status in {"generated", "needs_review"}
        and _generated_vocab_url_exists(generated_image_url)
    ):
        image_url = generated_image_url
    else:
        image_url = _vocab_card_image_url(
            value("word", ""), fallback_image_url, emoji,
            visual.get("visual_type", ""), value("topic", ""),
        )
        if generated_image_status in {"generated", "needs_review"}:
            generated_image_status = "missing"

    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": transcription,
        "example": word["example"] or "",
        "topic": topic,
        "age_group": word["age_group"] or "",
        "part_of_speech": visual["part_of_speech"],
        "visual_type": visual["visual_type"],
        "card_archetype": visual.get("card_archetype", ""),
        "question_archetype": visual.get("question_archetype", ""),
        "visual_confidence_label": visual.get("visual_confidence_label", ""),
        "visual_learning_note": visual.get("visual_learning_note", ""),
        "image_prompt": visual["image_prompt"],
        "emoji": visual.get("emoji", ""),
        "image_url": image_url,
        "fallback_image_url": fallback_image_url,
        "generated_image_url": generated_image_url if image_url == generated_image_url else "",
        "image_can_generate": VOCAB_AI_IMAGES,
        "image_generation_status": generated_image_status,
        "image_prompt_hash": image_prompt_hash,
        "image_alt": visual["image_alt"],
        "example_sentence": visual["example_sentence"],
        "simple_meaning": visual["simple_meaning"],
        "russian_hint": visual["russian_hint"],
        "image_confidence": visual["image_confidence"],
        "image_needs_review": visual["needs_review"],
        "needs_review": visual["needs_review"],
        "generation_status": visual["generation_status"],
        "show_russian_hint": visual["show_russian_hint"],
    }


def _dictionary_word_dict(word) -> dict:
    data = _word_dict(word)
    correct_count = int(word["correct_count"] or 0)
    wrong_count = int(word["wrong_count"] or 0)
    mastered = bool(word["mastered"])
    needs_review = bool(word["needs_review"])
    # SRS: «пора повторить» важнее «выучено». Освоенное слово, у которого подошёл
    # интервал (needs_review=due), показываем как «повторить» — иначе оно с ярлыком
    # «выучено» молча выпадало бы из визуального потока повторения (и из фильтра).
    if needs_review:
        status = "review"
        status_label = "повторить"
    elif mastered:
        status = "mastered"
        status_label = "выучено"
    else:
        status = "learning"
        status_label = "учим"
    data.update({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "needs_review": needs_review,
        "mastered": mastered,
        "status": status,
        "status_label": status_label,
    })
    return data


def _problem_word_dict(word) -> dict:
    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": _word_dict(word).get("transcription", ""),
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "correct_count": int(word["correct_count"] or 0),
        "wrong_count": int(word["wrong_count"] or 0),
    }
