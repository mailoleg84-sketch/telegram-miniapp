"""Deterministic learning-scene metadata for vocabulary cards.

The image is intentionally treated as one part of the explanation. Complex
words receive a contextual scene, a lower confidence score, and a review flag.
"""
from __future__ import annotations

from urllib.parse import urlencode


VISUAL_TYPES = {
    "object",
    "action",
    "contrast",
    "emotion",
    "spatial_relation",
    "situation",
    "cause_effect",
    "two_panel_comic",
    "grammar_diagram",
    "no_good_visual",
}
COMPLEX_VISUAL_TYPES = {
    "situation",
    "cause_effect",
    "two_panel_comic",
    "grammar_diagram",
    "no_good_visual",
}

BASE_IMAGE_STYLE = (
    "premium friendly educational illustration, soft 3D/cartoon style, "
    "clean light background, warm colors, clear subject, child-safe, modern "
    "EdTech look, suitable for children and teenagers, no text, no letters, "
    "no labels, no logo, no watermark"
)

OBJECT_WORDS = {
    "apple", "dog", "car", "chair", "ball", "cat", "book", "bus", "cake",
    "camera", "computer", "cup", "flower", "guitar", "house", "moon", "pencil",
    "plane", "robot", "school", "sun", "table", "teacher", "train", "tree",
}
COMMON_CONCRETE_NOUNS = {
    "arrow", "baby", "bag", "beans", "bed", "bike", "body", "boy", "brother",
    "building", "cabin", "cage", "cap", "caps", "child", "children", "city",
    "cloud", "clouds", "clothes", "coat", "couch", "customer", "dad", "daughter",
    "doctor", "eagle", "eye", "face", "family", "farm", "farms", "father",
    "fire", "fires", "friend", "girl", "grandma", "grandpa", "hand", "hat",
    "home", "horn", "jam", "lake", "lakes", "lamp", "leaf", "leg", "lens",
    "lip", "man", "men", "mom", "mother", "nurse", "nurses", "office",
    "partner", "people", "person", "photograph", "room", "school", "sheet",
    "sheets", "sister", "son", "sons", "stairs", "student", "teacher",
    "teeth", "teen", "teens", "tooth", "wallet", "woman", "women", "zoo",
}
ACTION_WORDS = {
    "run", "jump", "eat", "sleep", "read", "swim", "walk", "write", "draw",
    "play", "open", "carry", "choose", "clean", "create", "dance", "drink",
    "help", "listen", "look", "sing", "sit", "stand", "study", "visit",
}
CONTRAST_WORDS = {
    "big", "small", "hot", "cold", "clean", "dirty", "fast", "slow", "long",
    "short", "old", "new", "hard", "soft", "heavy", "light", "tall", "tiny",
}
EMOTION_WORDS = {
    "happy", "sad", "angry", "scared", "surprised", "tired", "excited",
    "bored", "afraid", "calm", "nervous",
}
SPATIAL_WORDS = {
    "in", "on", "under", "behind", "between", "above", "below", "inside",
    "outside", "near", "beside",
}
SITUATION_WORDS = {
    "brave", "kind", "honest", "careful", "lazy", "proud", "worried",
    "polite", "helpful", "friendly", "responsible", "patient", "confident",
    "careless", "generous", "shy", "unfair", "vulnerable", "urgent",
}
CAUSE_EFFECT_WORDS = {"because", "so", "therefore", "reason", "result"}
TWO_PANEL_WORDS = {"although", "but", "however", "before", "after", "while", "already", "yet"}
MODAL_WORDS = {"should", "must", "can", "could", "would", "might", "have"}
NO_GOOD_VISUAL_WORDS = {
    "the", "a", "an", "to", "of", "very", "really", "just", "usually",
    "always", "often", "sometimes", "never",
    # Служебные/местоимения/сравнительные/временные слова — у них нет осмысленной
    # единственной картинки. Раньше часть из них (топик "people") ошибочно
    # получала тип object → фото слова вроде "for"/"better". Внимание: НЕ трогаем
    # настоящие "-er"-существительные (paper, door, letter, monster, shower …).
    # местоимения и определители
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
    "them", "my", "your", "his", "its", "our", "their", "mine", "yours",
    "hers", "ours", "theirs", "this", "that", "these", "those",
    "who", "whom", "whose", "which", "what",
    # союзы / предлоги / частицы
    "for", "or", "nor", "as", "than", "then", "with", "from", "by", "at",
    "about", "again", "ever", "here", "there", "der",
    # количественные / сравнительные
    "more", "most", "less", "least", "much", "many", "few", "fewer",
    "better", "best", "worse", "worst", "later", "earlier",
    "faster", "slower", "lower", "higher", "lot", "lots",
    # дни и месяцы (нет смысловой одиночной картинки)
    "today", "tomorrow", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "april", "june", "july", "august",
    "september", "october", "november", "december",
}
CONCRETE_TOPICS = {
    "animals", "art", "body", "clothes", "family", "food", "friends",
    "games", "hobbies", "home", "jobs", "music", "nature", "places",
    "reading", "school", "sports", "technology", "toys", "transport",
    "travel", "people",
}
AMBIGUOUS_NOUNS = {
    "advice", "amount", "balance", "blow", "case", "change", "choice",
    "deal", "effect", "effort", "event", "fact", "idea", "issue",
    "matter", "mind", "opinion", "options", "point", "problem", "purpose",
    "reason", "result", "solution", "thought", "truth", "witness",
}
SENSITIVE_WORDS = {
    "fuck", "shit", "piss", "torture", "theft", "scandal", "nightmare",
    "propaganda", "criminals",
}

