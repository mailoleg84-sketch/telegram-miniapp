"""Навигация «назад»: единый screenHeader + setBack по экранам.

Статические тесты — сканируют исходник webapp/static/app.js (как и существующий
frontend-contract тест), JS не запускают. Проверяют, что у вложенных экранов есть
и нативный Telegram BackButton (setBack), и видимая кнопка «← Назад» (screenHeader
или .screen-back), что корневые экраны back прячут, и что чат при выходе чистится.
"""
import re
import unittest
from pathlib import Path

APP_JS = (Path(__file__).resolve().parents[1] / "webapp" / "static" / "app.js").read_text(encoding="utf-8")


def _func_body(name: str) -> str:
    """Тело функции name: от её объявления до следующего объявления верхнего уровня
    (вложенные function-объявления с отступом не считаются границей)."""
    decl = re.compile(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(")
    match = decl.search(APP_JS)
    if not match:
        raise AssertionError(f"function {name} not found in app.js")
    nxt = re.compile(r"\n(?:async\s+)?function\s+\w+\s*\(")
    after = nxt.search(APP_JS, match.end())
    return APP_JS[match.start():after.start() if after else len(APP_JS)]


# Вложенные экраны, которые сами рендерят шапку с видимой кнопкой назад.
SCREENS_WITH_VISIBLE_BACK = [
    "renderLearningHub", "renderProgressHub", "renderParentZone", "renderParentCabinet",
    "renderSubscription", "renderHelp", "renderLevelTestIntro", "renderLevelQuestion",
    "renderVocabStart", "renderVocabWords", "renderQuizQuestion", "renderGamesMenu",
    "renderWordHuntRound", "renderDictionary", "renderTrainingMenu",
    "renderChoiceTrainingTask", "renderInputTrainingTask", "renderTrainingSessionComplete",
    "renderDailyLesson", "renderDailyWords", "renderDailyQuizQuestion", "renderDailyPhrase",
    "renderDailyFinish", "renderChat", "renderMotivation", "renderParentReport",
    "renderActivityHistory", "renderLeaderboard", "renderAdminPanel", "renderAdminUsers",
    "renderAdminUserDetail", "renderProfile", "renderSettings",
]

# Экраны-загрузчики: сами шапку не рисуют, сразу рендерят дочерний экран, который её
# и показывает. От них требуется только корректный setBack (наследуется дочерним).
LOADER_SCREENS = ["renderVocabQuiz", "renderTrainingSessionNext", "renderDailyQuiz"]

# Question/task-экраны берут setBack у функции, которая их рендерит.
SETBACK_INHERITED_FROM = {
    "renderQuizQuestion": "renderVocabQuiz",
    "renderChoiceTrainingTask": "renderTrainingSessionNext",
    "renderInputTrainingTask": "renderTrainingSessionNext",
    "renderDailyQuizQuestion": "renderDailyQuiz",
}

ROOT_SCREENS = ["renderMenu", "renderRegistration", "renderLoggedOut"]


class NavigationBackTests(unittest.TestCase):
    def test_nested_screens_have_visible_back(self):
        for name in SCREENS_WITH_VISIBLE_BACK:
            with self.subTest(screen=name):
                body = _func_body(name)
                self.assertTrue(
                    "screenHeader(" in body or "screen-back" in body,
                    f"{name}: нет видимой кнопки назад (screenHeader/.screen-back)",
                )

    def test_nested_screens_set_back_target(self):
        for name in SCREENS_WITH_VISIBLE_BACK + LOADER_SCREENS:
            with self.subTest(screen=name):
                bodies = [_func_body(name)]
                if name in SETBACK_INHERITED_FROM:
                    bodies.append(_func_body(SETBACK_INHERITED_FROM[name]))
                self.assertTrue(
                    any("setBack(" in body for body in bodies),
                    f"{name}: нет setBack(...) ни в экране, ни в его загрузчике",
                )

    def test_root_screens_hide_back_button(self):
        for name in ROOT_SCREENS:
            with self.subTest(screen=name):
                body = _func_body(name)
                self.assertIn("setBack(null)", body, f"{name}: корневой экран должен прятать BackButton")
                self.assertNotIn("screenHeader(", body, f"{name}: на корневом экране кнопки назад быть не должно")

    def test_chat_back_runs_cleanup_and_shows_back_on_enter(self):
        body = _func_body("renderChat")
        self.assertIn("cleanupChat()", body, "выход из чата должен звать cleanupChat()")
        self.assertIn("screen-back", body, "в шапке чата должна быть видимая кнопка назад")
        self.assertIn("setBack(renderMenu)", body, "при входе в чат back должен появляться сразу")

    def test_single_delegated_back_listener_uses_state_back(self):
        # Один общий обработчик: клик по .screen-back -> текущий state.back (та же цель,
        # что и нативный BackButton). Нет per-screen onclick и зависших обработчиков.
        self.assertRegex(APP_JS, r"\.screen-back[\s\S]{0,120}state\.back")

    def test_screen_header_helper_exists(self):
        self.assertIn("function screenHeader(", APP_JS)
        self.assertIn('class="screen-back"', APP_JS)

    def test_no_legacy_adhoc_back_ids(self):
        for legacy in ("backToProfile", "reportHome", "historyHome", "adminUsersBack", "adminDetailBack"):
            self.assertNotIn(legacy, APP_JS, f"остался ad-hoc back id: {legacy}")


class QuizImageContractTests(unittest.TestCase):
    def test_quiz_prompt_card_has_no_image(self):
        # Карточки без картинок: в квиз-карточке не осталось рендера картинки/эмодзи-блока.
        body = _func_body("quizPromptCard")
        self.assertNotIn("q.image_url", body)
        self.assertNotIn("word-image", body)
        self.assertNotIn('class="quiz-emoji"', body)

    def test_cards_never_use_photo_stock(self):
        self.assertNotIn("/vocabulary-photo", APP_JS)

    def test_study_card_is_text_only(self):
        # Карточка «Учим слова» (wordStudyCard): без картинок и без шаблонных
        # объяснений simple_meaning/russian_hint; есть бейдж типа значения,
        # конкретное объяснение и блок полезных фраз.
        body = _func_body("wordStudyCard")
        for marker in ("wordImageHtml", "word-image", "image_url", "simple_meaning", "russian_hint"):
            self.assertNotIn(marker, body, marker)
        self.assertIn("word-pos-badge", body)
        self.assertIn("explanation_ru", body)
        self.assertIn("word-phrases", body)


if __name__ == "__main__":
    unittest.main()
