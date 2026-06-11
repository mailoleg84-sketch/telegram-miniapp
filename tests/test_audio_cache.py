"""Тесты кэширования озвучки через storage-слой (а не напрямую через диск).

После перевода `word_audio_storage` на `make_storage` кэш TTS умеет жить в R2
(переживает деплой). Проверяем серверную часть этой правки:
- имя файла кэша — «голое» (без подкаталога), детерминированное и
  нечувствительное к регистру/пробелам; None для некэшируемого текста;
- обработчик отдаёт попадание кэша через `storage.word_audio_storage.read`
  (одинаково для локального диска и приватного R2 — раздача прокси-методом).

Сам roundtrip backend'ов (local/S3) проверяется в tests/test_storage.py.
"""
import unittest
from unittest.mock import AsyncMock, patch

from webapp import server


class AudioCacheNameTests(unittest.TestCase):
    def test_name_is_bare_filename_and_deterministic(self):
        n1 = server._word_audio_cache_name("Cat", "word", None)
        n2 = server._word_audio_cache_name("  cat ", "word", None)  # регистр/пробелы нормализуются
        self.assertTrue(n1 and n1.endswith(".mp3"))
        self.assertNotIn("/", n1)   # без подкаталога — префикс добавит storage-слой
        self.assertNotIn("\\", n1)
        self.assertEqual(n1, n2)

    def test_speed_changes_name(self):
        self.assertNotEqual(
            server._word_audio_cache_name("cat", "word", None),
            server._word_audio_cache_name("cat", "word", 0.75),
        )

    def test_non_cacheable_returns_none(self):
        self.assertIsNone(server._word_audio_cache_name("hello", "chat", None))    # не режим word
        self.assertIsNone(server._word_audio_cache_name("x" * 200, "word", None))  # слишком длинно
        self.assertIsNone(server._word_audio_cache_name("", "word", None))         # пусто


class AudioCacheHitTests(unittest.IsolatedAsyncioTestCase):
    async def test_hit_served_through_storage_layer(self):
        body = {"text": "cat", "mode": "word"}
        expected_name = server._word_audio_cache_name("cat", "word", None)
        read_mock = AsyncMock(return_value=b"ID3-FAKE-MP3")
        # Хендлер озвучки живёт в webapp/routes_chat_voice.py (шаг 3e-3) —
        # патчим его пространство имён; server реэкспортирует хендлер.
        with patch("webapp.routes_chat_voice._safe_json", AsyncMock(return_value=body)), \
             patch.object(server.storage.word_audio_storage, "read", read_mock):
            resp = await server.api_audio_speech(object())
        self.assertEqual(resp.body, b"ID3-FAKE-MP3")
        self.assertEqual(resp.headers.get("X-Audio-Cache"), "hit")
        self.assertEqual(resp.content_type, "audio/mpeg")
        read_mock.assert_awaited_once_with(expected_name)

    async def test_storage_read_error_is_treated_as_miss(self):
        # Промах кэша (или сбой backend'а) не должен падать с 500 на этапе чтения:
        # обработчик идёт дальше к генерации (тут синтез замокан на «нет аудио» -> 502).
        body = {"text": "dog", "mode": "word"}

        async def _empty_stream(*_a, **_k):
            return
            yield  # noqa: делает функцию async-генератором

        with patch("webapp.routes_chat_voice._safe_json", AsyncMock(return_value=body)), \
             patch.object(server.storage.word_audio_storage, "read",
                          AsyncMock(side_effect=RuntimeError("backend down"))), \
             patch("webapp.routes_chat_voice.synthesize_speech_stream", _empty_stream):
            resp = await server.api_audio_speech(object())
        # Не упали на чтении кэша; дошли до генерации, которая вернула пусто -> 502.
        self.assertEqual(resp.status, 502)


if __name__ == "__main__":
    unittest.main()
