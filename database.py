"""Работа с базой данных PostgreSQL (Neon) через asyncpg.

Подключение берётся из переменной окружения DATABASE_URL.
Используется единый пул соединений на всё приложение.
"""
import ssl

import asyncpg

from config import DATABASE_URL
from data.words import INITIAL_WORDS

# Глобальный пул соединений
_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL не задан. Добавь строку подключения Neon "
                "в переменные окружения."
            )
        # Neon требует SSL. asyncpg не понимает ?sslmode=... в URL,
        # поэтому SSL-режим определяем сами, а параметр из URL вырезаем.
        dsn = DATABASE_URL
        need_ssl = ("sslmode=require" in dsn or "sslmode=verify" in dsn
                    or "sslmode=prefer" in dsn)
        for marker in ("?sslmode=", "&sslmode="):
            if marker in dsn:
                head, tail = dsn.split(marker, 1)
                rest = tail.split("&", 1)
                dsn = head + ("&" + rest[1] if len(rest) > 1 else "")
                dsn = dsn.rstrip("?&")
        ssl_arg = ssl.create_default_context() if need_ssl else None
        _pool = await asyncpg.create_pool(dsn=dsn, ssl=ssl_arg,
                                          min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        BIGINT PRIMARY KEY,
                name           TEXT NOT NULL,
                age_group      TEXT NOT NULL,
                points         INTEGER DEFAULT 0,
                registered_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id           SERIAL PRIMARY KEY,
                word         TEXT NOT NULL UNIQUE,
                translation  TEXT NOT NULL,
                example      TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id        BIGINT,
                word_id        INTEGER,
                correct_count  INTEGER DEFAULT 0,
                wrong_count    INTEGER DEFAULT 0,
                last_seen      TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, word_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await _seed_words(conn)


async def _seed_words(conn) -> None:
    count = await conn.fetchval("SELECT COUNT(*) FROM words")
    if count == 0:
        await conn.executemany(
            "INSERT INTO words (word, translation, example) VALUES ($1, $2, $3)",
            INITIAL_WORDS,
        )


# ---------- Пользователи ----------

async def user_exists(user_id: int) -> bool:
    pool = await _get_pool()
    row = await pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
    return row is not None


async def add_user(user_id: int, name: str, age_group: str) -> None:
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO users (user_id, name, age_group)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id)
        DO UPDATE SET name = EXCLUDED.name, age_group = EXCLUDED.age_group
    """, user_id, name, age_group)


async def get_user(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def update_points(user_id: int, delta: int) -> None:
    pool = await _get_pool()
    await pool.execute(
        "UPDATE users SET points = GREATEST(0, points + $1) WHERE user_id = $2",
        delta, user_id,
    )


# ---------- Слова ----------

async def get_word_by_id(word_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("SELECT * FROM words WHERE id = $1", word_id)


async def get_random_word(exclude_id: int | None = None):
    pool = await _get_pool()
    if exclude_id is not None:
        return await pool.fetchrow(
            "SELECT * FROM words WHERE id != $1 ORDER BY RANDOM() LIMIT 1",
            exclude_id,
        )
    return await pool.fetchrow("SELECT * FROM words ORDER BY RANDOM() LIMIT 1")


async def get_random_words(count: int, exclude_id: int | None = None):
    pool = await _get_pool()
    if exclude_id is not None:
        return await pool.fetch(
            "SELECT * FROM words WHERE id != $1 ORDER BY RANDOM() LIMIT $2",
            exclude_id, count,
        )
    return await pool.fetch(
        "SELECT * FROM words ORDER BY RANDOM() LIMIT $1", count,
    )


# ---------- Прогресс ----------

async def update_progress(user_id: int, word_id: int, correct: bool) -> None:
    pool = await _get_pool()
    if correct:
        await pool.execute("""
            INSERT INTO user_progress (user_id, word_id, correct_count)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, word_id)
            DO UPDATE SET correct_count = user_progress.correct_count + 1,
                          last_seen = NOW()
        """, user_id, word_id)
    else:
        await pool.execute("""
            INSERT INTO user_progress (user_id, word_id, wrong_count)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, word_id)
            DO UPDATE SET wrong_count = user_progress.wrong_count + 1,
                          last_seen = NOW()
        """, user_id, word_id)


async def get_user_stats(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT
            COUNT(DISTINCT word_id)         AS words_learned,
            COALESCE(SUM(correct_count), 0) AS total_correct,
            COALESCE(SUM(wrong_count),   0) AS total_wrong
        FROM user_progress
        WHERE user_id = $1
    """, user_id)


# ---------- Диалоги с ИИ-репетитором ----------

async def add_message(user_id: int, role: str, content: str) -> None:
    pool = await _get_pool()
    await pool.execute(
        "INSERT INTO conversations (user_id, role, content) VALUES ($1, $2, $3)",
        user_id, role, content,
    )


async def get_recent_messages(user_id: int, limit: int = 20):
    """Возвращает последние сообщения в хронологическом порядке."""
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT role, content FROM (
            SELECT id, role, content FROM conversations
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT $2
        ) sub ORDER BY id ASC
    """, user_id, limit)


async def clear_conversation(user_id: int) -> None:
    pool = await _get_pool()
    await pool.execute("DELETE FROM conversations WHERE user_id = $1", user_id)