FUNCTION_WORD_POS = {
    "although": "conjunction",
    "but": "conjunction",
    "however": "conjunction",
    "because": "conjunction",
    "so": "conjunction",
    "therefore": "adverb",
    "before": "preposition",
    "after": "preposition",
    "while": "conjunction",
    "already": "adverb",
    "yet": "adverb",
    "usually": "adverb",
    "always": "adverb",
    "often": "adverb",
    "sometimes": "adverb",
    "never": "adverb",
    "in": "preposition",
    "on": "preposition",
    "under": "preposition",
    "behind": "preposition",
    "between": "preposition",
    "above": "preposition",
    "below": "preposition",
    "inside": "preposition",
    "outside": "preposition",
    "near": "preposition",
    "beside": "preposition",
    "the": "article",
    "a": "article",
    "an": "article",
    "to": "particle",
    "of": "preposition",
}

EXAMPLES = {
    "apple": "I have an apple.",
    "dog": "The dog is friendly.",
    "car": "The car is blue.",
    "chair": "The book is on the chair.",
    "ball": "I have a red ball.",
    "run": "I can run fast.",
    "jump": "The child can jump.",
    "eat": "I eat an apple.",
    "sleep": "The cat is sleeping.",
    "read": "I read a book.",
    "swim": "I can swim.",
    "big": "The elephant is big.",
    "small": "The mouse is small.",
    "hot": "The soup is hot.",
    "cold": "The ice is cold.",
    "clean": "The room is clean.",
    "dirty": "The shoes are dirty.",
    "happy": "She is happy.",
    "sad": "He is sad.",
    "angry": "She is angry.",
    "scared": "He is scared.",
    "tired": "She is tired.",
    "in": "The ball is in the box.",
    "on": "The ball is on the box.",
    "under": "The ball is under the box.",
    "behind": "The ball is behind the box.",
    "between": "The ball is between the boxes.",
    "brave": "She is brave.",
    "kind": "He is kind to his friend.",
    "honest": "He is honest.",
    "careful": "He is careful.",
    "proud": "She is proud of her drawing.",
    "worried": "He is worried about the bus.",
    "although": "Although it is raining, he is happy.",
    "however": "It is raining. However, she goes outside.",
    "because": "He is wet because it is raining.",
    "should": "You should wear a helmet.",
    "must": "You must stop at the red light.",
    "would": "I would like some water.",
    "already": "She has already finished her homework.",
    "yet": "He has not finished yet.",
    "usually": "I usually get up at seven.",
}

SIMPLE_MEANINGS = {
    "apple": "An apple is a fruit.",
    "run": "To run means to move quickly on your feet.",
    "brave": "She is scared, but she does it.",
    "kind": "He helps someone and cares about them.",
    "honest": "He tells the truth and returns what is not his.",
    "careful": "He does something slowly and safely.",
    "careless": "He does something too fast and makes a mistake.",
    "confident": "He believes he can do it.",
    "generous": "She happily shares with other people.",
    "helpful": "She helps someone do something.",
    "lazy": "He does not want to do the work.",
    "patient": "He waits calmly.",
    "polite": "She uses kind words and good manners.",
    "proud": "She feels happy about something she did.",
    "responsible": "She takes care of her task.",
    "shy": "He feels quiet and unsure around people.",
    "unfair": "One person gets a worse deal than another.",
    "urgent": "It needs to be done soon.",
    "vulnerable": "Someone can be hurt or needs extra care.",
    "worried": "He thinks something may go wrong.",
    "although": "Something happens, but the result is different from what we expect.",
    "however": "This word introduces a different or surprising idea.",
    "because": "This word explains the reason.",
    "should": "It is a good idea to do this.",
    "must": "This is necessary or a rule.",
    "would": "This helps make a wish or polite request.",
    "already": "It happened earlier than now or expected.",
    "yet": "It has not happened up to now.",
    "usually": "It happens most of the time.",
}

