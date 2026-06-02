"""Стартовый словарь для детского AI-репетитора.

Формат итоговой записи:
(word, translation, example, topic, age_group)

База строится программно, чтобы держать ровно 5000 безопасных учебных
словарных единиц без ручного файла на тысячи строк. В базе есть одиночные
слова и короткие словосочетания: для детского обучения это полезнее, чем
только разрозненные слова.
"""

from __future__ import annotations

from collections import Counter
import re

import pronouncing


TARGET_WORD_COUNT = 5000
TARGET_PER_AGE_GROUP = {
    "5_7": 1250,
    "8_10": 1250,
    "11_13": 1250,
    "14_18": 1250,
}


Entry5 = tuple[str, str, str, str, str]
Entry6 = tuple[str, str, str, str, str, str]


ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ə", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɝ",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

PHONETIC_OVERRIDES = {
    "mom": "mɑm",
    "dad": "dæd",
    "grandma": "ˈɡrænˌmɑ",
    "grandpa": "ˈɡrænˌpɑ",
}

_IPA_CACHE: dict[str, str] = {}


def _arpabet_to_ipa(phones: str) -> str:
    raw_phones = phones.split()
    parts = []
    for raw_phone in raw_phones:
        phone = raw_phone
        if raw_phone[-1:] in {"0", "1", "2"}:
            phone = raw_phone[:-1]
        if phone == "AH" and raw_phone[-1:] in {"1", "2"}:
            ipa = "ʌ"
        elif phone == "ER" and raw_phone[-1:] == "0":
            ipa = "ɚ"
        else:
            ipa = ARPABET_TO_IPA.get(phone, phone.lower())
        parts.append(ipa)
    return "".join(parts)


def _ipa_token(token: str) -> str:
    token = token.lower()
    if token in _IPA_CACHE:
        return _IPA_CACHE[token]
    if token in PHONETIC_OVERRIDES:
        _IPA_CACHE[token] = PHONETIC_OVERRIDES[token]
        return _IPA_CACHE[token]
    phones = pronouncing.phones_for_word(token)
    _IPA_CACHE[token] = _arpabet_to_ipa(phones[0]) if phones else token
    return _IPA_CACHE[token]


def _transcription(text: str) -> str:
    tokens = re.findall(r"[a-z]+", text.lower())
    if not tokens:
        return ""
    return "/" + " ".join(_ipa_token(token) for token in tokens) + "/"


CORE_WORDS: list[Entry5] = [
    # 5-7
    ("cat", "кошка", "The cat is cute.", "animals", "5_7"),
    ("dog", "собака", "The dog is happy.", "animals", "5_7"),
    ("sun", "солнце", "The sun is yellow.", "nature", "5_7"),
    ("ball", "мяч", "I have a red ball.", "toys", "5_7"),
    ("apple", "яблоко", "I like apples.", "food", "5_7"),
    ("milk", "молоко", "I drink milk.", "food", "5_7"),
    ("red", "красный", "The ball is red.", "colors", "5_7"),
    ("blue", "синий", "The sky is blue.", "colors", "5_7"),
    ("mom", "мама", "My mom is kind.", "family", "5_7"),
    ("dad", "папа", "My dad is tall.", "family", "5_7"),

    # 8-10
    ("school", "школа", "I go to school every day.", "school", "8_10"),
    ("teacher", "учитель", "My teacher is friendly.", "school", "8_10"),
    ("pencil", "карандаш", "I write with a pencil.", "school", "8_10"),
    ("friend", "друг", "He is my best friend.", "friends", "8_10"),
    ("breakfast", "завтрак", "I eat breakfast at eight.", "food", "8_10"),
    ("homework", "домашняя работа", "I do my homework after school.", "school", "8_10"),
    ("playground", "площадка", "We play in the playground.", "school", "8_10"),
    ("rabbit", "кролик", "The rabbit is small.", "animals", "8_10"),
    ("window", "окно", "Open the window, please.", "home", "8_10"),
    ("kitchen", "кухня", "My family is in the kitchen.", "home", "8_10"),

    # 11-13
    ("subject", "предмет в школе", "English is my favorite subject.", "school", "11_13"),
    ("library", "библиотека", "I borrow books from the library.", "school", "11_13"),
    ("weekend", "выходные", "I visit my grandma at the weekend.", "everyday", "11_13"),
    ("usually", "обычно", "I usually get up at seven.", "grammar", "11_13"),
    ("because", "потому что", "I study English because it is useful.", "grammar", "11_13"),
    ("hobby", "хобби", "My hobby is drawing.", "hobbies", "11_13"),
    ("practice", "практиковаться", "I practice English every day.", "learning", "11_13"),
    ("question", "вопрос", "Can I ask a question?", "school", "11_13"),
    ("answer", "ответ", "Write the answer in your notebook.", "school", "11_13"),
    ("weather", "погода", "The weather is sunny today.", "everyday", "11_13"),

    # 14-18
    ("confident", "уверенный", "I feel confident when I speak English.", "speaking", "14_18"),
    ("opinion", "мнение", "In my opinion, this film is great.", "speaking", "14_18"),
    ("improve", "улучшать", "I want to improve my pronunciation.", "learning", "14_18"),
    ("experience", "опыт", "This trip was a great experience.", "travel", "14_18"),
    ("interview", "собеседование", "I have an interview on Monday.", "work", "14_18"),
    ("deadline", "дедлайн", "The deadline is tomorrow.", "study", "14_18"),
    ("prepare", "готовиться", "I prepare for my exam every evening.", "exams", "14_18"),
    ("achieve", "достигать", "You can achieve your goal.", "motivation", "14_18"),
    ("abroad", "за границей", "She wants to study abroad.", "travel", "14_18"),
    ("presentation", "презентация", "I made a presentation in English.", "study", "14_18"),
]


