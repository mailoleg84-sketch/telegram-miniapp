"""Контент возрастных тестов уровня (вынесено из webapp/server.py).

Чистые данные: для каждой возрастной группы список вопросов
(prompt + options + correct_id). Логика подсчёта — в server.py."""

LEVEL_TESTS = {
    "5_7": [
        {
            "id": "5_7_cat",
            "prompt": "Что значит cat?",
            "options": [("cat", "кошка"), ("dog", "собака"), ("sun", "солнце")],
            "correct_id": "cat",
        },
        {
            "id": "5_7_blue",
            "prompt": "Какой цвет blue?",
            "options": [("red", "красный"), ("blue", "синий"), ("green", "зеленый")],
            "correct_id": "blue",
        },
        {
            "id": "5_7_hello",
            "prompt": "Что можно ответить на Hello?",
            "options": [("hi", "Hi!"), ("bye", "Bye!"), ("thanks", "Thanks!")],
            "correct_id": "hi",
        },
        {
            "id": "5_7_three",
            "prompt": "One, two, ...",
            "options": [("five", "five"), ("three", "three"), ("red", "red")],
            "correct_id": "three",
        },
        {
            "id": "5_7_like",
            "prompt": "Как сказать: Я люблю яблоки?",
            "options": [("like", "I like apples."), ("am", "I am apples."), ("go", "I go apples.")],
            "correct_id": "like",
        },
    ],
    "8_10": [
        {
            "id": "8_10_like",
            "prompt": "Выбери правильную фразу.",
            "options": [("like", "I like pizza."), ("likes", "I likes pizza."), ("am", "I am pizza.")],
            "correct_id": "like",
        },
        {
            "id": "8_10_can",
            "prompt": "Что значит I can swim?",
            "options": [("can", "Я умею плавать"), ("want", "Я хочу плавать"), ("had", "Я плавал вчера")],
            "correct_id": "can",
        },
        {
            "id": "8_10_plural",
            "prompt": "Как правильно: две кошки?",
            "options": [("cats", "two cats"), ("cat", "two cat"), ("caties", "two caties")],
            "correct_id": "cats",
        },
        {
            "id": "8_10_question",
            "prompt": "Выбери вопрос.",
            "options": [("do", "Do you like games?"), ("you", "You like do games?"), ("likes", "Does you like games?")],
            "correct_id": "do",
        },
        {
            "id": "8_10_yesterday",
            "prompt": "Вчера я играл.",
            "options": [("played", "I played yesterday."), ("play", "I play yesterday."), ("playing", "I am play yesterday.")],
            "correct_id": "played",
        },
        {
            "id": "8_10_place",
            "prompt": "The book is under the table. Где книга?",
            "options": [("under", "под столом"), ("on", "на столе"), ("near", "рядом со столом")],
            "correct_id": "under",
        },
    ],
    "11_13": [
        {
            "id": "11_13_present",
            "prompt": "He ___ football every Sunday.",
            "options": [("plays", "plays"), ("play", "play"), ("playing", "playing")],
            "correct_id": "plays",
        },
        {
            "id": "11_13_past",
            "prompt": "We ___ to school yesterday.",
            "options": [("went", "went"), ("go", "go"), ("goes", "goes")],
            "correct_id": "went",
        },
        {
            "id": "11_13_question",
            "prompt": "Выбери правильный порядок слов.",
            "options": [("where", "Where do you live?"), ("do", "Where you do live?"), ("live", "Where live you?")],
            "correct_id": "where",
        },
        {
            "id": "11_13_future",
            "prompt": "Tomorrow I ___ visit my friend.",
            "options": [("will", "will"), ("was", "was"), ("did", "did")],
            "correct_id": "will",
        },
        {
            "id": "11_13_comparative",
            "prompt": "My room is ___ than my brother's room.",
            "options": [("bigger", "bigger"), ("big", "big"), ("biggest", "biggest")],
            "correct_id": "bigger",
        },
        {
            "id": "11_13_meaning",
            "prompt": "I have already done my homework.",
            "options": [("already", "Я уже сделал домашку"), ("tomorrow", "Я сделаю домашку завтра"), ("never", "Я никогда не делал домашку")],
            "correct_id": "already",
        },
        {
            "id": "11_13_advice",
            "prompt": "Как дать совет?",
            "options": [("should", "You should rest."), ("musted", "You musted rest."), ("are", "You are rest.")],
            "correct_id": "should",
        },
    ],
    "14_18": [
        {
            "id": "14_18_perfect",
            "prompt": "I ___ just finished my project.",
            "options": [("have", "have"), ("did", "did"), ("am", "am")],
            "correct_id": "have",
        },
        {
            "id": "14_18_condition",
            "prompt": "If I had more time, I ___ travel more.",
            "options": [("would", "would"), ("will", "will"), ("can", "can")],
            "correct_id": "would",
        },
        {
            "id": "14_18_natural",
            "prompt": "Выбери самый естественный ответ на Thanks a lot!",
            "options": [("welcome", "You're welcome!"), ("fine", "I'm fine."), ("later", "See you later.")],
            "correct_id": "welcome",
        },
        {
            "id": "14_18_reported",
            "prompt": "She said that she ___ tired.",
            "options": [("was", "was"), ("is", "is"), ("be", "be")],
            "correct_id": "was",
        },
        {
            "id": "14_18_phrase",
            "prompt": "Что значит I am looking forward to it?",
            "options": [("wait", "Я этого с нетерпением жду"), ("look", "Я смотрю вперед"), ("lost", "Я это потерял")],
            "correct_id": "wait",
        },
        {
            "id": "14_18_email",
            "prompt": "Какая фраза лучше для вежливого письма?",
            "options": [("could", "Could you please help me?"), ("give", "Give me help."), ("must", "You must help.")],
            "correct_id": "could",
        },
        {
            "id": "14_18_passive",
            "prompt": "English ___ in many countries.",
            "options": [("spoken", "is spoken"), ("speaks", "speaks"), ("spoke", "is spoke")],
            "correct_id": "spoken",
        },
        {
            "id": "14_18_opinion",
            "prompt": "Как начать мнение?",
            "options": [("opinion", "In my opinion, ..."), ("because", "Because my opinion, ..."), ("think", "I thinking that ...")],
            "correct_id": "opinion",
        },
    ],
}
