"""Работа с базой данных PostgreSQL (Neon) через asyncpg.

Подключение берётся из переменной окружения DATABASE_URL.
Используется единый пул соединений на всё приложение.
"""
import ssl
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

from config import DATABASE_URL
from data.words import LEARNING_WORDS

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
        # Neon требует SSL. asyncpg не понимает часть libpq-параметров
        # (?sslmode=require&channel_binding=require), поэтому SSL-режим
        # определяем сами, а несовместимые query-параметры вырезаем.
        dsn = DATABASE_URL
        parts = urlsplit(dsn)
        query = parse_qsl(parts.query, keep_blank_values=True)
        sslmode = next((value for key, value in query if key == "sslmode"), "")
        need_ssl = sslmode in {"require", "verify-ca", "verify-full", "prefer"}
        safe_query = [
            (key, value)
            for key, value in query
            if key not in {"sslmode", "channel_binding"}
        ]
        dsn = urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(safe_query),
            parts.fragment,
        ))
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
                parent_name    TEXT,
                child_age      INTEGER,
                goal           TEXT,
                english_level  TEXT DEFAULT 'beginner',
                level_test_score INTEGER,
                level_test_completed_at TIMESTAMP,
                points         INTEGER DEFAULT 0,
                registered_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_name TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS child_age INTEGER")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS goal TEXT")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS english_level TEXT DEFAULT 'beginner'")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS level_test_score INTEGER")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS level_test_completed_at TIMESTAMP")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id           SERIAL PRIMARY KEY,
                word         TEXT NOT NULL UNIQUE,
                translation  TEXT NOT NULL,
                transcription TEXT,
                example      TEXT,
                topic        TEXT DEFAULT 'basic',
                age_group    TEXT DEFAULT '8_10'
            )
        """)
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS transcription TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS topic TEXT DEFAULT 'basic'")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS age_group TEXT DEFAULT '8_10'")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id        BIGINT,
                word_id        INTEGER,
                correct_count  INTEGER DEFAULT 0,
                wrong_count    INTEGER DEFAULT 0,
                review_streak  INTEGER DEFAULT 0,
                last_seen      TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, word_id)
            )
        """)
        await conn.execute("ALTER TABLE user_progress ADD COLUMN IF NOT EXISTS review_streak INTEGER DEFAULT 0")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage (
                id             SERIAL PRIMARY KEY,
                user_id        BIGINT NOT NULL,
                model          TEXT NOT NULL,
                input_tokens   INTEGER DEFAULT 0,
                output_tokens  INTEGER DEFAULT 0,
                total_tokens   INTEGER DEFAULT 0,
                cost_usd       NUMERIC(12, 6) DEFAULT 0,
                created_at     TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS ai_usage_user_created_idx
            ON ai_usage (user_id, created_at DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_lessons (
                user_id          BIGINT NOT NULL,
                lesson_date      DATE NOT NULL DEFAULT CURRENT_DATE,
                completed_steps  INTEGER DEFAULT 0,
                completed        BOOLEAN DEFAULT FALSE,
                completed_at     TIMESTAMP,
                rewarded_at      TIMESTAMP,
                created_at       TIMESTAMP DEFAULT NOW(),
                updated_at       TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, lesson_date)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary_sessions (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL,
                topic           TEXT,
                age_group       TEXT NOT NULL,
                word_ids        INTEGER[] NOT NULL,
                correct_count   INTEGER DEFAULT 0,
                wrong_count     INTEGER DEFAULT 0,
                completed       BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMP DEFAULT NOW(),
                completed_at    TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS vocabulary_sessions_user_created_idx
            ON vocabulary_sessions (user_id, created_at DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                id              SERIAL PRIMARY KEY,
                user_id         BIGINT NOT NULL,
                game_type       TEXT NOT NULL,
                age_group       TEXT NOT NULL,
                word_ids        INTEGER[] NOT NULL,
                correct_count   INTEGER DEFAULT 0,
                wrong_count     INTEGER DEFAULT 0,
                completed       BOOLEAN DEFAULT FALSE,
                created_at      TIMESTAMP DEFAULT NOW(),
                completed_at    TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS game_sessions_user_created_idx
            ON game_sessions (user_id, created_at DESC)
        """)
        await _seed_words(conn)


async def _seed_words(conn) -> None:
    active_words = [item[0] for item in LEARNING_WORDS]
    await conn.executemany(
        """
        INSERT INTO words (word, translation, example, topic, age_group, transcription)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (word)
        DO UPDATE SET
            translation = EXCLUDED.translation,
            transcription = EXCLUDED.transcription,
            example = EXCLUDED.example,
            topic = EXCLUDED.topic,
            age_group = EXCLUDED.age_group
        """,
        LEARNING_WORDS,
    )
    await conn.execute(
        """
        DELETE FROM user_progress
        WHERE word_id IN (
            SELECT id FROM words WHERE NOT (word = ANY($1::text[]))
        )
        """,
        active_words,
    )
    await conn.execute(
        "DELETE FROM words WHERE NOT (word = ANY($1::text[]))",
        active_words,
    )


# ---------- Пользователи ----------

async def user_exists(user_id: int) -> bool:
    pool = await _get_pool()
    row = await pool.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id)
    return row is not None


async def add_user(
    user_id: int,
    name: str,
    age_group: str,
    parent_name: str | None = None,
    child_age: int | None = None,
    goal: str | None = None,
    english_level: str | None = None,
) -> None:
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO users (user_id, name, age_group, parent_name, child_age, goal, english_level)
        VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, 'beginner'))
        ON CONFLICT (user_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            age_group = EXCLUDED.age_group,
            parent_name = EXCLUDED.parent_name,
            child_age = EXCLUDED.child_age,
            goal = EXCLUDED.goal,
            english_level = COALESCE(users.english_level, EXCLUDED.english_level)
    """, user_id, name, age_group, parent_name, child_age, goal, english_level)


async def get_user(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def update_user_level(user_id: int, english_level: str, score: int) -> None:
    pool = await _get_pool()
    await pool.execute("""
        UPDATE users
        SET english_level = $2,
            level_test_score = $3,
            level_test_completed_at = NOW()
        WHERE user_id = $1
    """, user_id, english_level, score)


async def update_points(user_id: int, delta: int) -> None:
    pool = await _get_pool()
    await pool.execute(
        "UPDATE users SET points = GREATEST(0, points + $1) WHERE user_id = $2",
        delta, user_id,
    )


async def reset_learning_results(user_id: int) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                UPDATE users
                SET points = 0,
                    english_level = 'beginner',
                    level_test_score = NULL,
                    level_test_completed_at = NULL
                WHERE user_id = $1
            """, user_id)
            await conn.execute("DELETE FROM user_progress WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM daily_lessons WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM vocabulary_sessions WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM game_sessions WHERE user_id = $1", user_id)


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


async def get_random_words(
    count: int,
    exclude_id: int | None = None,
    age_group: str | None = None,
):
    pool = await _get_pool()
    if exclude_id is not None and age_group:
        rows = list(await pool.fetch(
            """
            SELECT * FROM words
            WHERE id != $1
              AND age_group = $2
            ORDER BY RANDOM()
            LIMIT $3
            """,
            exclude_id, age_group, count,
        ))
        if len(rows) >= count:
            return rows
        excluded_ids = [exclude_id] + [row["id"] for row in rows]
        fallback_rows = await pool.fetch(
            """
            SELECT * FROM words
            WHERE id != ALL($1::INTEGER[])
            ORDER BY RANDOM()
            LIMIT $2
            """,
            excluded_ids, count - len(rows),
        )
        rows.extend(fallback_rows)
        return rows
    if exclude_id is not None:
        return await pool.fetch(
            "SELECT * FROM words WHERE id != $1 ORDER BY RANDOM() LIMIT $2",
            exclude_id, count,
        )
    if age_group:
        return await pool.fetch(
            "SELECT * FROM words WHERE age_group = $1 ORDER BY RANDOM() LIMIT $2",
            age_group, count,
        )
    return await pool.fetch(
        "SELECT * FROM words ORDER BY RANDOM() LIMIT $1", count,
    )


async def get_words_for_age(age_group: str, count: int, topic: str | None = None):
    pool = await _get_pool()
    rows = []
    if topic:
        rows = await pool.fetch("""
            SELECT * FROM words
            WHERE age_group = $1 AND topic = $2
            ORDER BY RANDOM()
            LIMIT $3
        """, age_group, topic, count)
        if len(rows) >= count:
            return rows
    rows = list(rows)
    seen_ids = {row["id"] for row in rows}
    age_rows = await pool.fetch("""
        SELECT * FROM words
        WHERE age_group = $1
        ORDER BY RANDOM()
        LIMIT $2
    """, age_group, count)
    for row in age_rows:
        if row["id"] not in seen_ids:
            rows.append(row)
            seen_ids.add(row["id"])
        if len(rows) >= count:
            return rows

    fallback_rows = await pool.fetch("""
        SELECT * FROM words
        WHERE id != ALL($1::INTEGER[])
        ORDER BY RANDOM()
        LIMIT $2
    """, list(seen_ids), count - len(rows))
    rows.extend(fallback_rows)
    return rows


async def get_word_options(word_id: int, age_group: str, count: int = 3):
    pool = await _get_pool()
    rows = list(await pool.fetch("""
        SELECT id, translation FROM words
        WHERE id != $1
          AND age_group = $2
        ORDER BY RANDOM()
        LIMIT $3
    """, word_id, age_group, count))
    if len(rows) >= count:
        return rows

    excluded_ids = [word_id] + [row["id"] for row in rows]
    fallback_rows = await pool.fetch("""
        SELECT id, translation FROM words
        WHERE id != ALL($1::INTEGER[])
        ORDER BY RANDOM()
        LIMIT $2
    """, excluded_ids, count - len(rows))
    rows.extend(fallback_rows)
    return rows


async def get_practice_word(
    user_id: int,
    exclude_id: int | None = None,
    age_group: str | None = None,
):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT w.*
        FROM words w
        LEFT JOIN user_progress up
               ON up.word_id = w.id
              AND up.user_id = $1
        WHERE ($2::INTEGER IS NULL OR w.id != $2)
          AND ($3::TEXT IS NULL OR w.age_group = $3)
        ORDER BY
            CASE
                WHEN up.word_id IS NULL THEN 5
                WHEN COALESCE(up.wrong_count, 0) > COALESCE(up.correct_count, 0) THEN 4
                WHEN up.last_seen < NOW() - (
                    INTERVAL '1 hour' * POWER(2, LEAST(COALESCE(up.correct_count, 0), 8))
                ) THEN 3
                WHEN COALESCE(up.wrong_count, 0) > 0 THEN 2
                ELSE 1
            END DESC,
            COALESCE(up.wrong_count, 0) DESC,
            up.last_seen ASC NULLS FIRST,
            RANDOM()
        LIMIT 1
    """, user_id, exclude_id, age_group)


async def get_review_word(
    user_id: int,
    exclude_id: int | None = None,
    age_group: str | None = None,
):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT w.*
        FROM user_progress up
        JOIN words w ON w.id = up.word_id
        WHERE up.user_id = $1
          AND ($2::INTEGER IS NULL OR w.id != $2)
          AND ($3::TEXT IS NULL OR w.age_group = $3)
          AND COALESCE(up.wrong_count, 0) > 0
          AND COALESCE(up.review_streak, 0) < 2
        ORDER BY
            COALESCE(up.review_streak, 0) ASC,
            COALESCE(up.wrong_count, 0) DESC,
            up.last_seen ASC,
            RANDOM()
        LIMIT 1
    """, user_id, exclude_id, age_group)


async def get_user_dictionary(user_id: int, filter_mode: str = "all", limit: int = 80):
    pool = await _get_pool()
    filter_sql = ""
    if filter_mode == "review":
        filter_sql = """
          AND up.word_id IS NOT NULL
          AND COALESCE(up.wrong_count, 0) > 0
          AND COALESCE(up.review_streak, 0) < 2
        """
    elif filter_mode == "mastered":
        filter_sql = """
          AND up.word_id IS NOT NULL
          AND COALESCE(up.correct_count, 0) >= 3
          AND COALESCE(up.correct_count, 0) >= COALESCE(up.wrong_count, 0) + 2
        """
    return await pool.fetch(f"""
        SELECT
            w.id,
            w.word,
            w.translation,
            w.transcription,
            w.example,
            w.topic,
            w.age_group,
            COALESCE(up.correct_count, 0)::INT AS correct_count,
            COALESCE(up.wrong_count, 0)::INT AS wrong_count,
            COALESCE(up.review_streak, 0)::INT AS review_streak,
            up.last_seen,
            (
              COALESCE(up.wrong_count, 0) > 0
              AND COALESCE(up.review_streak, 0) < 2
            ) AS needs_review,
            (
              COALESCE(up.correct_count, 0) >= 3
              AND COALESCE(up.correct_count, 0) >= COALESCE(up.wrong_count, 0) + 2
            ) AS mastered
        FROM words w
        LEFT JOIN user_progress up ON up.word_id = w.id AND up.user_id = $1
        WHERE TRUE
        {filter_sql}
        ORDER BY
            needs_review DESC,
            mastered ASC,
            CASE WHEN up.word_id IS NULL THEN 1 ELSE 0 END ASC,
            COALESCE(up.wrong_count, 0) DESC,
            up.last_seen DESC NULLS LAST,
            w.age_group ASC,
            w.word ASC
        LIMIT $2
    """, user_id, limit)


async def get_words_count():
    pool = await _get_pool()
    return await pool.fetchval("SELECT COUNT(*)::INT FROM words")


async def get_dictionary_summary(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT
            COUNT(*)::INT AS total_words,
            COUNT(*) FILTER (
              WHERE COALESCE(correct_count, 0) >= 3
                AND COALESCE(correct_count, 0) >= COALESCE(wrong_count, 0) + 2
            )::INT AS mastered_words,
            COUNT(*) FILTER (
              WHERE COALESCE(wrong_count, 0) > 0
                AND COALESCE(review_streak, 0) < 2
            )::INT AS review_words
        FROM user_progress
        WHERE user_id = $1
    """, user_id)


async def get_problem_words(user_id: int, limit: int = 6):
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT
            w.id,
            w.word,
            w.translation,
            w.transcription,
            w.example,
            w.topic,
            w.age_group,
            COALESCE(up.correct_count, 0)::INT AS correct_count,
            COALESCE(up.wrong_count, 0)::INT AS wrong_count,
            up.last_seen
        FROM user_progress up
        JOIN words w ON w.id = up.word_id
        WHERE up.user_id = $1
          AND COALESCE(up.wrong_count, 0) > 0
        ORDER BY
            COALESCE(up.wrong_count, 0) DESC,
            (COALESCE(up.wrong_count, 0) - COALESCE(up.correct_count, 0)) DESC,
            up.last_seen DESC
        LIMIT $2
    """, user_id, limit)


# ---------- Словарные сессии ----------

async def create_vocabulary_session(user_id: int, age_group: str, topic: str | None, word_ids: list[int]):
    pool = await _get_pool()
    return await pool.fetchrow("""
        INSERT INTO vocabulary_sessions (user_id, topic, age_group, word_ids)
        VALUES ($1, $2, $3, $4)
        RETURNING *
    """, user_id, topic, age_group, word_ids)


async def get_vocabulary_session(session_id: int, user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT * FROM vocabulary_sessions
        WHERE id = $1 AND user_id = $2
    """, session_id, user_id)


async def get_words_by_ids(word_ids: list[int]):
    if not word_ids:
        return []
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT * FROM words
        WHERE id = ANY($1::INTEGER[])
        ORDER BY array_position($1::INTEGER[], id)
    """, word_ids)


async def finish_vocabulary_session(
    session_id: int,
    user_id: int,
    correct_count: int,
    wrong_count: int,
) -> None:
    pool = await _get_pool()
    await pool.execute("""
        UPDATE vocabulary_sessions
        SET
            correct_count = $3,
            wrong_count = $4,
            completed = TRUE,
            completed_at = NOW()
        WHERE id = $1 AND user_id = $2
    """, session_id, user_id, correct_count, wrong_count)


# ---------- Игровые сессии ----------

async def create_game_session(user_id: int, game_type: str, age_group: str, word_ids: list[int]):
    pool = await _get_pool()
    return await pool.fetchrow("""
        INSERT INTO game_sessions (user_id, game_type, age_group, word_ids)
        VALUES ($1, $2, $3, $4)
        RETURNING *
    """, user_id, game_type, age_group, word_ids)


async def get_game_session(session_id: int, user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT * FROM game_sessions
        WHERE id = $1 AND user_id = $2
    """, session_id, user_id)


