"""Планы тем урока по возрастным группам (вынесено из lesson_engine.py).

Чистые данные + приватный конструктор _topic. Логика урока — в
webapp/lesson_engine.py, который реэкспортирует TOPIC_PLANS."""
from __future__ import annotations

from typing import Any


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
        _topic("animals", "Животные", "назвать любимое животное", "I like cats.", ["cat", "dog", "rabbit"], ["animals", "animal", "cat", "dog", "rabbit", "животные", "животное", "животных", "кошка", "собака", "кот", "питомец"]),
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
        _topic("games", "Игры", "рассказать о любимой игре", "I like this game because it is fun.", ["game", "level", "team"], ["games", "game", "minecraft", "roblox", "игры", "игра", "майнкрафт", "роблокс"]),
        _topic("sports", "Спорт", "сказать, каким спортом нравится заниматься", "I like playing football.", ["sport", "team", "score"], ["sports", "sport", "спорт", "футбол"]),
        _topic("animals", "Животные", "описать любимое животное", "My favorite animal is a dolphin.", ["wild", "fast", "friendly"], ["animals", "animal", "cat", "dog", "rabbit", "животные", "животное", "животных", "кошка", "собака", "кот", "питомец"]),
        _topic("superheroes", "Супергерои", "описать способность героя", "My hero can fly.", ["hero", "power", "brave"], ["superheroes", "superhero", "супергерой", "герой"]),
        _topic("holidays", "Каникулы", "рассказать об идеальном дне каникул", "On holiday, I want to swim.", ["holiday", "trip", "beach"], ["holidays", "holiday", "каникулы", "отпуск"]),
        _topic("food", "Любимая еда", "заказать любимую еду", "Can I have a pizza, please?", ["menu", "pizza", "juice"], ["food", "еда", "еду", "пицца", "кафе"]),
        _topic("daily_routine", "Мой день", "описать часть своего дня", "I get up at seven.", ["morning", "school", "evening"], ["routine", "daily routine", "мой день", "распорядок"]),
        _topic("dream_house", "Дом мечты", "описать одну комнату мечты", "My dream house has a game room.", ["house", "room", "garden"], ["dream house", "house", "дом мечты", "дом"]),
    ],
    "11_13": [
        _topic("hobbies", "Хобби", "объяснить, почему нравится хобби", "I enjoy drawing because it helps me relax.", ["hobby", "enjoy", "practice"], ["hobbies", "hobby", "хобби"]),
        _topic("video_games", "Видеоигры", "описать игру и дать мнение", "I like this game because the story is exciting.", ["character", "level", "story"], ["video games", "gaming", "games", "minecraft", "roblox", "видеоигры", "игры", "майнкрафт", "роблокс"]),
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
        _topic("technology", "Технологии", "обсудить пользу и риски технологии", "Technology is useful when we use it thoughtfully.", ["privacy", "device", "feature"], ["technology", "tech", "minecraft", "roblox", "технологии", "майнкрафт", "роблокс"]),
        _topic("social_media", "Социальные сети", "выразить взвешенное мнение", "Social media can be useful, but it can also be distracting.", ["content", "privacy", "audience"], ["social media", "соцсети", "социальные сети"]),
        _topic("exams", "Экзамены", "дать развернутый экзаменационный ответ", "One effective way to prepare is to practice regularly.", ["prepare", "focus", "result"], ["exams", "exam", "экзамены", "экзамен"]),
        _topic("business", "Бизнес", "предложить простую бизнес-идею", "My idea solves a simple everyday problem.", ["customer", "idea", "value"], ["business", "бизнес"]),
        _topic("real_life_english", "Английский для жизни", "поддержать естественный small talk", "How has your week been so far?", ["actually", "probably", "sounds good"], ["real life english", "small talk", "английский для жизни", "разговор"]),
        _topic("interviews", "Собеседования", "уверенно ответить на вопрос о себе", "One of my strengths is that I learn quickly.", ["strength", "experience", "improve"], ["interviews", "interview", "собеседование", "интервью"]),
    ],
}