RUSSIAN_HINTS = {
    "apple": "Яблоко — это фрукт.",
    "run": "Бежать — быстро двигаться ногами.",
    "brave": "Ей страшно, но она всё равно делает.",
    "kind": "Он помогает другому человеку.",
    "honest": "Он говорит правду и возвращает чужую вещь.",
    "careful": "Он делает это аккуратно и безопасно.",
    "careless": "Он делает слишком быстро и ошибается.",
    "confident": "Он верит, что справится.",
    "generous": "Она с радостью делится с другими.",
    "helpful": "Она помогает другому человеку.",
    "lazy": "Он не хочет делать работу.",
    "patient": "Он спокойно ждёт.",
    "polite": "Она говорит вежливо и ведёт себя уважительно.",
    "proud": "Она рада тому, что сделала сама.",
    "responsible": "Она отвечает за своё дело.",
    "shy": "Он стесняется рядом с людьми.",
    "unfair": "К одному человеку относятся хуже, чем к другому.",
    "urgent": "Это нужно сделать скоро.",
    "vulnerable": "Человека легко задеть, ему нужна забота.",
    "worried": "Он переживает, что что-то может случиться.",
    "although": "Хотя идёт дождь, он счастлив.",
    "however": "Слово показывает другую или неожиданную мысль.",
    "because": "Это слово объясняет причину.",
    "should": "Тебе стоит надеть шлем.",
    "must": "Это обязательно или так требует правило.",
    "would": "Помогает вежливо попросить или сказать о желании.",
    "already": "Это уже произошло.",
    "yet": "Это ещё не произошло.",
    "usually": "Так происходит обычно, большую часть времени.",
}

SCENE_PROMPTS = {
    "brave": "A child who looks a little scared but calmly enters a dim safe room with a flashlight, showing courage through action",
    "kind": "A child helping a friend pick up dropped school books, showing kindness",
    "honest": "A child giving a lost wallet back to a teacher, showing honesty",
    "careful": "A child carefully carrying a full glass of water without spilling it, focused expression",
    "careless": "A child rushing with an open backpack while pencils safely spill onto a desk, showing a careless action",
    "confident": "A child calmly raising a hand in class with a relaxed smile, ready to answer",
    "generous": "A child happily sharing colored pencils with classmates",
    "helpful": "A child helping another child tie a shoelace before a game",
    "patient": "A child waiting calmly in a line while others go first",
    "polite": "A child holding a door open and smiling respectfully",
    "proud": "A child happily showing a finished drawing to a parent, showing healthy pride",
    "responsible": "A child watering a classroom plant and checking a small task list without any written text",
    "shy": "A child standing near a friendly group with a gentle quiet expression, safe and supportive mood",
    "unfair": "Two children receiving clearly unequal piles of toy blocks, showing an unfair situation without conflict",
    "urgent": "A child quickly but safely putting on a backpack while a clock-like shape suggests time is short",
    "vulnerable": "A younger child being gently protected with an umbrella in light rain, showing need for care",
    "worried": "A child looking at a clock while waiting safely at a bus stop, worried expression",
    "lazy": "A child resting on a sofa while a school bag and tidy task wait nearby",
}


