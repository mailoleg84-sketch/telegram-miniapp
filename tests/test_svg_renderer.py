"""svg_renderer: фолбэк-картинки слов. Валидный SVG, детерминизм, отсутствие
инъекции (слово в SVG не встраивается — только как seed для цвета/иконки)."""
import unittest

from webapp.svg_renderer import _vocabulary_visual_svg, _word_image_svg


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


if __name__ == "__main__":
    unittest.main()