NOUNS = [
    # 5-7
    ("baby", "малыш", "family", "5_7"), ("bear", "медведь", "animals", "5_7"),
    ("bird", "птица", "animals", "5_7"), ("boat", "лодка", "toys", "5_7"),
    ("book", "книга", "school", "5_7"), ("box", "коробка", "toys", "5_7"),
    ("bread", "хлеб", "food", "5_7"), ("bus", "автобус", "transport", "5_7"),
    ("cake", "торт", "food", "5_7"), ("car", "машина", "transport", "5_7"),
    ("chair", "стул", "home", "5_7"), ("cheese", "сыр", "food", "5_7"),
    ("clock", "часы", "home", "5_7"), ("cloud", "облако", "nature", "5_7"),
    ("coat", "пальто", "clothes", "5_7"), ("cup", "чашка", "home", "5_7"),
    ("duck", "утка", "animals", "5_7"), ("egg", "яйцо", "food", "5_7"),
    ("eye", "глаз", "body", "5_7"), ("face", "лицо", "body", "5_7"),
    ("fish", "рыба", "animals", "5_7"), ("flower", "цветок", "nature", "5_7"),
    ("frog", "лягушка", "animals", "5_7"), ("game", "игра", "games", "5_7"),
    ("garden", "сад", "nature", "5_7"), ("goat", "коза", "animals", "5_7"),
    ("hand", "рука", "body", "5_7"), ("hat", "шапка", "clothes", "5_7"),
    ("horse", "лошадь", "animals", "5_7"), ("house", "дом", "home", "5_7"),
    ("juice", "сок", "food", "5_7"), ("kite", "воздушный змей", "toys", "5_7"),
    ("lamp", "лампа", "home", "5_7"), ("leaf", "лист", "nature", "5_7"),
    ("leg", "нога", "body", "5_7"), ("lion", "лев", "animals", "5_7"),
    ("moon", "луна", "nature", "5_7"), ("mouse", "мышь", "animals", "5_7"),
    ("orange", "апельсин", "food", "5_7"), ("park", "парк", "places", "5_7"),
    ("pen", "ручка", "school", "5_7"), ("pig", "свинья", "animals", "5_7"),
    ("plane", "самолет", "transport", "5_7"), ("rain", "дождь", "nature", "5_7"),
    ("river", "река", "nature", "5_7"), ("robot", "робот", "toys", "5_7"),
    ("shoe", "ботинок", "clothes", "5_7"), ("star", "звезда", "nature", "5_7"),
    ("table", "стол", "home", "5_7"), ("tree", "дерево", "nature", "5_7"),

    # 8-10
    ("airport", "аэропорт", "travel", "8_10"), ("aunt", "тетя", "family", "8_10"),
    ("basket", "корзина", "home", "8_10"), ("beach", "пляж", "travel", "8_10"),
    ("bedroom", "спальня", "home", "8_10"), ("bike", "велосипед", "transport", "8_10"),
    ("birthday", "день рождения", "everyday", "8_10"), ("board", "доска", "school", "8_10"),
    ("bottle", "бутылка", "home", "8_10"), ("brother", "брат", "family", "8_10"),
    ("camera", "камера", "hobbies", "8_10"), ("candle", "свеча", "home", "8_10"),
    ("cartoon", "мультфильм", "hobbies", "8_10"), ("classmate", "одноклассник", "school", "8_10"),
    ("classroom", "класс", "school", "8_10"), ("computer", "компьютер", "technology", "8_10"),
    ("cookie", "печенье", "food", "8_10"), ("cousin", "двоюродный брат или сестра", "family", "8_10"),
    ("desk", "парта", "school", "8_10"), ("dictionary", "словарь", "school", "8_10"),
    ("dinner", "ужин", "food", "8_10"), ("doctor", "доктор", "jobs", "8_10"),
    ("dress", "платье", "clothes", "8_10"), ("email", "электронное письмо", "technology", "8_10"),
    ("farm", "ферма", "places", "8_10"), ("folder", "папка", "school", "8_10"),
    ("football", "футбол", "sports", "8_10"), ("grandma", "бабушка", "family", "8_10"),
    ("grandpa", "дедушка", "family", "8_10"), ("guitar", "гитара", "music", "8_10"),
    ("hospital", "больница", "places", "8_10"), ("lesson", "урок", "school", "8_10"),
    ("lunch", "обед", "food", "8_10"), ("market", "рынок", "places", "8_10"),
    ("movie", "фильм", "hobbies", "8_10"), ("museum", "музей", "places", "8_10"),
    ("notebook", "тетрадь", "school", "8_10"), ("page", "страница", "school", "8_10"),
    ("parent", "родитель", "family", "8_10"), ("party", "вечеринка", "friends", "8_10"),
    ("picture", "картинка", "art", "8_10"), ("postcard", "открытка", "travel", "8_10"),
    ("questionnaire", "анкета", "school", "8_10"), ("restaurant", "ресторан", "food", "8_10"),
    ("sister", "сестра", "family", "8_10"), ("skateboard", "скейтборд", "sports", "8_10"),
    ("station", "станция", "travel", "8_10"), ("ticket", "билет", "travel", "8_10"),
    ("uncle", "дядя", "family", "8_10"), ("village", "деревня", "places", "8_10"),

    # 11-13
    ("adventure", "приключение", "stories", "11_13"), ("album", "альбом", "hobbies", "11_13"),
    ("article", "статья", "reading", "11_13"), ("biology", "биология", "school", "11_13"),
    ("camp", "лагерь", "travel", "11_13"), ("chapter", "глава", "reading", "11_13"),
    ("chemistry", "химия", "school", "11_13"), ("choice", "выбор", "everyday", "11_13"),
    ("club", "клуб", "hobbies", "11_13"), ("conversation", "разговор", "speaking", "11_13"),
    ("culture", "культура", "society", "11_13"), ("diary", "дневник", "writing", "11_13"),
    ("direction", "направление", "travel", "11_13"), ("drawing", "рисование", "art", "11_13"),
    ("dream", "мечта", "motivation", "11_13"), ("energy", "энергия", "science", "11_13"),
    ("environment", "окружающая среда", "nature", "11_13"), ("event", "событие", "everyday", "11_13"),
    ("exercise", "упражнение", "learning", "11_13"), ("experiment", "эксперимент", "science", "11_13"),
    ("fact", "факт", "learning", "11_13"), ("festival", "фестиваль", "culture", "11_13"),
    ("future", "будущее", "time", "11_13"), ("geography", "география", "school", "11_13"),
    ("habit", "привычка", "everyday", "11_13"), ("history", "история", "school", "11_13"),
    ("information", "информация", "learning", "11_13"), ("internet", "интернет", "technology", "11_13"),
    ("language", "язык", "learning", "11_13"), ("magazine", "журнал", "reading", "11_13"),
    ("memory", "память", "learning", "11_13"), ("message", "сообщение", "communication", "11_13"),
    ("mistake", "ошибка", "learning", "11_13"), ("music", "музыка", "music", "11_13"),
    ("novel", "роман", "reading", "11_13"), ("planet", "планета", "science", "11_13"),
    ("project", "проект", "school", "11_13"), ("pronunciation", "произношение", "speaking", "11_13"),
    ("recipe", "рецепт", "food", "11_13"), ("schedule", "расписание", "time", "11_13"),
    ("science", "наука", "school", "11_13"), ("skill", "навык", "learning", "11_13"),
    ("sport", "спорт", "sports", "11_13"), ("story", "история", "stories", "11_13"),
    ("technology", "технология", "technology", "11_13"), ("theater", "театр", "culture", "11_13"),
    ("tradition", "традиция", "culture", "11_13"), ("training", "тренировка", "learning", "11_13"),
    ("trip", "поездка", "travel", "11_13"), ("volunteer", "волонтер", "society", "11_13"),

    # 14-18
    ("achievement", "достижение", "motivation", "14_18"), ("application", "заявка", "work", "14_18"),
    ("argument", "аргумент", "speaking", "14_18"), ("assignment", "задание", "study", "14_18"),
    ("audience", "аудитория", "speaking", "14_18"), ("balance", "баланс", "life", "14_18"),
    ("career", "карьера", "work", "14_18"), ("challenge", "вызов", "motivation", "14_18"),
    ("communication", "общение", "speaking", "14_18"), ("community", "сообщество", "society", "14_18"),
    ("competition", "соревнование", "school", "14_18"), ("confidence", "уверенность", "speaking", "14_18"),
    ("decision", "решение", "thinking", "14_18"), ("discussion", "обсуждение", "speaking", "14_18"),
    ("education", "образование", "study", "14_18"), ("effort", "усилие", "motivation", "14_18"),
    ("essay", "эссе", "writing", "14_18"), ("examination", "экзамен", "exams", "14_18"),
    ("explanation", "объяснение", "learning", "14_18"), ("feedback", "обратная связь", "learning", "14_18"),
    ("fluency", "беглость речи", "speaking", "14_18"), ("generation", "поколение", "society", "14_18"),
    ("goal", "цель", "motivation", "14_18"), ("grammar", "грамматика", "learning", "14_18"),
    ("impression", "впечатление", "speaking", "14_18"), ("independence", "самостоятельность", "life", "14_18"),
    ("internship", "стажировка", "work", "14_18"), ("knowledge", "знания", "learning", "14_18"),
    ("leadership", "лидерство", "work", "14_18"), ("lifestyle", "образ жизни", "life", "14_18"),
    ("opportunity", "возможность", "work", "14_18"), ("paragraph", "абзац", "writing", "14_18"),
    ("performance", "выступление", "speaking", "14_18"), ("priority", "приоритет", "life", "14_18"),
    ("progress", "прогресс", "learning", "14_18"), ("proposal", "предложение", "writing", "14_18"),
    ("purpose", "цель", "thinking", "14_18"), ("recommendation", "рекомендация", "work", "14_18"),
    ("relationship", "отношения", "friends", "14_18"), ("responsibility", "ответственность", "life", "14_18"),
    ("revision", "повторение", "study", "14_18"), ("scholarship", "стипендия", "study", "14_18"),
    ("solution", "решение", "thinking", "14_18"), ("strategy", "стратегия", "learning", "14_18"),
    ("summary", "краткое изложение", "writing", "14_18"), ("teamwork", "командная работа", "work", "14_18"),
    ("university", "университет", "study", "14_18"), ("vocabulary", "словарный запас", "learning", "14_18"),
    ("workshop", "мастер-класс", "learning", "14_18"), ("worldview", "мировоззрение", "thinking", "14_18"),
]