# Бесплатные «картинки» для конкретных слов: нативные цветные эмодзи (рендерятся
# системным шрифтом на всех платформах, без внешних запросов и без оплаты).
# Абстрактные/грамматические слова сюда не входят — для них остаётся SVG-сцена.
WORD_EMOJI = {
    # предметы и объекты
    "apple": "🍎", "dog": "🐶", "car": "🚗", "ball": "⚽", "cat": "🐱",
    "book": "📖", "bus": "🚌", "cake": "🍰", "camera": "📷", "computer": "💻",
    "cup": "🍵", "flower": "🌸", "guitar": "🎸", "house": "🏠", "moon": "🌙",
    "pencil": "✏️", "plane": "✈️", "robot": "🤖", "school": "🏫", "sun": "☀️",
    "teacher": "🧑‍🏫", "train": "🚆", "tree": "🌳", "chair": "🪑",
    # люди и тело
    "baby": "👶", "boy": "👦", "girl": "👧", "brother": "👦", "sister": "👧",
    "child": "🧒", "children": "🧒", "dad": "👨", "father": "👨", "daughter": "👧",
    "son": "👦", "mom": "👩", "mother": "👩", "man": "👨", "woman": "👩",
    "men": "👨", "women": "👩", "grandma": "👵", "grandpa": "👴", "people": "👥",
    "person": "🧍", "family": "👨‍👩‍👧‍👦", "friend": "🧑‍🤝‍🧑", "doctor": "🧑‍⚕️",
    "nurse": "🧑‍⚕️", "student": "🧑‍🎓", "eye": "👁️", "face": "🙂", "hand": "✋",
    "leg": "🦵", "tooth": "🦷", "teeth": "🦷",
    # вещи и места
    "bag": "🎒", "bed": "🛏️", "bike": "🚲", "building": "🏢", "cap": "🧢",
    "city": "🏙️", "cloud": "☁️", "clouds": "☁️", "clothes": "👕", "coat": "🧥",
    "couch": "🛋️", "farm": "🚜", "fire": "🔥", "hat": "🎩", "home": "🏠",
    "lamp": "💡", "leaf": "🍃", "office": "🏢", "stairs": "🪜", "wallet": "👛",
    "zoo": "🦁", "lake": "🏞️", "star": "⭐", "phone": "📱", "key": "🔑",
    "clock": "🕐", "gift": "🎁", "umbrella": "☂️", "ship": "🚢", "boat": "⛵",
    "rocket": "🚀", "balloon": "🎈", "drum": "🥁", "piano": "🎹",
    # действия
    "run": "🏃", "jump": "🤸", "eat": "🍽️", "sleep": "😴", "read": "📖",
    "swim": "🏊", "walk": "🚶", "write": "✍️", "draw": "🎨", "play": "🎮",
    "carry": "🛍️", "clean": "🧹", "dance": "💃", "drink": "🥤", "help": "🤝",
    "listen": "👂", "look": "👀", "sing": "🎤", "sit": "🪑", "stand": "🧍",
    "study": "📚", "cook": "🍳", "paint": "🎨", "ride": "🚴", "fly": "🛫",
    # эмоции
    "happy": "😀", "sad": "😢", "angry": "😠", "scared": "😨", "surprised": "😲",
    "tired": "😴", "excited": "🤩", "bored": "😑", "afraid": "😨", "calm": "😌",
    "nervous": "😰", "love": "❤️", "cry": "😭", "laugh": "😂",
    # еда
    "banana": "🍌", "orange": "🍊", "grapes": "🍇", "pizza": "🍕", "bread": "🍞",
    "egg": "🥚", "milk": "🥛", "water": "💧", "rice": "🍚", "fish": "🐟",
    "meat": "🍖", "chicken": "🍗", "cheese": "🧀", "ice cream": "🍦", "candy": "🍬",
    "cookie": "🍪", "soup": "🍲", "tea": "🍵", "coffee": "☕", "juice": "🧃",
    "carrot": "🥕", "tomato": "🍅", "potato": "🥔", "corn": "🌽", "lemon": "🍋",
    "strawberry": "🍓", "watermelon": "🍉", "honey": "🍯", "salad": "🥗",
    # животные
    "bird": "🐦", "cow": "🐄", "horse": "🐴", "pig": "🐷", "sheep": "🐑",
    "rabbit": "🐰", "bear": "🐻", "lion": "🦁", "tiger": "🐯", "elephant": "🐘",
    "monkey": "🐵", "mouse": "🐭", "duck": "🦆", "frog": "🐸", "snake": "🐍",
    "bee": "🐝", "butterfly": "🦋", "spider": "🕷️", "eagle": "🦅", "owl": "🦉",
    "penguin": "🐧", "dolphin": "🐬", "whale": "🐳", "shark": "🦈", "turtle": "🐢",
    "fox": "🦊", "wolf": "🐺", "deer": "🦌", "panda": "🐼", "koala": "🐨",
    # природа и погода
    "rain": "🌧️", "snow": "❄️", "wind": "🌬️", "rainbow": "🌈", "mountain": "⛰️",
    "sea": "🌊", "river": "🏞️", "beach": "🏖️", "park": "🏞️", "forest": "🌲",
    "grass": "🌿", "rose": "🌹", "leaves": "🍂",
    # транспорт
    "truck": "🚚", "taxi": "🚕", "bicycle": "🚲", "helicopter": "🚁", "subway": "🚇",
    # спорт и музыка
    "football": "⚽", "basketball": "🏀", "tennis": "🎾", "music": "🎵", "song": "🎶",
    # — расширение покрытия под банк 5000: конкретные слова, ранее уходившие
    #   в фото-лотерею; эмодзи всегда «по смыслу», без сети и без оплаты —
    # тело
    "arm": "💪", "ear": "👂", "finger": "☝️", "foot": "🦶", "knee": "🦵",
    "mouth": "👄", "nose": "👃", "heart": "❤️",
    # школа
    "backpack": "🎒", "pen": "🖊️", "marker": "🖍️", "ruler": "📏",
    "calculator": "🧮", "dictionary": "📖", "folder": "📁", "library": "📚",
    "notebook": "📓", "page": "📄", "math": "🔢", "science": "🔬",
    "chemistry": "🧪", "biology": "🧬", "geography": "🗺️", "history": "📜",
    # еда
    "grape": "🍇", "fruit": "🍎", "cupcake": "🧁", "apricot": "🍑",
    "breakfast": "🍳", "lunch": "🍱", "dinner": "🍽️", "restaurant": "🍴",
    # дом
    "spoon": "🥄", "fork": "🍴", "plate": "🍽️", "basket": "🧺",
    "bottle": "🍾", "candle": "🕯️", "window": "🪟", "bedroom": "🛏️",
    "bookshelf": "📚",
    # природа
    "earth": "🌍", "ocean": "🌊", "garden": "🌷", "sunflower": "🌻",
    "seashell": "🐚", "sky": "🌤️", "meadow": "🌾",
    # технологии
    "screen": "🖥️", "email": "📧", "headphones": "🎧", "video": "📹",
    "app": "📱", "internet": "🌐",
    # путешествия / места
    "hotel": "🏨", "map": "🗺️", "road": "🛣️", "airport": "🛫",
    "ticket": "🎫", "compass": "🧭", "station": "🚉", "camp": "⛺",
    "lantern": "🏮", "trip": "🧳", "postcard": "📮", "hospital": "🏥",
    "market": "🏪", "museum": "🏛️", "village": "🏘️",
    # семья и роли (агентивные существительные)
    "aunt": "👩", "uncle": "👨", "cousin": "🧑", "parent": "👪",
    "actor": "🎭", "baker": "🧑‍🍳", "farmer": "🧑‍🌾", "runner": "🏃",
    "walker": "🚶", "reader": "📖", "singer": "🎤", "dancer": "💃",
    "painter": "🧑‍🎨", "pilot": "🧑‍✈️", "writer": "✍️",
    # животные
    "goat": "🐐", "kitten": "🐱", "puppy": "🐶",
    # игры / спорт / хобби / искусство / чтение
    "scooter": "🛴", "skateboard": "🛹", "race": "🏁", "box": "📦",
    "kite": "🪁", "game": "🎮", "puzzle": "🧩", "crayon": "🖍️",
    "picture": "🖼️", "bookmark": "🔖", "magazine": "📰", "novel": "📖",
    "flute": "🪈",
    # одежда
    "shoe": "👟", "shoes": "👟", "dress": "👗",
    # прочее
    "arrow": "➡️", "beans": "🫘", "cabin": "🛖", "horn": "📯",
    "photograph": "🖼️", "lip": "👄",
    # — расширение под 11–18 (image-тип был почти мёртв) + кросс-возрастные
    #   пропуски конкретных слов, найденные тем же проходом. Каждый эмодзи сверен
    #   с переводом из банка; глифы различимы (без коллизий с существующими) —
    # роли/профессии (различимый глиф)
    "officer": "👮", "detective": "🕵️", "scientist": "🧑‍🔬", "engineer": "👷",
    "developer": "🧑‍💻", "king": "🤴", "queen": "👸",
    # объекты / техника / учёба
    "newspaper": "🗞️", "calendar": "📅", "telescope": "🔭", "microscope": "🔬",
    "satellite": "🛰️", "battery": "🔋", "exam": "📝", "mirror": "🪞", "brush": "🖌️",
    "hammer": "🔨", "gear": "⚙️", "chain": "⛓️", "shield": "🛡️", "flag": "🚩",
    "bell": "🔔", "lock": "🔒", "coin": "🪙", "dollar": "💵", "diamond": "💎",
    "crown": "👑", "ring": "💍", "medal": "🏅", "trophy": "🏆", "wheel": "🛞",
    # еда
    "cherry": "🍒", "chocolate": "🍫", "pepper": "🌶️", "salt": "🧂",
    # животные
    "dragon": "🐉", "rooster": "🐓", "bat": "🦇",
    # природа / места
    "factory": "🏭", "galaxy": "🌌", "bridge": "🌉", "castle": "🏰", "tower": "🗼",
    "island": "🏝️", "desert": "🏜️", "planet": "🪐", "stadium": "🏟️", "bank": "🏦",
    # спорт
    "baseball": "⚾", "boxing": "🥊", "golf": "⛳", "fishing": "🎣",
    # тело / здоровье / прочее
    "brain": "🧠", "bone": "🦴", "alien": "👽",
}


