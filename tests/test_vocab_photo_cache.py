"""Тесты кэша бесплатных фото (Pixabay) через storage-слой.

После перевода `vocab_photo_storage` на `make_storage` кэш фото умеет жить в R2.
Проверяем серверную часть:
- имя файла кэша «голое», детерминированное, нормализованное (регистр/пробелы);
- попадание кэша отдаётся через `storage.vocab_photo_storage.read` (прокси —
  работает и для приватного R2);
- `.none`-маркер («фото нет») проверяется через `storage…exists` и уводит на
  SVG-фолбэк (302), не жгя квоту Pixabay.

Сам roundtrip backend'ов (local/S3) и eviction — в tests/test_storage.py.
"""
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import make_mocked_request

from webapp import server

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # валидная PNG-сигнатура для _sniff_image_type


class VocabPhotoCacheNameTests(unittest.TestCase):
    def test_name_is_bare_and_normalized(self):
        n1 = server._vocab_photo_cache_name("Cat")
        n2 = server._vocab_photo_cache_name("  cat ")  # регистр/пробелы нормализуются
        self.assertTrue(n1)
        self.assertNotIn("/", n1)
        self.assertNotIn("\\", n1)
        self.assertEqual(n1, n2)

    def test_different_words_differ(self):
        self.assertNotEqual(server._vocab_photo_cache_name("cat"),
                            server._vocab_photo_cache_name("dog"))


class VocabPhotoHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_hit_served_through_storage(self):
        req = make_mocked_request("GET", "/vocabulary-photo?w=cat")
        expected = server._vocab_photo_cache_name("cat")
        read_mock = AsyncMock(return_value=_PNG)
        with patch("webapp.server.VOCAB_FREE_PHOTOS", True), \
             patch("webapp.server.photo_rate_limit_ok", AsyncMock(return_value=True)), \
             patch.object(server.storage.vocab_photo_storage, "read", read_mock):
            resp = await server.vocabulary_photo_handler(req)
        self.assertEqual(resp.body, _PNG)
        self.assertEqual(resp.headers.get("X-Vocab-Photo"), "hit")
        read_mock.assert_awaited_once_with(expected)

    async def test_none_marker_redirects_to_svg(self):
        req = make_mocked_request("GET", "/vocabulary-photo?w=ghost")
        none_name = server._vocab_photo_cache_name("ghost") + ".none"
        exists_mock = AsyncMock(return_value=True)  # маркер «фото нет» есть
        with patch("webapp.server.VOCAB_FREE_PHOTOS", True), \
             patch("webapp.server.photo_rate_limit_ok", AsyncMock(return_value=True)), \
             patch.object(server.storage.vocab_photo_storage, "read",
                          AsyncMock(side_effect=FileNotFoundError)), \
             patch.object(server.storage.vocab_photo_storage, "exists", exists_mock):
            resp = await server.vocabulary_photo_handler(req)
        self.assertEqual(resp.status, 302)  # SVG-фолбэк, фото не качали
        exists_mock.assert_awaited_once_with(none_name)


if __name__ == "__main__":
    unittest.main()
