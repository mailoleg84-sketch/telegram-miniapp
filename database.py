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
from webapp.vocabulary_visualizer import build_vocabulary_visual

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
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS part_of_speech TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS visual_type TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS image_prompt TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS image_url TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS image_alt TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS example_sentence TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS simple_meaning TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS russian_hint TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS image_confidence REAL DEFAULT 0")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generation_status TEXT DEFAULT 'pending'")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_url TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_prompt_hash TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_review TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_status TEXT DEFAULT 'missing'")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_model TEXT")
        await conn.execute("ALTER TABLE words ADD COLUMN IF NOT EXISTS generated_image_checked_at TIMESTAMP")
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
            CREATE TABLE IF NOT EXISTS voice_lesson_state (
                user_id             BIGINT PRIMARY KEY,
                age_group           TEXT NOT NULL,
                phase               TEXT NOT NULL DEFAULT 'welcome',
                current_topic       TEXT DEFAULT '',
                current_topic_label TEXT DEFAULT '',
                topic_suggestions   TEXT[] NOT NULL DEFAULT '{}',
                lesson_goal         TEXT DEFAULT '',
                target_phrase       TEXT DEFAULT '',
                target_words        TEXT[] NOT NULL DEFAULT '{}',
                turn_count          INTEGER DEFAULT 0,
                correction_count    INTEGER DEFAULT 0,
                last_language       TEXT DEFAULT 'unknown',
                support_mode        TEXT DEFAULT '',
                started_at          TIMESTAMP DEFAULT NOW(),
                updated_at          TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_lesson_sessions (
                id               SERIAL PRIMARY KEY,
                user_id          BIGINT NOT NULL,
                started_at       TIMESTAMP NOT NULL,
                completed_at     TIMESTAMP DEFAULT NOW(),
                age_group        TEXT NOT NULL,
                topic            TEXT NOT NULL,
                topic_label      TEXT DEFAULT '',
                lesson_goal      TEXT DEFAULT '',
                target_phrase    TEXT DEFAULT '',
                target_words     TEXT[] NOT NULL DEFAULT '{}',
                correction_count INTEGER DEFAULT 0,
                last_language    TEXT DEFAULT 'unknown',
                UNIQUE (user_id, started_at)
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS training_attempts (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                mode        TEXT NOT NULL,
                focus       TEXT NOT NULL DEFAULT 'all',
                correct     BOOLEAN NOT NULL,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS training_attempts_user_created_idx
            ON training_attempts (user_id, created_at DESC)
        """)
        # Индексы на горячих путях: история чата, прогресс, дневной урок и
        # выборка слов по возрастной группе (без них — seq scan при росте данных).
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS conversations_user_id_idx
            ON conversations (user_id, id DESC)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS user_progress_user_id_idx
            ON user_progress (user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS daily_lessons_user_id_idx
            ON daily_lessons (user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS words_age_group_idx
            ON words (age_group)
        """)
        await _seed_words(conn)


# Защита в глубину: ни одно из этих слов не попадёт в детский банк, даже если
# просочится в data-файл. Слова не в этом списке также удаляются из БД сидером.
BLOCKED_SEED_WORDS = frozenset({
    "fuck", "fucking", "fucked", "fuckin", "fucker", "motherfucker", "shit", "shitty",
    "bullshit", "crap", "ass", "asshole", "arse", "bitch", "bastard", "dick", "cock",
    "prick", "pussy", "cunt", "slut", "whore", "hoe", "piss", "pissed", "sex", "sexy",
    "sexual", "porn", "porno", "nude", "naked", "penis", "vagina", "boobs", "boob",
    "tits", "nipple", "orgasm", "masturbate", "horny", "erotic", "condom", "rape",
    "rapist", "damn", "goddamn", "nigger", "faggot", "retard",
})


async def _seed_words(conn) -> None:
    source = [item for item in LEARNING_WORDS if item[0].strip().lower() not in BLOCKED_SEED_WORDS]
    active_words = [item[0] for item in source]
    seed_rows = []
    for word, translation, example, topic, age_group, transcription in source:
        visual = build_vocabulary_visual(
            word=word,
            translation=translation,
            example_sentence=example,
            topic=topic,
            age_group=age_group,
        )
        seed_rows.append((
            word,
            translation,
            example,
            topic,
            age_group,
            transcription,
            visual["part_of_speech"],
            visual["visual_type"],
            visual["image_prompt"],
            visual["image_url"],
            visual["image_alt"],
            visual["example_sentence"],
            visual["simple_meaning"],
            visual["russian_hint"],
            visual["image_confidence"],
            visual["needs_review"],
            visual["generation_status"],
        ))
    await conn.executemany(
        """
        INSERT INTO words (
            word,
            translation,
            example,
            topic,
            age_group,
            transcription,
            part_of_speech,
            visual_type,
            image_prompt,
            image_url,
            image_alt,
            example_sentence,
            simple_meaning,
            russian_hint,
            image_confidence,
            needs_review,
            generation_status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
        ON CONFLICT (word)
        DO UPDATE SET
            translation = EXCLUDED.translation,
            transcription = EXCLUDED.transcription,
            example = EXCLUDED.example,
            topic = EXCLUDED.topic,
            age_group = EXCLUDED.age_group,
            part_of_speech = EXCLUDED.part_of_speech,
            visual_type = EXCLUDED.visual_type,
            image_prompt = EXCLUDED.image_prompt,
            image_url = EXCLUDED.image_url,
            image_alt = EXCLUDED.image_alt,
            example_sentence = EXCLUDED.example_sentence,
            simple_meaning = EXCLUDED.simple_meaning,
            russian_hint = EXCLUDED.russian_hint,
            image_confidence = EXCLUDED.image_confidence,
            needs_review = EXCLUDED.needs_review,
            generation_status = EXCLUDED.generation_status
        """,
        seed_rows,
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


def _affected_count(command_status: str) -> int:
    try:
        return int(str(command_status).rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


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
            await conn.execute("DELETE FROM training_attempts WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM voice_lesson_state WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM voice_lesson_sessions WHERE user_id = $1", user_id)


async def delete_user_account(user_id: int) -> None:
    """Полное удаление профиля ребёнка и всех связанных данных (QA H6).

    Удаляет историю диалогов, прогресс, сессии, расход AI и саму строку
    пользователя. Транзакционно, чтобы не осталось «осиротевших» данных.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for table in (
                "user_progress",
                "daily_lessons",
                "vocabulary_sessions",
                "game_sessions",
                "training_attempts",
                "voice_lesson_state",
                "voice_lesson_sessions",
                "conversations",
                "ai_usage",
                "users",
            ):
                await conn.execute(f"DELETE FROM {table} WHERE user_id = $1", user_id)


# ---------- Админка ----------

async def get_admin_overview() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetchrow("""
            SELECT
                COUNT(*)::INT AS total_users,
                COUNT(*) FILTER (WHERE registered_at >= DATE_TRUNC('day', NOW()))::INT AS new_users_today,
                COALESCE(SUM(points), 0)::INT AS total_points
            FROM users
        """)
        active_today = await conn.fetchval("""
            SELECT COUNT(DISTINCT user_id)::INT
            FROM (
                SELECT user_id FROM conversations WHERE created_at >= DATE_TRUNC('day', NOW())
                UNION
                SELECT user_id FROM ai_usage WHERE created_at >= DATE_TRUNC('day', NOW())
                UNION
                SELECT user_id FROM daily_lessons
                WHERE COALESCE(updated_at, created_at) >= DATE_TRUNC('day', NOW())
                UNION
                SELECT user_id FROM vocabulary_sessions WHERE created_at >= DATE_TRUNC('day', NOW())
                UNION
                SELECT user_id FROM game_sessions WHERE created_at >= DATE_TRUNC('day', NOW())
                UNION
                SELECT user_id FROM training_attempts WHERE created_at >= DATE_TRUNC('day', NOW())
            ) activity
        """)
        words = await conn.fetchrow("""
            SELECT
                COUNT(*)::INT AS total_words,
                COUNT(*) FILTER (WHERE generated_image_status = 'generated')::INT AS generated_images,
                COUNT(*) FILTER (WHERE generated_image_status = 'needs_review')::INT AS images_needing_review,
                COUNT(*) FILTER (WHERE generated_image_status = 'failed')::INT AS failed_images,
                COUNT(*) FILTER (
                    WHERE COALESCE(generated_image_status, 'missing') NOT IN ('generated', 'needs_review', 'failed')
                )::INT AS missing_images,
                COUNT(*) FILTER (WHERE needs_review = TRUE)::INT AS semantic_review_words
            FROM words
        """)
        learning = await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*)::INT FROM daily_lessons WHERE completed = TRUE) AS completed_daily_lessons,
                (SELECT COUNT(*)::INT FROM vocabulary_sessions WHERE completed = TRUE) AS completed_word_tests,
                (SELECT COUNT(*)::INT FROM game_sessions WHERE completed = TRUE) AS completed_games,
                (SELECT COUNT(*)::INT FROM training_attempts) AS training_attempts,
                (SELECT COUNT(*)::INT FROM user_progress) AS learned_word_links
        """)
        ai_today = await conn.fetchrow("""
            SELECT
                COUNT(*)::INT AS requests,
                COALESCE(SUM(input_tokens), 0)::INT AS input_tokens,
                COALESCE(SUM(output_tokens), 0)::INT AS output_tokens,
                COALESCE(SUM(total_tokens), 0)::INT AS total_tokens,
                COALESCE(SUM(cost_usd), 0)::FLOAT AS cost_usd
            FROM ai_usage
            WHERE created_at >= DATE_TRUNC('day', NOW())
        """)
    return {
        "users": users,
        "active_today": int(active_today or 0),
        "words": words,
        "learning": learning,
        "ai_today": ai_today,
    }


async def get_admin_users(search: str = "", limit: int = 40):
    pool = await _get_pool()
    query = " ".join(str(search or "").lower().split())[:80]
    return await pool.fetch("""
        SELECT
            u.user_id,
            u.name,
            u.parent_name,
            u.child_age,
            u.age_group,
            u.goal,
            u.english_level,
            u.level_test_score,
            u.level_test_completed_at,
            u.points,
            u.registered_at,
            COALESCE(p.words_learned, 0)::INT AS words_learned,
            COALESCE(p.total_correct, 0)::INT AS total_correct,
            COALESCE(p.total_wrong, 0)::INT AS total_wrong,
            COALESCE(l.completed_lessons, 0)::INT AS completed_lessons,
            COALESCE(v.completed_word_tests, 0)::INT AS completed_word_tests,
            COALESCE(g.completed_games, 0)::INT AS completed_games
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
            SELECT user_id, COUNT(*) AS completed_word_tests
            FROM vocabulary_sessions
            WHERE completed = TRUE
            GROUP BY user_id
        ) v ON v.user_id = u.user_id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS completed_games
            FROM game_sessions
            WHERE completed = TRUE
            GROUP BY user_id
        ) g ON g.user_id = u.user_id
        WHERE
            $1 = ''
            OR LOWER(u.name) LIKE '%' || $1 || '%'
            OR LOWER(COALESCE(u.parent_name, '')) LIKE '%' || $1 || '%'
            OR u.user_id::TEXT LIKE '%' || $1 || '%'
        ORDER BY u.registered_at DESC
        LIMIT $2
    """, query, max(5, min(int(limit or 40), 100)))


async def get_admin_failed_image_words(limit: int = 20):
    pool = await _get_pool()
    return await pool.fetch("""
        SELECT
            id,
            word,
            translation,
            topic,
            age_group,
            generated_image_status,
            generated_image_review,
            generated_image_checked_at
        FROM words
        WHERE generated_image_status = 'failed'
        ORDER BY generated_image_checked_at DESC NULLS LAST, word ASC
        LIMIT $1
    """, max(1, min(int(limit or 20), 100)))


async def reset_failed_generated_images() -> int:
    pool = await _get_pool()
    status = await pool.execute("""
        UPDATE words
        SET generated_image_url = '',
            generated_image_review = NULL,
            generated_image_status = 'missing',
            generated_image_model = NULL,
            generated_image_checked_at = NULL
        WHERE generated_image_status = 'failed'
    """)
    return _affected_count(status)


# ---------- Слова ----------

async def get_word_by_id(word_id: int):
    pool = await _get_pool()
    return await pool.fetchrow("SELECT * FROM words WHERE id = $1", word_id)


async def update_word_generated_image(
    word_id: int,
    *,
    image_url: str,
    prompt_hash: str,
    review_json: str,
    status: str,
    model: str,
) -> None:
    pool = await _get_pool()
    await pool.execute("""
        UPDATE words
        SET generated_image_url = $2,
            generated_image_prompt_hash = $3,
            generated_image_review = $4,
            generated_image_status = $5,
            generated_image_model = $6,
            generated_image_checked_at = NOW()
        WHERE id = $1
    """, word_id, image_url, prompt_hash, review_json, status, model)


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
              AND age_group = $3
            ORDER BY RANDOM()
            LIMIT $2
            """,
            excluded_ids, count - len(rows), age_group,
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
          AND age_group = $3
        ORDER BY RANDOM()
        LIMIT $2
    """, list(seen_ids), count - len(rows), age_group)
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
          AND age_group = $3
        ORDER BY RANDOM()
        LIMIT $2
    """, excluded_ids, count - len(rows), age_group)
    rows.extend(fallback_rows)
    return rows


async def get_practice_word(
    user_id: int,
    exclude_id: int | None = None,
    age_group: str | None = None,
    exclude_ids: list[int] | None = None,
):
    pool = await _get_pool()
    excluded = exclude_ids or []
    return await pool.fetchrow("""
        SELECT w.*
        FROM words w
        LEFT JOIN user_progress up
               ON up.word_id = w.id
              AND up.user_id = $1
        WHERE ($2::INTEGER IS NULL OR w.id != $2)
          AND ($3::TEXT IS NULL OR w.age_group = $3)
          AND (CARDINALITY($4::INTEGER[]) = 0 OR NOT (w.id = ANY($4::INTEGER[])))
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
    """, user_id, exclude_id, age_group, excluded)


async def get_review_word(
    user_id: int,
    exclude_id: int | None = None,
    age_group: str | None = None,
    exclude_ids: list[int] | None = None,
):
    pool = await _get_pool()
    excluded = exclude_ids or []
    return await pool.fetchrow("""
        SELECT w.*
        FROM user_progress up
        JOIN words w ON w.id = up.word_id
        WHERE up.user_id = $1
          AND ($2::INTEGER IS NULL OR w.id != $2)
          AND ($3::TEXT IS NULL OR w.age_group = $3)
          AND (CARDINALITY($4::INTEGER[]) = 0 OR NOT (w.id = ANY($4::INTEGER[])))
          AND COALESCE(up.wrong_count, 0) > 0
          AND COALESCE(up.review_streak, 0) < 2
        ORDER BY
            COALESCE(up.review_streak, 0) ASC,
            COALESCE(up.wrong_count, 0) DESC,
            up.last_seen ASC,
            RANDOM()
        LIMIT 1
    """, user_id, exclude_id, age_group, excluded)


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
              AND completed = TRUE

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
              AND completed = TRUE

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
              AND completed = TRUE

            UNION ALL

            SELECT
                CASE
                    WHEN focus = 'review' THEN 'review_training'::TEXT
                    ELSE 'word_training'::TEXT
                END AS event_type,
                MAX(created_at) AS event_at,
                created_at::DATE::TEXT AS event_date,
                TRUE AS completed,
                NULL::INT AS completed_steps,
                ROUND(
                    COUNT(*) FILTER (WHERE correct)::NUMERIC / COUNT(*) * 100
                )::INT AS score,
                COUNT(*) FILTER (WHERE correct)::INT AS correct_count,
                COUNT(*) FILTER (WHERE NOT correct)::INT AS wrong_count,
                COUNT(*)::INT AS word_count,
                FALSE AS rewarded,
                NULL::TEXT AS game_type
            FROM training_attempts
            WHERE user_id = $1
            GROUP BY created_at::DATE, focus

            UNION ALL

            SELECT
                'level_test'::TEXT AS event_type,
                level_test_completed_at AS event_at,
                level_test_completed_at::DATE::TEXT AS event_date,
                TRUE AS completed,
                NULL::INT AS completed_steps,
                level_test_score::INT AS score,
                NULL::INT AS correct_count,
                NULL::INT AS wrong_count,
                NULL::INT AS word_count,
                FALSE AS rewarded,
                NULL::TEXT AS game_type
            FROM users
            WHERE user_id = $1
              AND level_test_completed_at IS NOT NULL
        ) events
        ORDER BY event_at DESC
        LIMIT $2
    """, user_id, limit)


async def add_training_attempt(user_id: int, mode: str, focus: str, correct: bool) -> None:
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO training_attempts (user_id, mode, focus, correct)
        VALUES ($1, $2, $3, $4)
    """, user_id, mode, focus, correct)


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

async def get_voice_lesson_state(user_id: int):
    pool = await _get_pool()
    return await pool.fetchrow(
        "SELECT * FROM voice_lesson_state WHERE user_id = $1",
        user_id,
    )


async def save_voice_lesson_state(user_id: int, state: dict) -> None:
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO voice_lesson_state (
            user_id,
            age_group,
            phase,
            current_topic,
            current_topic_label,
            topic_suggestions,
            lesson_goal,
            target_phrase,
            target_words,
            turn_count,
            correction_count,
            last_language,
            support_mode,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
        ON CONFLICT (user_id)
        DO UPDATE SET
            age_group = EXCLUDED.age_group,
            phase = EXCLUDED.phase,
            current_topic = EXCLUDED.current_topic,
            current_topic_label = EXCLUDED.current_topic_label,
            topic_suggestions = EXCLUDED.topic_suggestions,
            lesson_goal = EXCLUDED.lesson_goal,
            target_phrase = EXCLUDED.target_phrase,
            target_words = EXCLUDED.target_words,
            turn_count = EXCLUDED.turn_count,
            correction_count = EXCLUDED.correction_count,
            last_language = EXCLUDED.last_language,
            support_mode = EXCLUDED.support_mode,
            updated_at = NOW()
    """,
    user_id,
    state.get("age_group") or "8_10",
    state.get("phase") or "welcome",
    state.get("current_topic") or "",
    state.get("current_topic_label") or "",
    list(state.get("topic_suggestions") or []),
    state.get("lesson_goal") or "",
    state.get("target_phrase") or "",
    list(state.get("target_words") or []),
    int(state.get("turn_count") or 0),
    int(state.get("correction_count") or 0),
    state.get("last_language") or "unknown",
    state.get("support_mode") or "",
    )