def emoji_for(word: str) -> str:
    """Returns a native color emoji for a concrete word, or "" if there is none."""
    w = _clean(word).lower()
    if not w:
        return ""
    if w in WORD_EMOJI:
        return WORD_EMOJI[w]
    if w.endswith("es") and w[:-2] in WORD_EMOJI:
        return WORD_EMOJI[w[:-2]]
    if w.endswith("s") and w[:-1] in WORD_EMOJI:
        return WORD_EMOJI[w[:-1]]
    return ""


# Слова, для которых НЕ тянем внешние фото (детская безопасность): даже при
# mature=false стоковое фото может оказаться неуместным. Они получают SVG-сцену.
PHOTO_BLOCKLIST = {
    "dating", "date", "kiss", "kissing", "romance", "romantic", "love",
    "beer", "wine", "alcohol", "drunk", "vodka", "cocktail", "bar",
    "cigarette", "cigarettes", "smoking", "smoke", "tobacco",
    "drug", "drugs", "gun", "guns", "weapon", "weapons", "knife", "rifle",
    "blood", "bloody", "war", "death", "dead", "kill", "killing", "fight",
    "gambling", "casino", "bikini", "underwear", "lingerie", "naked", "nude",
    "pregnant", "divorce", "funeral", "grave", "violence",
}


