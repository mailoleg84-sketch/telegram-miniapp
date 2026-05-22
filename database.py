import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")

pool = None


async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            word TEXT,
            translation TEXT
        );
        """)

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)


# ---------------- USERS ----------------

async def get_or_create_user(telegram_id):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id FROM users WHERE telegram_id=$1",
            telegram_id
        )

        if user:
            return user["id"]

        user = await conn.fetchrow(
            "INSERT INTO users (telegram_id) VALUES ($1) RETURNING id",
            telegram_id
        )
        return user["id"]


# ---------------- WORDS ----------------

async def add_word(user_id, word, translation):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO words (user_id, word, translation) VALUES ($1, $2, $3)",
            user_id, word, translation
        )


async def get_words(user_id):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT word, translation FROM words WHERE user_id=$1",
            user_id
        )


# ---------------- CHAT ----------------

async def save_message(user_id, role, content):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content
        )


async def get_history(user_id, limit=20):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT role, content
            FROM conversations
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        """, user_id, limit)

        return list(reversed(rows))


async def clear_history(user_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM conversations WHERE user_id=$1",
            user_id
        )
