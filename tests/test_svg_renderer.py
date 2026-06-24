"""svg_renderer: фолбэк-картинки слов. Валидный SVG, детерминизм, отсутствие
инъекции (слово в SVG не встраивается — только как seed для цвета/иконки)."""
import unittest

from webapp.svg_renderer import _accent_for, _vocabulary_visual_svg, _word_image_svg


class SvgRendererTests(unittest.TestCase):
    def test_word_image_is_valid_svg(self):
        s = _word_image_svg("apple", "food")
        self.assertIn("<svg", s)
        self.assertTrue(s.strip().endswith("</svg>"))

    def test_deterministic(self):
        self.assertEqual(_word_image_svg("dog", "animals"), _word_image_svg("dog", "animals"))

    def test_edge_inputs_no_crash_no_injection(self):
        for word, topic in [("", ""), ("<script>alert(1)</script>", "x&y"),
                            ("a" * 1000, "b" * 1000), (None, None)]:
            s = _word_image_svg(word, topic)
            self.assertIn("<svg", s)
            # слово не попадает в разметку → инъекция невозможна
            self.assertNotIn("<script>", s)
            self.assertNotIn("alert(1)", s)

    def test_vocabulary_visual_valid_for_types(self):
        for vt in ("object", "action", "situation", "emotion", "no_good_visual"):
            s = _vocabulary_visual_svg("dog", "animals", vt)
            self.assertIn("<svg", s)
            self.assertTrue(s.strip().endswith("</svg>"))


class UnifiedAccentTests(unittest.TestCase):
    """Единая палитра: вторичный (акцентный) цвет берётся из палитры темы, а не из
    хэша слова. Раньше у каждого слова был свой случайный accent → «резкая разница»
    между карточками одной темы; теперь он одинаков для всей темы."""

    def test_accent_for_is_deterministic_topic_companion(self):
        self.assertEqual(_accent_for("#2481cc"), "#ff9f43")   # синий → оранжевый
        self.assertEqual(_accent_for("#2481CC"), "#ff9f43")   # без учёта регистра
        self.assertEqual(_accent_for("unknown"), "#ff9f43")   # дефолт
        self.assertEqual(_accent_for(""), "#ff9f43")
        self.assertEqual(_accent_for(None), "#ff9f43")

    def test_same_topic_words_share_one_accent_not_random(self):
        # brave/kind/honest — одна тема (school) → один и тот же акцент в сцене
        # (раньше accent зависел от хэша слова и был у каждого свой).
        accent = _accent_for("#2481cc")
        for word in ("brave", "kind", "honest"):
            with self.subTest(word=word):
                self.assertIn(accent, _vocabulary_visual_svg(word, "school", "situation"))

    def test_spatial_ball_uses_topic_accent(self):
        # Мяч схемы in/on/under раньше был fill случайного цвета (срез хэша слова).
        accent = _accent_for("#2481cc")
        for word in ("in", "on", "under"):
            with self.subTest(word=word):
                self.assertIn(accent, _vocabulary_visual_svg(word, "school", "spatial_relation"))


if __name__ == "__main__":
    unittest.main()