def is_sensitive_word(word: str) -> bool:
    """True for words we never want to fetch external imagery for (kids safety)."""
    w = _clean(word).lower()
    return w in SENSITIVE_WORDS or w in PHOTO_BLOCKLIST


def is_complex_visual_type(visual_type: str) -> bool:
    return visual_type in COMPLEX_VISUAL_TYPES


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def determine_part_of_speech(word: str, translation: str = "", topic: str = "") -> str:
    word = _clean(word).lower()
    translation = _clean(translation).lower()
    topic = _clean(topic).lower()
    if word in MODAL_WORDS:
        return "modal_verb"
    if word in FUNCTION_WORD_POS:
        return FUNCTION_WORD_POS[word]
    if word in CONTRAST_WORDS | EMOTION_WORDS | SITUATION_WORDS:
        return "adjective"
    adjective_endings = ("ый", "ий", "ой", "ая", "ое", "ые", "ный", "енный", "ованный")
    if translation.endswith(adjective_endings):
        return "adjective"
    third_person_verb_endings = ("ет", "ёт", "ит", "ют", "ут", "ают", "яют", "ует", "ирует")
    if (
        word in ACTION_WORDS
        or topic in {"verbs", "movement"}
        or translation.endswith(("ть", "ться", "лся", "лась", "лось", "лись"))
        or (word.endswith(("s", "es")) and translation.endswith(third_person_verb_endings))
        or word.endswith(("ed", "ing"))
    ):
        return "verb"
    if word.endswith("ly") or topic == "grammar":
        return "adverb"
    return "noun"