async def finish_game_session(
    session_id: int,
    user_id: int,
    correct_count: int,
    wrong_count: int,
) -> None:
    pool = await _get_pool()
    await pool.execute("""
        UPDATE game_sessions
        SET
            correct_count = $3,
            wrong_count = $4,
            completed = TRUE,
            completed_at = NOW()
        WHERE id = $1 AND user_id = $2
    """, session_id, user_id, correct_count, wrong_count)


# ---------- Прогресс ----------

async def update_progress(user_id: int, word_id: int, correct: bool) -> None:
    pool = await _get_pool()
    if correct:
        await pool.execute("""
            INSERT INTO user_progress (user_id, word_id, correct_count, review_streak)
            VALUES ($1, $2, 1, 1)
            ON CONFLICT (user_id, word_id)
            DO UPDATE SET correct_count = user_progress.correct_count + 1,
                          review_streak = LEAST(COALESCE(user_progress.review_streak, 0) + 1, 2),
                          last_seen = NOW()
        """, user_id, word_id)
    else:
        await pool.execute("""
            INSERT INTO user_progress (user_id, word_id, wrong_count, review_streak)
            VALUES ($1, $2, 1, 0)
            ON CONFLICT (user_id, word_id)
            DO UPDATE SET wrong_count = user_progress.wrong_count + 1,
                          review_streak = 0,
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


async def get_parent_report(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT
            COALESCE(p.words_learned, 0)::INT AS words_learned,
            COALESCE(p.total_correct, 0)::INT AS total_correct,
            COALESCE(p.total_wrong, 0)::INT AS total_wrong,
            COALESCE(l.completed_lessons, 0)::INT AS completed_lessons,
            COALESCE(v.completed_word_tests, 0)::INT AS completed_word_tests,
            COALESCE(v.avg_word_test_score, 0)::INT AS avg_word_test_score,
            COALESCE(g.completed_games, 0)::INT AS completed_games,
            COALESCE(g.avg_game_score, 0)::INT AS avg_game_score
        FROM users u
        LEFT JOIN (
            SELECT
                user_id,
                COUNT(DISTINCT word_id) AS words_learned,
                SUM(correct_count) AS total_correct,
                SUM(wrong_count) AS total_wrong
            FROM user_progress
            GROUP BY user_id
        ) p ON p.user_id = u.user_id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS completed_lessons
            FROM daily_lessons
            WHERE completed = TRUE
            GROUP BY user_id
        ) l ON l.user_id = u.user_id
        LEFT JOIN (
            SELECT
                user_id,
                COUNT(*) AS completed_word_tests,
                ROUND(AVG(
                    CASE
                        WHEN (correct_count + wrong_count) > 0
                        THEN correct_count::NUMERIC / (correct_count + wrong_count) * 100
                        ELSE NULL
                    END
                ), 0) AS avg_word_test_score
            FROM vocabulary_sessions
            WHERE completed = TRUE
            GROUP BY user_id
        ) v ON v.user_id = u.user_id
        LEFT JOIN (
            SELECT
                user_id,
                COUNT(*) AS completed_games,
                ROUND(AVG(
                    CASE
                        WHEN (correct_count + wrong_count) > 0
                        THEN correct_count::NUMERIC / (correct_count + wrong_count) * 100
                        ELSE NULL
                    END
                ), 0) AS avg_game_score
            FROM game_sessions
            WHERE completed = TRUE
            GROUP BY user_id
        ) g ON g.user_id = u.user_id
        WHERE u.user_id = $1
    """, user_id)


