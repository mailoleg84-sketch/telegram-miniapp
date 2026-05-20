"""Работа с базой данных SQLite (используется и ботом, и Mini App)."""
import aiosqlite

from config import DB_PATH
from data.words import INITIAL_WORDS


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER PRIMARY KEY,
                name           TEXT NOT NULL,
                age_group      TEXT NOT NULL,
                points         INTEGER DEFAULT 0,
                registered_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                word         TEXT NOT NULL UNIQUE,
                translation  TEXT NOT NULL,
                example      TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id        INTEGER,
                word_id        INTEGER,
                correct_count  INTEGER DEFAULT 0,
                wrong_count    INTEGER DEFAULT 0,
                last_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, word_id)
            )
        """)
        await db.commit()
        await _seed_words(db)


async def _seed_words(db) -> None:
    cursor = await db.execute("SELECT COUNT(*) FROM words")
    (count,) = await cursor.fetchone()
    if count == 0:
        await db.executemany(
            "INSERT INTO words (word, translation, example) VALUES (?, ?, ?)",
            INITIAL_WORDS,
        )
        await db.commit()


# ---------- Пользователи ----------

async def user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone() is not None


async def add_user(user_id: int, name: str, age_group: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, name, age_group) VALUES (?, ?, ?)",
            (user_id, name, age_group),
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def update_points(user_id: int, delta: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET points = MAX(0, points + ?) WHERE user_id = ?",
            (delta, user_id),
        )
        await db.commit()


# ---------- Слова ----------

async def get_word_by_id(word_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM words WHERE id = ?", (word_id,))
        return await cursor.fetchone()


async def get_random_word(exclude_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if exclude_id is not None:
            cursor = await db.execute(
                "SELECT * FROM words WHERE id != ? ORDER BY RANDOM() LIMIT 1",
                (exclude_id,),
            )
        else:
            cursor = await db.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1")
        return await cursor.fetchone()


async def get_random_words(count: int, exclude_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if exclude_id is not None:
            cursor = await db.execute(
                "SELECT * FROM words WHERE id != ? ORDER BY RANDOM() LIMIT ?",
                (exclude_id, count),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM words ORDER BY RANDOM() LIMIT ?", (count,)
            )
        return await cursor.fetchall()


# ---------- Прогресс ----------

async def update_progress(user_id: int, word_id: int, correct: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        if correct:
            await db.execute("""
                INSERT INTO user_progress (user_id, word_id, correct_count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, word_id)
                DO UPDATE SET correct_count = correct_count + 1,
                              last_seen = CURRENT_TIMESTAMP
            """, (user_id, word_id))
        else:
            await db.execute("""
                INSERT INTO user_progress (user_id, word_id, wrong_count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, word_id)
                DO UPDATE SET wrong_count = wrong_count + 1,
                              last_seen = CURRENT_TIMESTAMP
            """, (user_id, word_id))
        await db.commit()


async def get_user_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                COUNT(DISTINCT word_id)         AS words_learned,
                COALESCE(SUM(correct_count), 0) AS total_correct,
                COALESCE(SUM(wrong_count),   0) AS total_wrong
            FROM user_progress
            WHERE user_id = ?
        """, (user_id,))
        return await cursor.fetchone()