def determine_visual_type(word: str, part_of_speech: str, topic: str = "") -> str:
    word = _clean(word).lower()
    topic = _clean(topic).lower()
    if word in SENSITIVE_WORDS:
        return "no_good_visual"
    if word in NO_GOOD_VISUAL_WORDS:
        return "no_good_visual"
    if word in TWO_PANEL_WORDS:
        return "two_panel_comic"
    if word in CAUSE_EFFECT_WORDS:
        return "cause_effect"
    if word in MODAL_WORDS:
        return "grammar_diagram"
    if word in SPATIAL_WORDS:
        return "spatial_relation"
    if word in SITUATION_WORDS:
        return "situation"
    if word in EMOTION_WORDS:
        return "emotion"
    if word in CONTRAST_WORDS:
        return "contrast"
    if word in ACTION_WORDS or part_of_speech == "verb":
        return "action"
    if part_of_speech == "adjective":
        return "situation"
    if part_of_speech in {"conjunction", "article", "particle", "preposition"}:
        return "no_good_visual"
    if part_of_speech == "adverb":
        return "situation"
    if word in AMBIGUOUS_NOUNS:
        return "situation"
    if word in OBJECT_WORDS:
        return "object"
    if word in COMMON_CONCRETE_NOUNS:
        return "object"
    if part_of_speech == "noun" and topic and topic not in CONCRETE_TOPICS:
        return "situation"
    return "object"


def image_confidence_for(visual_type: str, word: str = "") -> float:
    confidence = {
        "object": 0.94,
        "action": 0.90,
        "contrast": 0.82,
        "emotion": 0.82,
        "spatial_relation": 0.84,
        "situation": 0.60,
        "cause_effect": 0.55,
        "two_panel_comic": 0.38,
        "grammar_diagram": 0.42,
        "no_good_visual": 0.15,
    }.get(visual_type, 0.15)
    if visual_type == "object" and word not in OBJECT_WORDS and word not in COMMON_CONCRETE_NOUNS:
        confidence = 0.78
    if word in OBJECT_WORDS | COMMON_CONCRETE_NOUNS:
        confidence = max(confidence, 0.95)
    return confidence


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def create_example_sentence(word: str, part_of_speech: str, visual_type: str, current_example: str = "") -> str:
    word = _clean(word).lower()
    current_example = _clean(current_example)
    if word in EXAMPLES:
        return EXAMPLES[word]
    if current_example and not current_example.lower().startswith("let's learn the word"):
        return current_example
    if visual_type == "spatial_relation":
        return f"The ball is {word} the box."
    if part_of_speech == "verb":
        if word.endswith("ed"):
            return f"It {word}."
        if word.endswith("ing"):
            return f"She is {word}."
        if word.endswith(("s", "es")):
            return f"It {word}."
        return f"I can {word}."
    if part_of_speech == "adjective":
        return f"It is {word}."
    if part_of_speech == "adverb":
        return f"I do this {word}."
    if part_of_speech == "modal_verb":
        return f"You {word} be careful."
    if visual_type == "no_good_visual":
        return f"We use {word} in a sentence."
    if visual_type == "situation":
        return f"This card helps explain {word}."
    if part_of_speech == "noun":
        if word.endswith("s") and not word.endswith("ss"):
            return f"These are {word}."
        return f"This is {_article(word)} {word}."
    return f"Here is the word {word} in a sentence."


def create_simple_meaning(word: str, part_of_speech: str, translation: str) -> str:
    word = _clean(word).lower()
    if word in SIMPLE_MEANINGS:
        return SIMPLE_MEANINGS[word]
    category = {
        "noun": "a thing, person, place, or idea",
        "verb": "an action",
        "adjective": "a word that describes something",
        "adverb": "a word that tells how or when something happens",
        "preposition": "a word that shows a relationship",
        "conjunction": "a word that connects ideas",
        "modal_verb": "a helper word for advice, rules, or possibilities",
        "article": "a small grammar word used before a noun",
        "particle": "a small grammar word",
    }.get(part_of_speech, "a useful English word")
    return f"This is {category}."


def create_russian_hint(word: str, translation: str, part_of_speech: str) -> str:
    word = _clean(word).lower()
    translation = _clean(translation)
    if word in RUSSIAN_HINTS:
        return RUSSIAN_HINTS[word]
    labels = {
        "noun": "название предмета, человека, места или идеи",
        "verb": "действие",
        "adjective": "слово, которое описывает признак",
        "adverb": "слово, которое уточняет, как или когда что-то происходит",
        "preposition": "слово, которое показывает отношение или положение",
        "conjunction": "слово, которое связывает мысли",
        "modal_verb": "слово-помощник для совета, правила или возможности",
    }
    description = labels.get(part_of_speech, "полезное английское слово")
    return f"{word} — {translation}. Это {description}."