async def get_activity_history(user_id: int, limit: int = 30):
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT *
        FROM (
            SELECT
                'daily_lesson'::TEXT AS event_type,
                COALESCE(completed_at, updated_at, created_at) AS event_at,
                lesson_date::TEXT AS event_date,
                completed,
                completed_steps::INT AS completed_steps,
                NULL::INT AS score,
                NULL::INT AS correct_count,
                NULL::INT AS wrong_count,
                NULL::INT AS word_count,
                rewarded_at IS NOT NULL AS rewarded,
                NULL::TEXT AS game_type
            FROM daily_lessons
            WHERE user_id = $1
              AND (completed = TRUE OR completed_steps > 0)

            UNION ALL

            SELECT
                'word_test'::TEXT AS event_type,
                COALESCE(completed_at, created_at) AS event_at,
                created_at::DATE::TEXT AS event_date,
                completed,
                NULL::INT AS completed_steps,
                CASE
                    WHEN (correct_count + wrong_count) > 0
                    THEN ROUND(correct_count::NUMERIC / (correct_count + wrong_count) * 100)::INT
                    ELSE NULL::INT
                END AS score,
                correct_count::INT,
                wrong_count::INT,
                CARDINALITY(word_ids)::INT AS word_count,
                FALSE AS rewarded,
                NULL::TEXT AS game_type
            FROM vocabulary_sessions
            WHERE user_id = $1
              AND (completed = TRUE OR CARDINALITY(word_ids) > 0)

            UNION ALL

            SELECT
                'word_game'::TEXT AS event_type,
                COALESCE(completed_at, created_at) AS event_at,
                created_at::DATE::TEXT AS event_date,
                completed,
                NULL::INT AS completed_steps,
                CASE
                    WHEN (correct_count + wrong_count) > 0
                    THEN ROUND(correct_count::NUMERIC / (correct_count + wrong_count) * 100)::INT
                    ELSE NULL::INT
                END AS score,
                correct_count::INT,
                wrong_count::INT,
                CARDINALITY(word_ids)::INT AS word_count,
                FALSE AS rewarded,
                game_type
            FROM game_sessions
            WHERE user_id = $1
              AND (completed = TRUE OR CARDINALITY(word_ids) > 0)
        ) events
        ORDER BY event_at DESC
        LIMIT $2
    """, user_id, limit)


async def get_leaderboard(limit: int = 10):
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT
            user_id,
            name,
            age_group,
            points
        FROM users
        ORDER BY points DESC, registered_at ASC
        LIMIT $1
    """, limit)


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


