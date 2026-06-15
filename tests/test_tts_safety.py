"""Контент-фильтр озвучки (TTS) — _TTS_BLOCKED_RE.

Эндпоинт /api/audio/speech авторизован, но принимает произвольный текст. Регекс
должен ловить мат/оскорбления/явный 18+ по границам слова и НЕ давать ложных
срабатываний на легитимных учебных словах.
"""
import unittest

from webapp.routes_chat_voice import _TTS_BLOCKED_RE


class TtsBlocklistTests(unittest.TestCase):
    def assert_blocked(self, text):
        self.assertIsNotNone(_TTS_BLOCKED_RE.search(text), f"должно блокироваться: {text!r}")

    def assert_allowed(self, text):
        self.assertIsNone(_TTS_BLOCKED_RE.search(text), f"НЕ должно блокироваться: {text!r}")

    def test_blocks_profanity(self):
        for t in ("fuck", "What the fuck", "this is SHIT", "you bitch",
                  "asshole!", "a real bastard", "what a prick"):
            self.assert_blocked(t)

    def test_blocks_sexual(self):
        for t in ("porn", "send nudes", "sexy time", "a rapist", "blowjob"):
            self.assert_blocked(t)

    def test_blocks_slurs(self):
        for t in ("retard", "faggot", "that fag", "kike"):
            self.assert_blocked(t)

    def test_case_insensitive(self):
        for t in ("FUCK", "Shit", "ReTaRd"):
            self.assert_blocked(t)

    def test_allows_clean_words(self):
        for t in ("apple", "school", "rainbow", "I love my family",
                  "The cat is happy", "Let's read a book"):
            self.assert_allowed(t)

    def test_allows_words_containing_blocked_substrings(self):
        # Границы слова (\b) не должны ловить безобидные слова с подстроками.
        for t in ("class", "assist", "pass", "grass", "glass", "bass",
                  "grape", "scrape", "method", "methods", "spice", "spicy",
                  "cucumber", "document", "Sussex", "scunthorpe",
                  "title", "shiitake", "flag", "peacock"):
            self.assert_allowed(t)

    def test_allows_legitimate_lesson_words(self):
        # Намеренно НЕ в блок-листе (контекстно-нормальные для уроков 5–18).
        for t in ("nightmare", "scandal", "the naked eye", "pussy cat",
                  "the cock crows at dawn", "a chink of light",
                  "pull the weeds", "a dyke holds back the sea",
                  # реальное учебное слово 11–13 (data/single_words_5000.py)
                  "pissed", "Let's learn the word pissed."):
            self.assert_allowed(t)


if __name__ == "__main__":
    unittest.main()
