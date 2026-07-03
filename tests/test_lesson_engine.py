import unittest
from pathlib import Path

from webapp.lesson_engine import (
    PHASE_PROGRESS,
    TOPIC_PLANS,
    advance_lesson_state,
    create_lesson_state,
    lesson_prompt_context,
    public_lesson_state,
)
from webapp.openai_service import _runtime_instructions, build_voice_realtime_instructions


class LessonEngineTests(unittest.TestCase):
    def test_age_scenarios_receive_relevant_topic_choices(self):
        scenarios = (
            ("5_7", "animals", "animals"),
            ("8_10", "food", "food"),
            ("8_10", "school", "school"),
            ("11_13", "games", "video_games"),
            ("14_18", "travel", "travel"),
        )
        for index, (age_group, request_text, expected_topic) in enumerate(scenarios):
            with self.subTest(age_group=age_group, expected_topic=expected_topic):
                state = create_lesson_state(age_group, seed=f"scenario-{index}")
                self.assertEqual(state["age_group"], age_group)
                self.assertEqual(len(state["topic_suggestions"]), 3)
                self.assertTrue(all(topic in {item["id"] for item in TOPIC_PLANS[age_group]} for topic in state["topic_suggestions"]))
                state = advance_lesson_state(state, "user", request_text)
                self.assertEqual(state["current_topic"], expected_topic)
                self.assertEqual(state["phase"], "mini_lesson")

    def test_lesson_keeps_topic_until_explicit_change(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "Давай про еду")
        self.assertEqual(state["current_topic"], "food")

        state = advance_lesson_state(state, "assistant", "Поговорим про любимую еду.")
        state = advance_lesson_state(state, "user", "А у меня еще есть собака")
        self.assertEqual(state["current_topic"], "food")
        self.assertEqual(state["support_mode"], "bridge")
        bridge_instruction = lesson_prompt_context(state)["lesson_state_instruction"]
        self.assertIn("свяжи", bridge_instruction)
        # Упоминание другой темы — не ошибка: bridge не должен исправлять реплику.
        self.assertIn("НЕ исправляй", bridge_instruction)

        state = advance_lesson_state(state, "user", "Давай сменим тему на животных")
        self.assertEqual(state["current_topic"], "animals")
        self.assertEqual(state["phase"], "mini_lesson")

    def test_confusion_uses_support_without_changing_topic(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "school")
        state = advance_lesson_state(state, "user", "Я не понимаю, объясни проще")

        self.assertEqual(state["current_topic"], "school")
        self.assertEqual(state["last_language"], "russian")
        self.assertEqual(state["support_mode"], "confused")
        prompt = lesson_prompt_context(state)
        self.assertIn("по-русски", prompt["lesson_state_instruction"])
        self.assertIn("выбор из двух", prompt["lesson_state_instruction"])

    def test_confusion_before_topic_does_not_force_topic_menu(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "Я не понимаю")

        prompt = lesson_prompt_context(state)

        self.assertIn("Не перечисляй темы", prompt["lesson_state_instruction"])
        self.assertIn("суперлегкий английский шаг", prompt["lesson_state_instruction"])
        self.assertNotIn("предложи ровно три темы", prompt["lesson_state_instruction"])

    def test_common_child_words_select_topic_before_menu(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "Мне нравится Майнкрафт")

        self.assertEqual(state["current_topic"], "games")

        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "I like cat")

        self.assertEqual(state["current_topic"], "animals")

    def test_tired_child_gets_easier_activity_not_a_new_topic(self):
        state = create_lesson_state("11_13", seed="kid")
        state = advance_lesson_state(state, "user", "music")
        state = advance_lesson_state(state, "user", "Мне скучно и я устал")

        self.assertEqual(state["current_topic"], "music")
        self.assertEqual(state["support_mode"], "tired")
        self.assertIn("легкую игру", lesson_prompt_context(state)["lesson_state_instruction"])

    def test_simple_error_requests_one_gentle_correction(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "animals")
        state = advance_lesson_state(state, "user", "I like dog")

        self.assertEqual(state["current_topic"], "animals")
        self.assertEqual(state["correction_count"], 1)
        self.assertEqual(state["support_mode"], "correction")
        self.assertEqual(public_lesson_state(state)["avatar_state"], "correcting")
        self.assertIn("только одну главную ошибку", lesson_prompt_context(state)["lesson_state_instruction"])

    def test_lesson_moves_through_structured_phases(self):
        state = create_lesson_state("14_18", seed="teen")
        state = advance_lesson_state(state, "user", "travel")
        phases = []
        for turn in range(10):
            state = advance_lesson_state(state, "assistant", f"turn {turn}")
            phases.append(state["phase"])

        self.assertEqual(phases[:2], ["mini_lesson", "mini_lesson"])
        self.assertEqual(phases[2:7], ["dialogue"] * 5)
        self.assertEqual(phases[7:9], ["challenge"] * 2)
        self.assertEqual(phases[-1], "wrapup")
        self.assertEqual(public_lesson_state(state)["progress_percent"], PHASE_PROGRESS["wrapup"])

    def test_mastery_reaches_wrapup_before_turn_ceiling(self):
        # Ребёнок реально произносит целевую фразу — урок движется по усвоению,
        # а не только по счётчику ходов, и доходит до итога раньше потолка в 10 ходов.
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "food")
        self.assertEqual(state["current_topic"], "food")
        for _ in range(3):
            state = advance_lesson_state(state, "assistant", "Nice, your turn.")
            state = advance_lesson_state(state, "user", "Can I have a pizza, please?")
        self.assertGreaterEqual(state["target_hits"], 2)
        for _ in range(3):
            state = advance_lesson_state(state, "assistant", "Great job!")
        self.assertEqual(state["turn_count"], 6)
        self.assertEqual(state["phase"], "wrapup")

    def test_no_mastery_keeps_old_turn_based_ceiling(self):
        # Без попаданий (ребёнок не произносит цель) фазы идут по старым потолкам.
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "food")
        for _ in range(5):
            state = advance_lesson_state(state, "assistant", "Let's keep going.")
        self.assertEqual(state["target_hits"], 0)
        self.assertEqual(state["phase"], "dialogue")

    def test_no_preference_can_start_a_topic_without_repeated_menu(self):
        state = create_lesson_state("5_7", seed="small-kid")
        first_suggestion = state["topic_suggestions"][0]
        state = advance_lesson_state(state, "user", "Выбери сам")

        self.assertEqual(state["current_topic"], first_suggestion)
        self.assertEqual(state["phase"], "mini_lesson")

    def test_public_state_is_compact_and_child_friendly(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "games")
        payload = public_lesson_state(state)

        self.assertEqual(payload["topic_label"], "Игры")
        self.assertEqual(payload["phase_label"], "Новые слова и фраза")
        self.assertTrue(payload["target_phrase"])
        self.assertNotIn("lesson_state_instruction", payload)

    def test_voice_routes_and_frontend_share_persistent_lesson_state(self):
        # Голосовые маршруты живут в webapp/routes_chat_voice.py (шаг 3e-3).
        root = Path(__file__).resolve().parents[1]
        routes_chat_voice = (root / "webapp" / "routes_chat_voice.py").read_text(encoding="utf-8")
        database = (root / "database.py").read_text(encoding="utf-8")
        app = (root / "webapp" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS voice_lesson_state", database)
        self.assertGreaterEqual(routes_chat_voice.count("_advance_voice_lesson_state("), 4)
        self.assertGreaterEqual(routes_chat_voice.count("public_lesson_state("), 4)
        self.assertIn("_voice_unclear_payload", routes_chat_voice)
        self.assertIn('id="voiceLessonStrip"', app)
        self.assertIn("renderLessonState(result.lesson_state)", app)
        self.assertIn("VOICE_STATE_LABELS", app)
        self.assertIn("friendlyVoiceError", app)
        self.assertIn("microphone_denied", app)
        # Микрофон возвращается коротким forceEarlier-таймером по окончании аудио,
        # без оценки длины речи (которая раньше глушила ребёнка до 26с).
        self.assertIn("scheduleRealtimeMicResume(400, true)", app)

    def test_voice_prompts_receive_authoritative_lesson_state(self):
        state = create_lesson_state("8_10", seed="kid")
        state = advance_lesson_state(state, "user", "food")
        context = {
            "mode": "voice",
            "age": 10,
            "age_group": "8_10",
            "level": "beginner",
            **lesson_prompt_context(state),
        }

        prompt = _runtime_instructions("Misha", "10 лет", context, "А у меня есть собака")
        realtime = build_voice_realtime_instructions("Misha", "10 лет", context)

        self.assertIn("AUTHORITATIVE LESSON STATE", prompt)
        self.assertIn("Current topic: Любимая еда", prompt)
        self.assertIn("Never tell the child", prompt)
        self.assertIn("Authoritative lesson phase", realtime)
        self.assertIn("bridge it naturally", realtime)


if __name__ == "__main__":
    unittest.main()
