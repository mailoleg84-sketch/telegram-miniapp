import unittest
from pathlib import Path

from data.words import LEARNING_WORDS
from webapp.vocabulary_visualizer import (
    build_vocabulary_visual,
    determine_part_of_speech,
    determine_visual_type,
)


class VocabularyVisualizerTests(unittest.TestCase):
    def test_required_test_words_receive_expected_visual_types(self):
        expected = {
            "apple": ("noun", "object", False),
            "dog": ("noun", "object", False),
            "car": ("noun", "object", False),
            "chair": ("noun", "object", False),
            "ball": ("noun", "object", False),
            "run": ("verb", "action", False),
            "jump": ("verb", "action", False),
            "eat": ("verb", "action", False),
            "sleep": ("verb", "action", False),
            "read": ("verb", "action", False),
            "big": ("adjective", "contrast", False),
            "small": ("adjective", "contrast", False),
            "hot": ("adjective", "contrast", False),
            "cold": ("adjective", "contrast", False),
            "clean": ("adjective", "contrast", False),
            "dirty": ("adjective", "contrast", False),
            "happy": ("adjective", "emotion", False),
            "sad": ("adjective", "emotion", False),
            "angry": ("adjective", "emotion", False),
            "scared": ("adjective", "emotion", False),
            "tired": ("adjective", "emotion", False),
            "in": ("preposition", "spatial_relation", False),
            "on": ("preposition", "spatial_relation", False),
            "under": ("preposition", "spatial_relation", False),
            "behind": ("preposition", "spatial_relation", False),
            "between": ("preposition", "spatial_relation", False),
            "brave": ("adjective", "situation", True),
            "kind": ("adjective", "situation", True),
            "honest": ("adjective", "situation", True),
            "careful": ("adjective", "situation", True),
            "proud": ("adjective", "situation", True),
            "worried": ("adjective", "situation", True),
            "although": ("conjunction", "two_panel_comic", True),
            "however": ("conjunction", "two_panel_comic", True),
            "because": ("conjunction", "cause_effect", True),
            "should": ("modal_verb", "grammar_diagram", True),
            "must": ("modal_verb", "grammar_diagram", True),
            "would": ("modal_verb", "grammar_diagram", True),
            "already": ("adverb", "two_panel_comic", True),
            "yet": ("adverb", "two_panel_comic", True),
            "usually": ("adverb", "no_good_visual", True),
        }

        for word, (part_of_speech, visual_type, needs_review) in expected.items():
            with self.subTest(word=word):
                visual = build_vocabulary_visual(word, "перевод", "Let's learn the word.", "basic", "8_10")
                self.assertEqual(visual["part_of_speech"], part_of_speech)
                self.assertEqual(visual["visual_type"], visual_type)
                self.assertEqual(visual["needs_review"], needs_review)
                self.assertTrue(visual["image_prompt"])
                self.assertTrue(visual["image_url"].startswith("/vocabulary-visual.svg?"))
                self.assertTrue(visual["image_alt"])
                self.assertTrue(visual["example_sentence"])
                self.assertTrue(visual["simple_meaning"])
                self.assertTrue(visual["russian_hint"])
                self.assertGreaterEqual(visual["image_confidence"], 0)
                self.assertLessEqual(visual["image_confidence"], 1)

    def test_image_prompts_are_child_safe_and_text_free(self):
        for word in ("apple", "run", "brave", "although", "should", "usually"):
            visual = build_vocabulary_visual(word, "перевод", "", "basic", "8_10")
            prompt = visual["image_prompt"].lower()

            self.assertIn("no text", prompt)
            self.assertIn("no letters", prompt)
            self.assertIn("no labels", prompt)
            self.assertIn("child-safe", prompt)
            self.assertIn("educational", prompt)

    def test_complex_words_use_full_learning_context_not_naive_picture(self):
        complex_words = {
            "brave": "a brave child",
            "honest": "an honest student",
            "careful": "a careful child",
            "although": "although text",
            "should": "the word should",
            "usually": "the word usually",
        }

        for word, bad_prompt in complex_words.items():
            with self.subTest(word=word):
                visual = build_vocabulary_visual(word, "перевод", "Let's learn the word.", "basic", "14_18", "advanced")
                prompt = visual["image_prompt"].lower()

                self.assertTrue(visual["needs_review"])
                self.assertTrue(visual["show_russian_hint"])
                self.assertTrue(visual["example_sentence"])
                self.assertTrue(visual["simple_meaning"])
                self.assertTrue(visual["russian_hint"])
                self.assertIn("support the example sentence", prompt)
                self.assertIn("rather than replace the translation", prompt)
                self.assertNotIn(bad_prompt, prompt)

    def test_all_learning_words_can_build_complete_visual_cards(self):
        for word, translation, example, topic, age_group, _transcription in LEARNING_WORDS:
            with self.subTest(word=word):
                visual = build_vocabulary_visual(word, translation, example, topic, age_group)

                for key in (
                    "part_of_speech",
                    "visual_type",
                    "image_prompt",
                    "image_url",
                    "image_alt",
                    "example_sentence",
                    "simple_meaning",
                    "russian_hint",
                    "image_confidence",
                    "needs_review",
                    "generation_status",
                ):
                    self.assertIn(key, visual)
                    self.assertNotEqual(visual[key], "", key)

    def test_database_and_frontend_include_visual_card_contract(self):
        root = Path(__file__).resolve().parents[1]
        database_py = (root / "database.py").read_text(encoding="utf-8")
        server_py = (root / "webapp" / "server.py").read_text(encoding="utf-8")
        app_js = (root / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
        styles_css = (root / "webapp" / "static" / "styles.css").read_text(encoding="utf-8")

        for column in (
            "part_of_speech",
            "visual_type",
            "image_prompt",
            "image_url",
            "image_alt",
            "example_sentence",
            "simple_meaning",
            "russian_hint",
            "image_confidence",
            "needs_review",
            "generation_status",
            "generated_image_url",
            "generated_image_prompt_hash",
            "generated_image_review",
            "generated_image_status",
            "generated_image_model",
            "generated_image_checked_at",
        ):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", database_py)

        self.assertIn("/vocabulary-visual.svg", server_py)
        self.assertIn("/api/vocab/image/generate", server_py)
        self.assertIn("generate_vocabulary_image", server_py)
        self.assertIn("GENERATED_VOCAB_DIR", server_py)
        self.assertIn("word-image-placeholder", app_js)
        self.assertIn("word-image-retry", app_js)
        self.assertIn("requestGeneratedWordImage", app_js)
        self.assertIn("image_generation_status", app_js)
        self.assertIn("fallback_image_url", app_js)
        self.assertIn("word-detail", app_js)
        self.assertIn("word-explain", app_js)
        self.assertIn("word-hint", app_js)
        self.assertIn("showLearningDetails: false", app_js)
        self.assertIn(".word-visual", styles_css)
        self.assertIn(".word-visual.generating", styles_css)

    def test_part_of_speech_fallbacks_are_reasonable(self):
        self.assertEqual(determine_part_of_speech("improve", "улучшать", "learning"), "verb")
        self.assertEqual(determine_part_of_speech("remained", "остался", "verbs"), "verb")
        self.assertEqual(determine_part_of_speech("carefully", "тщательно", "grammar"), "adverb")
        self.assertEqual(determine_visual_type("the", "article"), "no_good_visual")
        self.assertEqual(determine_visual_type("witness", "noun", "abstract"), "situation")
        injured = build_vocabulary_visual("injured", "раненый", "Let's learn the word injured.", "health", "8_10")
        self.assertEqual(injured["part_of_speech"], "adjective")
        self.assertEqual(injured["visual_type"], "situation")
        self.assertTrue(injured["needs_review"])
        remained = build_vocabulary_visual("remained", "остался", "Let's learn the word remained.", "verbs", "8_10")
        self.assertEqual(remained["visual_type"], "action")
        self.assertNotIn("This is a remained", remained["example_sentence"])
        posts = build_vocabulary_visual("posts", "посты", "Let's learn the word posts.", "technology", "8_10")
        self.assertEqual(posts["example_sentence"], "These are posts.")
        perfectly = build_vocabulary_visual("perfectly", "совершенно", "Let's learn the word perfectly.", "basic", "8_10")
        self.assertEqual(perfectly["visual_type"], "situation")
        self.assertEqual(perfectly["example_sentence"], "I do this perfectly.")
        sons = build_vocabulary_visual("sons", "сыновья", "Let's learn the word sons.", "everyday", "8_10")
        self.assertEqual(sons["visual_type"], "object")
        self.assertFalse(sons["needs_review"])
        teeth = build_vocabulary_visual("teeth", "зубы", "Let's learn the word teeth.", "everyday", "8_10")
        self.assertEqual(teeth["visual_type"], "object")
        options = build_vocabulary_visual("options", "варианты", "Let's learn the word options.", "everyday", "8_10")
        self.assertEqual(options["visual_type"], "situation")
        self.assertTrue(options["needs_review"])
        sensitive = build_vocabulary_visual("torture", "пытки", "Let's learn the word torture.", "everyday", "14_18")
        self.assertEqual(sensitive["visual_type"], "no_good_visual")
        self.assertTrue(sensitive["needs_review"])
        returns = build_vocabulary_visual("returns", "возвращает", "Let's learn the word returns.", "everyday", "8_10")
        self.assertEqual(returns["part_of_speech"], "verb")
        self.assertEqual(returns["visual_type"], "action")
        self.assertEqual(returns["example_sentence"], "It returns.")
        witness = build_vocabulary_visual("witness", "свидетель", "Let's learn the word witness.", "abstract", "8_10")
        self.assertEqual(witness["visual_type"], "situation")
        self.assertTrue(witness["needs_review"])


if __name__ == "__main__":
    unittest.main()
