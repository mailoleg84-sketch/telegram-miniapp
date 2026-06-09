"""Юнит-тесты слоя данных database.py через фейковый asyncpg-пул.

Реальная Postgres не нужна: фейковый пул записывает (метод, SQL, параметры) и
отдаёт заданные строки. Так ловим регрессии в выборе ветки SQL, порядке
параметров и маппинге результата — без инфраструктуры и без прод-БД.
(Корректность самого SQL против Postgres — отдельный интеграционный уровень.)
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import database


class FakePool:
    def __init__(self):
        self.calls = []          # [(method, sql, args)]
        self.fetch_return = []
        self.fetchrow_return = None
        self.fetchval_return = None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "OK"

    async def executemany(self, sql, args_list):
        self.calls.append(("executemany", sql, list(args_list)))
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.fetch_return

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self.fetchrow_return

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self.fetchval_return


def run_with(fake, coro):
    with patch("database._get_pool", new=AsyncMock(return_value=fake)):
        return asyncio.run(coro)


class UpdateProgressTests(unittest.TestCase):
    def test_correct_branch_sql_and_params(self):
        fake = FakePool()
        run_with(fake, database.update_progress(7, 42, correct=True))
        method, sql, args = fake.calls[0]
        self.assertEqual(method, "execute")
        self.assertEqual(args, (7, 42))
        self.assertIn("correct_count = user_progress.correct_count + 1", sql)
        self.assertIn("LEAST(COALESCE(user_progress.review_streak, 0) + 1, 2)", sql)

    def test_wrong_branch_resets_streak(self):
        fake = FakePool()
        run_with(fake, database.update_progress(7, 42, correct=False))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, (7, 42))
        self.assertIn("wrong_count = user_progress.wrong_count + 1", sql)
        self.assertIn("review_streak = 0", sql)


class UpdateProgressBulkTests(unittest.TestCase):
    def test_bulk_builds_param_tuples(self):
        fake = FakePool()
        run_with(fake, database.update_progress_bulk(7, [(1, True), (2, False)]))
        method, _sql, args_list = fake.calls[0]
        self.assertEqual(method, "executemany")
        self.assertEqual(args_list, [(7, 1, True), (7, 2, False)])

    def test_empty_items_is_noop(self):
        fake = FakePool()
        run_with(fake, database.update_progress_bulk(7, []))
        self.assertEqual(fake.calls, [])


class UsageTests(unittest.TestCase):
    def test_model_requests_today_returns_int(self):
        fake = FakePool()
        fake.fetchval_return = 3
        out = run_with(fake, database.get_model_requests_today(7, "gpt-realtime-2"))
        self.assertEqual(out, 3)
        _, _sql, args = fake.calls[0]
        self.assertEqual(args, (7, "gpt-realtime-2"))

    def test_model_requests_today_handles_none(self):
        fake = FakePool()
        fake.fetchval_return = None
        out = run_with(fake, database.get_model_requests_today(7, "m"))
        self.assertEqual(out, 0)

    def test_get_ai_usage_today_passes_user_id(self):
        fake = FakePool()
        fake.fetchrow_return = {"requests": 5}
        out = run_with(fake, database.get_ai_usage_today(7))
        self.assertEqual(out, {"requests": 5})
        _, _sql, args = fake.calls[0]
        self.assertEqual(args, (7,))


class GetRandomWordsBranchTests(unittest.TestCase):
    def _rows(self, n):
        return [{"id": 100 + i, "word": f"w{i}"} for i in range(n)]

    def test_exclude_and_age_group(self):
        fake = FakePool()
        fake.fetch_return = self._rows(3)  # >= count -> возвращает сразу
        run_with(fake, database.get_random_words(3, exclude_id=5, age_group="8_10"))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, (5, "8_10", 3))
        self.assertIn("age_group = $2", sql)
        self.assertIn("id != $1", sql)

    def test_exclude_only(self):
        fake = FakePool()
        run_with(fake, database.get_random_words(4, exclude_id=5))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, (5, 4))
        self.assertIn("id != $1", sql)
        self.assertNotIn("age_group", sql)

    def test_age_group_only(self):
        fake = FakePool()
        run_with(fake, database.get_random_words(6, age_group="11_13"))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, ("11_13", 6))
        self.assertIn("age_group = $1", sql)

    def test_neither(self):
        fake = FakePool()
        run_with(fake, database.get_random_words(2))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, (2,))
        self.assertNotIn("age_group", sql)


class AddMessageRetentionTests(unittest.TestCase):
    def test_insert_then_prune_when_retention_on(self):
        fake = FakePool()
        with patch("database.CHAT_RETENTION_PER_USER", 50):
            run_with(fake, database.add_message(7, "user", "hi"))
        self.assertEqual(len(fake.calls), 2)
        m0, sql0, args0 = fake.calls[0]
        self.assertEqual((m0, args0), ("execute", (7, "user", "hi")))
        self.assertIn("INSERT INTO conversations", sql0)
        m1, sql1, args1 = fake.calls[1]
        self.assertEqual(m1, "execute")
        self.assertIn("DELETE FROM conversations", sql1)
        self.assertEqual(args1, (7, 50))

    def test_no_prune_when_retention_disabled(self):
        fake = FakePool()
        with patch("database.CHAT_RETENTION_PER_USER", 0):
            run_with(fake, database.add_message(7, "user", "hi"))
        self.assertEqual(len(fake.calls), 1)  # только INSERT
        self.assertIn("INSERT INTO conversations", fake.calls[0][1])


class MiscQueryTests(unittest.TestCase):
    def test_get_words_by_ids_empty_skips_db(self):
        fake = FakePool()
        out = run_with(fake, database.get_words_by_ids([]))
        self.assertEqual(out, [])
        self.assertEqual(fake.calls, [])

    def test_get_words_by_ids_passes_array(self):
        fake = FakePool()
        fake.fetch_return = [{"id": 1}]
        run_with(fake, database.get_words_by_ids([1, 2, 3]))
        _, sql, args = fake.calls[0]
        self.assertEqual(args, ([1, 2, 3],))
        self.assertIn("ANY($1::INTEGER[])", sql)

    def test_add_user_param_order(self):
        fake = FakePool()
        run_with(fake, database.add_user(
            7, "Маша", "8_10", parent_name="Олег", child_age=9,
            goal="speaking", english_level="beginner",
        ))
        method, _sql, args = fake.calls[0]
        self.assertEqual(method, "execute")
        self.assertEqual(args, (7, "Маша", "8_10", "Олег", 9, "speaking", "beginner"))


if __name__ == "__main__":
    unittest.main()