# ---------- Учет расходов ИИ ----------

async def add_ai_usage(
    user_id: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cost_usd: float,
) -> None:
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO ai_usage (
            user_id,
            model,
            input_tokens,
            output_tokens,
            total_tokens,
            cost_usd
        )
        VALUES ($1, $2, $3, $4, $5, $6)
    """, user_id, model, input_tokens, output_tokens, total_tokens, cost_usd)


async def get_ai_usage_today(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("""
        SELECT
            COUNT(*)::INTEGER                    AS requests,
            COALESCE(SUM(input_tokens), 0)::INT  AS input_tokens,
            COALESCE(SUM(output_tokens), 0)::INT AS output_tokens,
            COALESCE(SUM(total_tokens), 0)::INT  AS total_tokens,
            COALESCE(SUM(cost_usd), 0)::FLOAT    AS cost_usd
        FROM ai_usage
        WHERE user_id = $1
          AND created_at >= DATE_TRUNC('day', NOW())
    """, user_id)


# ---------- Ежедневный урок ----------

async def get_daily_lesson_status(user_id: int):
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_lessons (user_id)
            VALUES ($1)
            ON CONFLICT (user_id, lesson_date) DO NOTHING
        """, user_id)
        return await conn.fetchrow("""
            SELECT
                lesson_date::TEXT AS lesson_date,
                completed_steps,
                completed,
                rewarded_at IS NOT NULL AS rewarded
            FROM daily_lessons
            WHERE user_id = $1
              AND lesson_date = CURRENT_DATE
        """, user_id)