ADJECTIVES = [
    # 5-7
    ("big", "большой/ая/ое", "size", "5_7"), ("small", "маленький/ая/ое", "size", "5_7"),
    ("long", "длинный/ая/ое", "size", "5_7"), ("short", "короткий/ая/ое", "size", "5_7"),
    ("round", "круглый/ая/ое", "shape", "5_7"), ("soft", "мягкий/ая/ое", "touch", "5_7"),
    ("hard", "твердый/ая/ое", "touch", "5_7"), ("warm", "теплый/ая/ое", "weather", "5_7"),
    ("cold", "холодный/ая/ое", "weather", "5_7"), ("hot", "горячий/ая/ое", "weather", "5_7"),
    ("new", "новый/ая/ое", "basic", "5_7"), ("old", "старый/ая/ое", "basic", "5_7"),
    ("good", "хороший/ая/ее", "basic", "5_7"), ("nice", "милый/ая/ое", "feelings", "5_7"),
    ("funny", "смешной/ая/ое", "feelings", "5_7"), ("happy", "счастливый/ая/ое", "feelings", "5_7"),
    ("sad", "грустный/ая/ое", "feelings", "5_7"), ("fast", "быстрый/ая/ое", "movement", "5_7"),
    ("slow", "медленный/ая/ое", "movement", "5_7"), ("clean", "чистый/ая/ое", "home", "5_7"),
    ("dirty", "грязный/ая/ое", "home", "5_7"), ("bright", "яркий/ая/ое", "colors", "5_7"),
    ("dark", "темный/ая/ое", "colors", "5_7"), ("sweet", "сладкий/ая/ое", "food", "5_7"),
    ("little", "маленький/ая/ое", "size", "5_7"),

    # 8-10
    ("friendly", "дружелюбный/ая/ое", "people", "8_10"), ("busy", "занятый/ая/ое", "everyday", "8_10"),
    ("quiet", "тихий/ая/ое", "sound", "8_10"), ("loud", "громкий/ая/ое", "sound", "8_10"),
    ("easy", "легкий/ая/ое", "learning", "8_10"), ("difficult", "сложный/ая/ое", "learning", "8_10"),
    ("healthy", "здоровый/ая/ое", "health", "8_10"), ("tasty", "вкусный/ая/ое", "food", "8_10"),
    ("fresh", "свежий/ая/ое", "food", "8_10"), ("colorful", "разноцветный/ая/ое", "colors", "8_10"),
    ("careful", "осторожный/ая/ое", "behavior", "8_10"), ("brave", "смелый/ая/ое", "feelings", "8_10"),
    ("kind", "добрый/ая/ое", "people", "8_10"), ("polite", "вежливый/ая/ое", "people", "8_10"),
    ("ready", "готовый/ая/ое", "everyday", "8_10"), ("early", "ранний/яя/ее", "time", "8_10"),
    ("late", "поздний/яя/ее", "time", "8_10"), ("safe", "безопасный/ая/ое", "safety", "8_10"),
    ("strong", "сильный/ая/ое", "body", "8_10"), ("weak", "слабый/ая/ое", "body", "8_10"),
    ("clever", "умный/ая/ое", "learning", "8_10"), ("noisy", "шумный/ая/ое", "sound", "8_10"),
    ("hungry", "голодный/ая/ое", "food", "8_10"), ("thirsty", "хотящий пить", "food", "8_10"),
    ("comfortable", "удобный/ая/ое", "home", "8_10"),

    # 11-13
    ("active", "активный/ая/ое", "behavior", "11_13"), ("amazing", "удивительный/ая/ое", "feelings", "11_13"),
    ("creative", "творческий/ая/ое", "art", "11_13"), ("curious", "любознательный/ая/ое", "learning", "11_13"),
    ("different", "разный/ая/ое", "comparison", "11_13"), ("important", "важный/ая/ое", "learning", "11_13"),
    ("interesting", "интересный/ая/ое", "learning", "11_13"), ("modern", "современный/ая/ое", "technology", "11_13"),
    ("natural", "естественный/ая/ое", "nature", "11_13"), ("popular", "популярный/ая/ое", "culture", "11_13"),
    ("possible", "возможный/ая/ое", "thinking", "11_13"), ("regular", "регулярный/ая/ое", "time", "11_13"),
    ("simple", "простой/ая/ое", "learning", "11_13"), ("special", "особенный/ая/ое", "basic", "11_13"),
    ("successful", "успешный/ая/ое", "motivation", "11_13"), ("useful", "полезный/ая/ое", "learning", "11_13"),
    ("usual", "обычный/ая/ое", "everyday", "11_13"), ("careless", "невнимательный/ая/ое", "behavior", "11_13"),
    ("patient", "терпеливый/ая/ое", "people", "11_13"), ("peaceful", "спокойный/ая/ое", "feelings", "11_13"),
    ("powerful", "мощный/ая/ое", "science", "11_13"), ("practical", "практичный/ая/ое", "learning", "11_13"),
    ("private", "личный/ая/ое", "life", "11_13"), ("public", "общественный/ая/ое", "society", "11_13"),
    ("serious", "серьезный/ая/ое", "behavior", "11_13"),

    # 14-18
    ("accurate", "точный/ая/ое", "learning", "14_18"), ("ambitious", "амбициозный/ая/ое", "motivation", "14_18"),
    ("appropriate", "подходящий/ая/ее", "communication", "14_18"), ("available", "доступный/ая/ое", "work", "14_18"),
    ("clear", "ясный/ая/ое", "communication", "14_18"), ("complex", "сложный/ая/ое", "thinking", "14_18"),
    ("consistent", "последовательный/ая/ое", "learning", "14_18"), ("effective", "эффективный/ая/ое", "learning", "14_18"),
    ("efficient", "результативный/ая/ое", "work", "14_18"), ("emotional", "эмоциональный/ая/ое", "feelings", "14_18"),
    ("essential", "важнейший/ая/ее", "learning", "14_18"), ("formal", "официальный/ая/ое", "work", "14_18"),
    ("global", "глобальный/ая/ое", "society", "14_18"), ("independent", "самостоятельный/ая/ое", "life", "14_18"),
    ("logical", "логичный/ая/ое", "thinking", "14_18"), ("personal", "личный/ая/ое", "life", "14_18"),
    ("professional", "профессиональный/ая/ое", "work", "14_18"), ("reliable", "надежный/ая/ое", "work", "14_18"),
    ("responsible", "ответственный/ая/ое", "life", "14_18"), ("specific", "конкретный/ая/ое", "communication", "14_18"),
    ("strategic", "стратегический/ая/ое", "thinking", "14_18"), ("suitable", "подходящий/ая/ее", "communication", "14_18"),
    ("valuable", "ценный/ая/ое", "motivation", "14_18"), ("various", "различный/ая/ое", "comparison", "14_18"),
    ("well-organized", "хорошо организованный/ая/ое", "study", "14_18"),
]