async def clear_voice_lesson_state(user_id: int) -> None:
    pool = await _get_pool()
    await pool.execute("DELETE FROM voice_lesson_state WHERE user_id = $1", user_id)


async def save_completed_voice_lesson(user_id: int, state: dict) -> None:
    if not state.get("current_topic") or not state.get("started_at"):
        return
    pool = await _get_pool()
    await pool.execute("""
        INSERT INTO voice_lesson_sessions (
            user_id,
            started_at,
            age_group,
            topic,
            topic_label,
            lesson_goal,
            target_phrase,
            target_words,
            correction_count,
            last_language
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (user_id, started_at)
        DO UPDATE SET
            completed_at = NOW(),
            correction_count = EXCLUDED.correction_count,
            last_language = EXCLUDED.last_language
    """,
    user_id,
    state["started_at"],
    state.get("age_group") or "8_10",
    state.get("current_topic") or "",
    state.get("current_topic_label") or "",
    state.get("lesson_goal") or "",
    state.get("target_phrase") or "",
    list(state.get("target_words") or []),
    int(state.get("correction_count") or 0),
    state.get("last_language") or "unknown",
    )


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


async def get_model_requests_today(user_id: int, model: str) -> int:
    """Сколько раз за сегодня учтён расход по конкретной модели (per-user).

    Используется для суточного лимита дорогих Realtime-сессий: каждая сессия
    учитывается в ai_usage с model = OPENAI_REALTIME_MODEL.
    """
    pool = await _get_pool()
    count = await pool.fetchval("""
        SELECT COUNT(*)::INTEGER
        FROM ai_usage
        WHERE user_id = $1
          AND model = $2
          AND created_at >= DATE_TRUNC('day', NOW())
    """, user_id, model)
    return int(count or 0)


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
    # QA H3: шаг урока двигает СЕРВЕР, а не клиент. Принятый номер шага
    # ограничивается значением «текущий + 1» — нельзя перепрыгнуть на финал и
    # мгновенно забрать награду. Монотонно (GREATEST) и идемпотентно (повторный
    # тот же шаг ничего не меняет).
    pool = await _get_pool()
    completed_steps = max(0, min(completed_steps, total_steps))
    next_steps = "LEAST(GREATEST(completed_steps, LEAST($2, completed_steps + 1)), $3)"
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_lessons (user_id)
            VALUES ($1)
            ON CONFLICT (user_id, lesson_date) DO NOTHING
        """, user_id)
        return await conn.fetchrow(f"""
            UPDATE daily_lessons
            SET
                completed_steps = {next_steps},
                completed = {next_steps} >= $3,
                completed_at = CASE
                    WHEN {next_steps} >= $3
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