async def get_learning_streak(user_id: int) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        today = await conn.fetchval("SELECT CURRENT_DATE")
        rows = await conn.fetch("""
            SELECT lesson_date
            FROM daily_lessons
            WHERE user_id = $1
              AND completed = TRUE
            ORDER BY lesson_date DESC
        """, user_id)

    completed_dates = [row["lesson_date"] for row in rows]
    completed_set = set(completed_dates)

    current_streak = 0
    cursor = today if today in completed_set else today - timedelta(days=1)
    while cursor in completed_set:
        current_streak += 1
        cursor -= timedelta(days=1)

    longest_streak = 0
    run = 0
    previous = None
    for lesson_date in sorted(completed_set):
        if previous is not None and lesson_date == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest_streak = max(longest_streak, run)
        previous = lesson_date

    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "completed_days": len(completed_set),
        "today_completed": today in completed_set,
        "last_completed_date": completed_dates[0].isoformat() if completed_dates else "",
    }


async def update_daily_lesson_progress(user_id: int, completed_steps: int, total_steps: int):
    pool = await _get_pool()
    completed_steps = max(0, min(completed_steps, total_steps))
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_lessons (user_id)
            VALUES ($1)
            ON CONFLICT (user_id, lesson_date) DO NOTHING
        """, user_id)
        return await conn.fetchrow("""
            UPDATE daily_lessons
            SET
                completed_steps = GREATEST(completed_steps, $2),
                completed = GREATEST(completed_steps, $2) >= $3,
                completed_at = CASE
                    WHEN GREATEST(completed_steps, $2) >= $3
                     AND completed_at IS NULL
                    THEN NOW()
                    ELSE completed_at
                END,
                updated_at = NOW()
            WHERE user_id = $1
              AND lesson_date = CURRENT_DATE
            RETURNING
                lesson_date::TEXT AS lesson_date,
                completed_steps,
                completed,
                rewarded_at IS NOT NULL AS rewarded
        """, user_id, completed_steps, total_steps)


async def claim_daily_lesson_reward(user_id: int) -> bool:
    pool = await _get_pool()
    row = await pool.fetchrow("""
        UPDATE daily_lessons
        SET rewarded_at = NOW(),
            updated_at = NOW()
        WHERE user_id = $1
          AND lesson_date = CURRENT_DATE
          AND completed = TRUE
          AND rewarded_at IS NULL
        RETURNING 1
    """, user_id)
    return row is not None