VERBS = [
    # 5-7
    ("see", "видеть", "basic", "5_7"), ("find", "находить", "basic", "5_7"),
    ("like", "любить", "feelings", "5_7"), ("have", "иметь", "basic", "5_7"),
    ("draw", "рисовать", "art", "5_7"), ("hold", "держать", "movement", "5_7"),
    ("open", "открывать", "home", "5_7"), ("touch", "трогать", "movement", "5_7"),

    # 8-10
    ("choose", "выбирать", "learning", "8_10"), ("describe", "описывать", "speaking", "8_10"),
    ("carry", "нести", "movement", "8_10"), ("clean", "убирать", "home", "8_10"),
    ("visit", "посещать", "travel", "8_10"), ("use", "использовать", "technology", "8_10"),
    ("learn", "учить", "learning", "8_10"), ("remember", "помнить", "learning", "8_10"),

    # 11-13
    ("compare", "сравнивать", "learning", "11_13"), ("explain", "объяснять", "speaking", "11_13"),
    ("practice", "практиковать", "learning", "11_13"), ("prepare", "готовить", "study", "11_13"),
    ("create", "создавать", "art", "11_13"), ("discuss", "обсуждать", "speaking", "11_13"),
    ("explore", "исследовать", "science", "11_13"), ("improve", "улучшать", "learning", "11_13"),

    # 14-18
    ("analyze", "анализировать", "thinking", "14_18"), ("argue", "аргументировать", "speaking", "14_18"),
    ("evaluate", "оценивать", "thinking", "14_18"), ("organize", "организовывать", "work", "14_18"),
    ("present", "презентовать", "speaking", "14_18"), ("recommend", "рекомендовать", "communication", "14_18"),
    ("summarize", "кратко излагать", "writing", "14_18"), ("support", "поддерживать", "communication", "14_18"),
]


