"""Стартовые слова для детского AI-репетитора.

Формат:
(word, translation, example, topic, age_group)
"""

INITIAL_WORDS = [
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