def create_image_prompt(word: str, visual_type: str, age_group: str = "") -> str:
    word = _clean(word).lower()
    age_note = (
        "playful and very simple for a young child"
        if age_group == "5_7"
        else "clear and age-appropriate, not babyish"
        if age_group in {"11_13", "14_18"}
        else "clear and playful for a child"
    )
    if word in SCENE_PROMPTS:
        scene = SCENE_PROMPTS[word]
    elif visual_type == "object":
        scene = f"A single clearly recognizable {word} as the main subject"
    elif visual_type == "action":
        scene = f"A cheerful child clearly performing the action {word}, dynamic pose"
    elif visual_type == "contrast":
        scene = f"Two safe familiar objects showing a very clear visual contrast for the idea {word}"
    elif visual_type == "emotion":
        scene = f"A child with a clear facial expression and body pose showing {word}"
    elif visual_type == "spatial_relation":
        scene = f"A red ball and two blue boxes arranged to clearly show the spatial relationship {word}"
    elif visual_type == "situation":
        scene = (
            f"A concrete safe everyday situation for the vocabulary idea {word}; "
            "show meaning through a child's action, facial expression, and context, "
            "not as a single labeled object and not as a generic portrait"
        )
    elif visual_type == "cause_effect":
        scene = "A clear two-step scene where rain causes a child with an umbrella to get wet"
    elif visual_type == "two_panel_comic":
        scene = f"A simple two-panel scene showing the contrast or time relationship for {word}"
    elif visual_type == "grammar_diagram":
        scene = f"A safe everyday situation where the grammar idea {word} is naturally useful"
    else:
        scene = "A simple context-learning scene with a child, two objects, and a clear relationship"
    support_note = (
        "The picture is only a memory cue; it must support the example sentence, "
        "simple meaning, and Russian hint rather than replace the translation."
        if is_complex_visual_type(visual_type)
        else "The picture should be clear enough to support quick recognition."
    )
    return f"{scene}, {age_note}, {support_note} {BASE_IMAGE_STYLE}."


def create_image_alt(word: str, visual_type: str) -> str:
    word = _clean(word).lower()
    descriptions = {
        "object": f"Учебная иллюстрация предмета для слова {word}",
        "action": f"Ребёнок показывает действие {word}",
        "contrast": f"Сцена с контрастом для слова {word}",
        "emotion": f"Выражение эмоции {word}",
        "spatial_relation": f"Схема расположения предметов для слова {word}",
        "situation": f"Жизненная ситуация, объясняющая слово {word}",
        "cause_effect": f"Сцена причины и результата для слова {word}",
        "two_panel_comic": f"Двухкадровая сцена, объясняющая слово {word}",
        "grammar_diagram": f"Учебная ситуация для грамматического слова {word}",
        "no_good_visual": f"Контекстная подсказка для слова {word}",
    }
    return descriptions.get(visual_type, f"Учебная подсказка для слова {word}")


def vocabulary_image_url(word: str, visual_type: str, topic: str = "") -> str:
    return "/vocabulary-visual.svg?" + urlencode({
        "w": _clean(word).lower()[:48],
        "v": visual_type if visual_type in VISUAL_TYPES else "no_good_visual",
        "t": _clean(topic).lower()[:32],
    })


def build_vocabulary_visual(
    word: str,
    translation: str,
    example_sentence: str = "",
    topic: str = "",
    age_group: str = "",
    level: str = "beginner",
) -> dict:
    word = _clean(word).lower()
    translation = _clean(translation)
    part_of_speech = determine_part_of_speech(word, translation, topic)
    visual_type = determine_visual_type(word, part_of_speech, topic)
    confidence = image_confidence_for(visual_type, word)
    needs_review = confidence < 0.7
    if is_complex_visual_type(visual_type):
        needs_review = True
    show_russian_hint = (
        is_complex_visual_type(visual_type)
        or str(level or "beginner").lower() in {"starter", "beginner", "elementary", "a0", "a1", "a2"}
    )
    return {
        "word": word,
        "translation": translation,
        "part_of_speech": part_of_speech,
        "visual_type": visual_type,
        "image_prompt": create_image_prompt(word, visual_type, age_group),
        "image_url": vocabulary_image_url(word, visual_type, topic),
        "image_alt": create_image_alt(word, visual_type),
        "emoji": emoji_for(word),
        "example_sentence": create_example_sentence(word, part_of_speech, visual_type, example_sentence),
        "simple_meaning": create_simple_meaning(word, part_of_speech, translation),
        "russian_hint": create_russian_hint(word, translation, part_of_speech),
        "image_confidence": confidence,
        "needs_review": needs_review,
        "generation_status": "needs_review" if needs_review else "generated",
        "show_russian_hint": show_russian_hint,
    }