def _add(entries: list[Entry5], seen: set[str], item: Entry5) -> bool:
    word = item[0].strip().lower()
    if not word or word in seen:
        return False
    seen.add(word)
    entries.append((word, item[1], item[2], item[3], item[4]))
    return True


def _age_count(entries: list[Entry5], age_group: str) -> int:
    return sum(1 for item in entries if item[4] == age_group)


CONCRETE_NOUN_TOPICS = {
    "animals", "art", "body", "clothes", "family", "food", "friends",
    "games", "hobbies", "home", "jobs", "music", "nature", "places",
    "reading", "school", "sports", "technology", "toys", "transport", "travel",
}

PERSON_NOUN_TOPICS = {"family", "friends", "jobs"}

COUNTABLE_NOUN_TOPICS = CONCRETE_NOUN_TOPICS - {"body", "food"}

WITH_NOUN_TOPICS = COUNTABLE_NOUN_TOPICS - {
    "family", "friends", "jobs", "places", "transport", "travel",
}

FOR_NOUN_TOPICS = {
    "communication", "culture", "exams", "learning", "reading", "school",
    "science", "society", "speaking", "study", "technology", "time",
    "travel", "work", "writing",
}

UNCOUNTABLE_NOUNS = {
    "bread", "cheese", "juice", "milk", "rain",
    "breakfast", "dinner", "lunch", "football", "music",
    "biology", "chemistry", "culture", "education", "energy",
    "environment", "feedback", "fluency", "geography", "grammar",
    "history", "information", "knowledge", "leadership", "progress",
    "responsibility", "science", "technology", "teamwork", "training",
    "vocabulary",
}

ADJECTIVE_TOPIC_COMPATIBILITY = {
    "art": {"art", "hobbies", "music", "school", "study", "technology", "work"},
    "basic": set(NOUN_TOPIC for NOUN_TOPIC in {
        "animals", "art", "clothes", "communication", "culture", "everyday",
        "family", "food", "friends", "games", "hobbies", "home", "jobs",
        "learning", "life", "motivation", "music", "nature", "places",
        "reading", "school", "science", "society", "speaking", "sports",
        "stories", "study", "technology", "thinking", "time", "toys",
        "transport", "travel", "work", "writing",
    }),
    "behavior": PERSON_NOUN_TOPICS | {"school", "speaking", "communication", "work", "society", "life", "sports"},
    "body": {"body", "family", "friends", "sports"},
    "colors": CONCRETE_NOUN_TOPICS,
    "communication": {"communication", "speaking", "writing", "work", "study", "society", "learning"},
    "comparison": set(NOUN_TOPIC for NOUN_TOPIC in {
        "animals", "art", "clothes", "communication", "culture", "everyday",
        "exams", "family", "food", "friends", "games", "hobbies", "home",
        "jobs", "learning", "life", "motivation", "music", "nature",
        "places", "reading", "school", "science", "society", "speaking",
        "sports", "stories", "study", "technology", "thinking", "time",
        "toys", "transport", "travel", "work", "writing",
    }),
    "culture": {"culture", "society", "hobbies", "art", "stories", "music", "travel"},
    "everyday": {"everyday", "family", "friends", "school", "home", "life", "work", "travel", "places", "transport", "food"},
    "feelings": {"animals", "family", "friends", "jobs", "stories", "hobbies", "games", "culture", "speaking"},
    "food": {"food"},
    "health": {"body", "food", "sports", "life"},
    "home": {"home", "clothes", "body", "school", "places", "food"},
    "learning": {"learning", "school", "study", "exams", "reading", "writing", "speaking", "communication", "science", "technology", "work", "thinking", "culture", "stories", "hobbies"},
    "life": {"life", "family", "friends", "society", "work", "study", "motivation"},
    "motivation": {"motivation", "learning", "study", "work", "life", "school", "sports"},
    "movement": {"animals", "transport", "sports", "games", "travel"},
    "nature": {"nature", "food", "science", "places"},
    "people": PERSON_NOUN_TOPICS | {"school", "speaking", "communication", "work", "society"},
    "safety": {"places", "travel", "transport", "technology", "life", "home", "school", "sports"},
    "science": {"science", "technology", "learning", "school", "nature"},
    "shape": CONCRETE_NOUN_TOPICS,
    "size": CONCRETE_NOUN_TOPICS,
    "society": {"society", "culture", "communication", "work", "life"},
    "sound": {"animals", "home", "school", "places", "music", "culture", "everyday", "friends", "technology", "travel", "transport"},
    "study": {"study", "learning", "school", "exams", "writing", "reading"},
    "technology": {"technology", "work", "study", "communication", "society"},
    "thinking": {"thinking", "learning", "study", "work", "science", "communication", "writing", "speaking"},
    "time": {"time", "school", "everyday", "study", "work", "travel", "exams"},
    "touch": {"animals", "body", "clothes", "food", "home", "nature", "toys"},
    "weather": {"body", "clothes", "food", "home", "nature", "places", "travel"},
    "work": {"work", "study", "motivation", "life", "communication"},
}

ADJECTIVE_WORD_OVERRIDES = {
    "nice": ADJECTIVE_TOPIC_COMPATIBILITY["basic"],
    "amazing": ADJECTIVE_TOPIC_COMPATIBILITY["basic"],
    "special": ADJECTIVE_TOPIC_COMPATIBILITY["basic"],
    "good": ADJECTIVE_TOPIC_COMPATIBILITY["basic"],
    "friendly": PERSON_NOUN_TOPICS | {"animals", "school", "places", "travel"},
    "busy": {"places", "school", "home", "travel", "transport", "work", "everyday"},
    "quiet": ADJECTIVE_TOPIC_COMPATIBILITY["sound"],
    "loud": ADJECTIVE_TOPIC_COMPATIBILITY["sound"],
    "happy": PERSON_NOUN_TOPICS | {"animals", "stories"},
    "sad": PERSON_NOUN_TOPICS | {"animals", "stories"},
    "brave": PERSON_NOUN_TOPICS | {"animals", "stories"},
    "kind": PERSON_NOUN_TOPICS | {"animals", "school", "jobs"},
    "polite": PERSON_NOUN_TOPICS | {"school", "jobs"},
    "ready": PERSON_NOUN_TOPICS | {"school", "work", "study", "exams", "travel"},
    "early": {"time", "school", "everyday", "food", "travel", "transport", "study", "work"},
    "late": {"time", "school", "everyday", "food", "travel", "transport", "study", "work"},
    "hungry": PERSON_NOUN_TOPICS | {"animals"},
    "thirsty": PERSON_NOUN_TOPICS | {"animals"},
    "healthy": {"body", "food", "sports", "life"},
    "colorful": CONCRETE_NOUN_TOPICS | {"culture", "stories"},
    "careful": PERSON_NOUN_TOPICS | {"school", "work", "travel", "transport"},
    "safe": {"places", "travel", "transport", "technology", "life", "home", "school", "sports"},
    "strong": {"animals", "body", "family", "friends", "sports", "work", "motivation"},
    "weak": {"animals", "body", "family", "friends", "sports", "thinking"},
    "clever": PERSON_NOUN_TOPICS | {"animals", "school", "jobs"},
    "noisy": ADJECTIVE_TOPIC_COMPATIBILITY["sound"],
    "comfortable": {"home", "clothes", "transport", "places", "travel", "school"},
    "creative": {"art", "hobbies", "music", "school", "study", "work", "stories", "technology"},
    "curious": PERSON_NOUN_TOPICS | {"animals", "school", "science", "learning"},
    "important": ADJECTIVE_TOPIC_COMPATIBILITY["learning"] | {"life", "motivation", "society"},
    "interesting": ADJECTIVE_TOPIC_COMPATIBILITY["learning"] | {"travel", "culture", "stories", "hobbies", "music", "sports"},
    "modern": {"technology", "work", "study", "school", "culture", "society", "communication"},
    "natural": {"nature", "food", "science", "life"},
    "popular": {"culture", "hobbies", "music", "sports", "technology", "travel", "food", "school", "society"},
    "possible": {"thinking", "learning", "life", "work", "study", "motivation"},
    "regular": {"time", "study", "school", "sports", "learning", "work"},
    "simple": ADJECTIVE_TOPIC_COMPATIBILITY["learning"] | {"work", "life", "technology"},
    "successful": {"motivation", "work", "study", "sports", "school", "life"},
    "useful": ADJECTIVE_TOPIC_COMPATIBILITY["learning"] | {"work", "life", "technology", "travel"},
    "usual": {"everyday", "school", "home", "time", "study", "work", "travel"},
    "careless": PERSON_NOUN_TOPICS | {"school", "work", "study"},
    "patient": PERSON_NOUN_TOPICS | {"school", "jobs", "work"},
    "peaceful": {"nature", "places", "culture", "life", "society", "stories"},
    "powerful": {"science", "technology", "nature", "work", "motivation"},
    "practical": ADJECTIVE_TOPIC_COMPATIBILITY["learning"] | {"work", "life", "technology"},
    "professional": {"work", "communication", "speaking", "writing"},
}

VERB_OBJECT_COMPATIBILITY = {
    "analyze": {"thinking", "science", "school", "work", "writing", "learning", "information"},
    "argue": set(),
    "carry": CONCRETE_NOUN_TOPICS - {"places", "nature", "body"},
    "choose": {"animals", "art", "clothes", "everyday", "food", "games", "hobbies", "music", "places", "school", "sports", "technology", "toys", "transport", "travel", "work"},
    "clean": {"home", "clothes", "body", "school", "places"},
    "compare": {"animals", "art", "clothes", "communication", "culture", "exams", "food", "games", "hobbies", "learning", "music", "reading", "school", "science", "speaking", "sports", "stories", "study", "technology", "thinking", "travel", "work", "writing"},
    "create": {"art", "hobbies", "school", "stories", "study", "technology", "work", "writing", "communication"},
    "describe": {"animals", "art", "clothes", "culture", "family", "food", "friends", "hobbies", "home", "music", "nature", "places", "school", "science", "sports", "stories", "technology", "travel"},
    "discuss": {"communication", "culture", "everyday", "learning", "life", "motivation", "science", "society", "speaking", "study", "technology", "thinking", "travel", "work"},
    "draw": {"animals", "art", "body", "family", "food", "friends", "home", "nature", "places", "toys", "transport"},
    "evaluate": {"thinking", "work", "study", "learning", "speaking", "writing", "science"},
    "explain": {"communication", "learning", "school", "science", "speaking", "study", "technology", "thinking", "writing"},
    "explore": {"culture", "nature", "places", "science", "technology", "travel"},
    "find": set(NOUN_TOPIC for NOUN_TOPIC in {
        "animals", "art", "clothes", "communication", "culture", "everyday",
        "family", "food", "friends", "games", "hobbies", "home", "learning",
        "life", "music", "nature", "places", "reading", "school", "science",
        "speaking", "sports", "stories", "study", "technology", "thinking",
        "time", "toys", "transport", "travel", "work", "writing",
    }),
    "have": {"animals", "clothes", "communication", "everyday", "family", "food", "friends", "games", "hobbies", "home", "learning", "life", "motivation", "school", "sports", "study", "technology", "time", "toys", "transport", "travel", "work"},
    "hold": CONCRETE_NOUN_TOPICS - {"places", "nature"},
    "improve": {"communication", "learning", "life", "motivation", "school", "speaking", "sports", "study", "work", "writing"},
    "learn": {"communication", "culture", "learning", "reading", "school", "science", "speaking", "study", "technology", "writing"},
    "like": ADJECTIVE_TOPIC_COMPATIBILITY["basic"],
    "open": {"home", "school", "technology", "reading", "communication", "places"},
    "organize": {"communication", "everyday", "events", "life", "school", "study", "work", "writing"},
    "practice": {"learning", "music", "speaking", "sports", "study", "writing"},
    "prepare": {"exams", "food", "school", "speaking", "study", "travel", "work", "writing"},
    "present": {"communication", "speaking", "study", "work", "writing"},
    "recommend": {"art", "communication", "culture", "food", "hobbies", "learning", "places", "reading", "school", "technology", "travel", "work"},
    "remember": {"communication", "culture", "everyday", "family", "friends", "learning", "school", "stories", "study", "time"},
    "see": CONCRETE_NOUN_TOPICS | {"culture", "society"},
    "summarize": {"communication", "reading", "school", "speaking", "study", "work", "writing"},
    "support": {"communication", "family", "friends", "learning", "life", "motivation", "society", "speaking", "work"},
    "touch": {"animals", "body", "clothes", "food", "home", "nature", "toys"},
    "use": {"communication", "home", "learning", "school", "study", "technology", "work", "writing"},
    "visit": {"family", "friends", "places", "school", "travel", "culture"},
}

MODIFIER_COMPATIBILITY = {
    "my": ADJECTIVE_TOPIC_COMPATIBILITY["basic"] | {"body", "exams"},
    "your": ADJECTIVE_TOPIC_COMPATIBILITY["basic"] | {"body", "exams"},
    "this": ADJECTIVE_TOPIC_COMPATIBILITY["basic"] | {"body", "exams"},
    "that": ADJECTIVE_TOPIC_COMPATIBILITY["basic"] | {"body", "exams"},
    "the": set(NOUN_TOPIC for NOUN_TOPIC in {
        "animals", "art", "body", "clothes", "communication", "culture",
        "everyday", "exams", "family", "food", "friends", "games",
        "hobbies", "home", "jobs", "learning", "life", "motivation",
        "music", "nature", "places", "reading", "school", "science",
        "society", "speaking", "sports", "stories", "study", "technology",
        "thinking", "time", "toys", "transport", "travel", "work", "writing",
    }),
    "a": COUNTABLE_NOUN_TOPICS,
    "one": COUNTABLE_NOUN_TOPICS,
    "two": set(),
    "favorite": {"animals", "art", "clothes", "culture", "food", "friends", "games", "hobbies", "music", "places", "reading", "school", "sports", "stories", "technology", "toys", "travel"},
    "next": {"communication", "everyday", "exams", "learning", "reading", "school", "speaking", "study", "time", "travel", "work", "writing"},
    "first": {"communication", "everyday", "exams", "learning", "reading", "school", "speaking", "study", "time", "travel", "work", "writing"},
    "last": {"communication", "everyday", "exams", "learning", "reading", "school", "speaking", "study", "time", "travel", "work", "writing"},
}


def _compatible_adjective_phrase(adjective: str, adjective_topic: str, noun_topic: str) -> bool:
    allowed_topics = ADJECTIVE_WORD_OVERRIDES.get(
        adjective,
        ADJECTIVE_TOPIC_COMPATIBILITY.get(adjective_topic, set()),
    )
    return noun_topic in allowed_topics


def _compatible_verb_phrase(verb: str, noun_topic: str) -> bool:
    allowed_topics = VERB_OBJECT_COMPATIBILITY.get(verb, set())
    return noun_topic in allowed_topics


def _compatible_modifier_phrase(modifier: str, noun_topic: str) -> bool:
    allowed_topics = MODIFIER_COMPATIBILITY.get(modifier, set())
    return noun_topic in allowed_topics


def _article_for(noun: str) -> str:
    if noun.startswith(("uni", "use", "user")):
        return "a"
    return "an" if noun[:1] in {"a", "e", "i", "o", "u"} else "a"


def _needs_article(noun: str, noun_topic: str) -> bool:
    return noun_topic in COUNTABLE_NOUN_TOPICS and noun not in UNCOUNTABLE_NOUNS


def _article_phrase(noun: str, noun_topic: str) -> str:
    return f"{_article_for(noun)} {noun}" if _needs_article(noun, noun_topic) else noun


def _verb_object_phrase(verb: str, noun: str, noun_topic: str) -> str:
    if verb in {"learn", "practice"} and noun_topic in {
        "learning", "music", "school", "speaking", "sports", "study", "writing",
    }:
        return noun
    return _article_phrase(noun, noun_topic)


def _add_base_words(entries: list[Entry5], seen: set[str]) -> None:
    for word, translation, example, topic, age_group in CORE_WORDS:
        _add(entries, seen, (word, translation, example, topic, age_group))

    for word, translation, topic, age_group in NOUNS:
        _add(entries, seen, (word, translation, f"I know the word {word}.", topic, age_group))
    for word, translation, topic, age_group in ADJECTIVES:
        _add(entries, seen, (word, translation, f"This word is {word}.", topic, age_group))
    for word, translation, topic, age_group in VERBS:
        _add(entries, seen, (word, translation, f"I can {word}.", topic, age_group))


def _fill_age_group(entries: list[Entry5], seen: set[str], age_group: str) -> None:
    target = TARGET_PER_AGE_GROUP[age_group]
    nouns = [item for item in NOUNS if item[3] == age_group]
    adjectives = [item for item in ADJECTIVES if item[3] == age_group]
    verbs = [item for item in VERBS if item[3] == age_group]

    modifiers = [
        ("my", "мой/моя/мое"),
        ("your", "твой/твоя/твое"),
        ("this", "этот/эта/это"),
        ("that", "тот/та/то"),
        ("the", "определенный артикль"),
        ("a", "неопределенный артикль"),
        ("one", "один/одна/одно"),
        ("two", "два/две"),
        ("favorite", "любимый/ая/ое"),
        ("next", "следующий/ая/ее"),
        ("first", "первый/ая/ое"),
        ("last", "последний/яя/ее"),
    ]

    generators = [
        (
            f"{adj} {noun}",
            f"{noun_ru} ({adj_ru})",
            f"The phrase is: {adj} {noun}.",
            noun_topic,
            age_group,
        )
        for adj, adj_ru, adj_topic, _adj_age in adjectives
        for noun, noun_ru, noun_topic, _noun_age in nouns
        if _compatible_adjective_phrase(adj, adj_topic, noun_topic)
    ]
    generators.extend(
        (
            f"{verb} {_verb_object_phrase(verb, noun, noun_topic)}",
            f"{verb_ru}: {noun_ru}",
            f"Practice phrase: {verb} {_verb_object_phrase(verb, noun, noun_topic)}.",
            noun_topic,
            age_group,
        )
        for verb, verb_ru, _verb_topic, _verb_age in verbs
        for noun, noun_ru, noun_topic, _noun_age in nouns
        if _compatible_verb_phrase(verb, noun_topic)
    )
    generators.extend(
        (
            f"{_article_for(noun) if mod == 'a' else mod} {noun}",
            f"{mod_ru}: {noun_ru}",
            f"This is {_article_for(noun) if mod == 'a' else mod} {noun}.",
            noun_topic,
            age_group,
        )
        for mod, mod_ru in modifiers
        for noun, noun_ru, noun_topic, _noun_age in nouns
        if _compatible_modifier_phrase(mod, noun_topic)
        and (mod not in {"a", "one"} or _needs_article(noun, noun_topic))
    )
    generators.extend(
        (
            f"about {_article_phrase(noun, noun_topic)}",
            f"о/об: {noun_ru}",
            f"Let's talk about {_article_phrase(noun, noun_topic)}.",
            noun_topic,
            age_group,
        )
        for noun, noun_ru, noun_topic, _noun_age in nouns
    )
    generators.extend(
        (
            f"with {_article_for(noun)} {noun}",
            f"с: {noun_ru}",
            f"I can say a phrase with {_article_for(noun)} {noun}.",
            noun_topic,
            age_group,
        )
        for noun, noun_ru, noun_topic, _noun_age in nouns
        if noun_topic in WITH_NOUN_TOPICS and _needs_article(noun, noun_topic)
    )
    generators.extend(
        (
            f"for {_article_phrase(noun, noun_topic)}",
            f"для: {noun_ru}",
            f"This phrase is for {_article_phrase(noun, noun_topic)}.",
            noun_topic,
            age_group,
        )
        for noun, noun_ru, noun_topic, _noun_age in nouns
        if noun_topic in FOR_NOUN_TOPICS
    )

    for item in generators:
        if _age_count(entries, age_group) >= target:
            break
        _add(entries, seen, item)

    if _age_count(entries, age_group) < target:
        raise RuntimeError(f"Not enough generated words for {age_group}")


def _build_base_words() -> list[Entry5]:
    entries: list[Entry5] = []
    seen: set[str] = set()
    _add_base_words(entries, seen)
    for age_group in TARGET_PER_AGE_GROUP:
        _fill_age_group(entries, seen, age_group)

    by_age = Counter(item[4] for item in entries)
    if len(entries) != TARGET_WORD_COUNT:
        raise RuntimeError(f"Expected {TARGET_WORD_COUNT} words, got {len(entries)}")
    if len(seen) != TARGET_WORD_COUNT:
        raise RuntimeError("Generated word list contains duplicates")
    for age_group, expected in TARGET_PER_AGE_GROUP.items():
        if by_age[age_group] != expected:
            raise RuntimeError(f"Expected {expected} words for {age_group}, got {by_age[age_group]}")
    return entries


def _with_transcriptions(entries: list[Entry5]) -> list[Entry6]:
    return [
        (word, translation, example, topic, age_group, _transcription(word))
        for word, translation, example, topic, age_group in entries
    ]


INITIAL_WORDS = _with_transcriptions(_build_base_words())
