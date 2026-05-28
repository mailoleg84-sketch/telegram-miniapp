"""Real integration smoke test for the Mini App.

Reads BOT_TOKEN, DATABASE_URL and OPENAI_API_KEY from the environment or .env.
Creates a temporary test user, exercises real API handlers and cleans up data.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import database
from config import BOT_TOKEN, DATABASE_URL, OPENAI_API_KEY
from webapp.server import create_app


SMOKE_USER_ID = 998_877_661


def require_env(with_openai: bool) -> None:
    missing = []
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if with_openai and not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing))


def signed_init_data() -> str:
    user = {
        "id": SMOKE_USER_ID,
        "first_name": "Smoke",
        "username": "smoke_test_user",
    }
    payload = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(user, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


async def cleanup_smoke_user() -> None:
    pool = await database._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ai_usage WHERE user_id = $1", SMOKE_USER_ID)
        await conn.execute("DELETE FROM conversations WHERE user_id = $1", SMOKE_USER_ID)
        await conn.execute("DELETE FROM user_progress WHERE user_id = $1", SMOKE_USER_ID)
        await conn.execute("DELETE FROM daily_lessons WHERE user_id = $1", SMOKE_USER_ID)
        await conn.execute("DELETE FROM vocabulary_sessions WHERE user_id = $1", SMOKE_USER_ID)
        await conn.execute("DELETE FROM users WHERE user_id = $1", SMOKE_USER_ID)


async def request_json(client: TestClient, method: str, path: str, headers: dict, body=None) -> dict:
    request = getattr(client, method.lower())
    if body is None:
        response = await request(path, headers=headers)
    else:
        response = await request(path, headers=headers, json=body)
    text = await response.text()
    if response.status >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status}: {text[:500]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_text": text}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-openai", action="store_true", help="make one real OpenAI chat request")
    args = parser.parse_args()

    require_env(args.with_openai)
    await database.init_db()
    await cleanup_smoke_user()

    headers = {"X-Telegram-Init-Data": signed_init_data()}
    client = TestClient(TestServer(create_app()))
    await client.start_server()

    try:
        checks = []

        html = await client.get("/")
        checks.append(("GET /", html.status == 200))

        app_js = await client.get("/static/app.js")
        app_js_text = await app_js.text()
        checks.append((
            "GET /static/app.js",
            app_js.status == 200
            and "renderDailyLesson" in app_js_text
            and "renderTrainingMenu" in app_js_text
            and "renderLeaderboard" in app_js_text,
        ))

        me = await request_json(client, "GET", "/api/me", headers)
        checks.append(("GET /api/me before register", me.get("registered") is False))

        await request_json(client, "POST", "/api/register", headers, {
            "parent_name": "Smoke Parent",
            "child_name": "Smoke Kid",
            "child_age": "9",
            "age_group": "8_10",
            "goal": "school",
        })

        me = await request_json(client, "GET", "/api/me", headers)
        checks.append(("GET /api/me after register", me.get("registered") is True))

        lesson = await request_json(client, "GET", "/api/daily/status", headers)
        checks.append(("GET /api/daily/status", lesson.get("total_steps") == 4))

        word = await request_json(client, "POST", "/api/learn/next", headers, {})
        checks.append(("POST /api/learn/next", bool(word.get("word"))))

        vocab = await request_json(client, "POST", "/api/vocab/start", headers, {})
        checks.append(("POST /api/vocab/start", len(vocab.get("words", [])) >= 4))

        quiz = await request_json(client, "POST", "/api/vocab/quiz", headers, {
            "session_id": vocab["session_id"],
        })
        checks.append(("POST /api/vocab/quiz", len(quiz.get("questions", [])) >= 4))

        vocab_finish = await request_json(client, "POST", "/api/vocab/finish", headers, {
            "session_id": vocab["session_id"],
            "answers": [
                {"word_id": question["word_id"], "selected_id": question["word_id"]}
                for question in quiz["questions"]
            ],
        })
        checks.append(("POST /api/vocab/finish", vocab_finish.get("score") == 100))

        choice = await request_json(client, "POST", "/api/training/choice/next", headers, {})
        checks.append(("POST /api/training/choice/next", len(choice.get("options", [])) >= 2))

        choice_answer = await request_json(client, "POST", "/api/training/choice/answer", headers, {
            "word_id": choice["word_id"],
            "selected_id": choice["word_id"],
        })
        checks.append(("POST /api/training/choice/answer", choice_answer.get("correct") is True))

        input_task = await request_json(client, "POST", "/api/training/input/next", headers, {})
        input_word = await database.get_word_by_id(input_task["word_id"])
        input_answer = await request_json(client, "POST", "/api/training/input/answer", headers, {
            "word_id": input_task["word_id"],
            "answer": input_word["word"],
        })
        checks.append(("POST /api/training/input/answer", input_answer.get("correct") is True))

        daily_done = await request_json(client, "POST", "/api/daily/progress", headers, {
            "completed_steps": 4,
        })
        checks.append(("POST /api/daily/progress", daily_done.get("completed") is True))

        leaderboard = await request_json(client, "GET", "/api/leaderboard", headers)
        checks.append(("GET /api/leaderboard", isinstance(leaderboard.get("leaders"), list)))

        history = await request_json(client, "GET", "/api/chat/history", headers)
        checks.append(("GET /api/chat/history", "usage" in history))

        if args.with_openai:
            chat = await request_json(client, "POST", "/api/chat/send", headers, {
                "message": "Hello! I like apples.",
            })
            chat_reply = chat.get("reply") or ""
            chat_usage = chat.get("usage") or {}
            checks.append((
                "POST /api/chat/send OpenAI",
                bool(chat_reply)
                and not chat_reply.startswith("⚠️")
                and int(chat_usage.get("total_tokens_today") or 0) > 0,
            ))

            speech = await client.post(
                "/api/audio/speech",
                headers=headers,
                json={"text": "Hello! Nice to meet you."},
            )
            speech_bytes = await speech.read()
            checks.append((
                "POST /api/audio/speech OpenAI",
                speech.status == 200
                and speech.headers.get("Content-Type", "").startswith("audio/")
                and len(speech_bytes) > 1000,
            ))

        reset = await request_json(client, "POST", "/api/chat/reset", headers, {})
        checks.append(("POST /api/chat/reset", reset.get("ok") is True))

        failed = [name for name, ok in checks if not ok]
        for name, ok in checks:
            print(f"{'OK' if ok else 'FAIL'} {name}")
        if failed:
            raise SystemExit("Failed checks: " + ", ".join(failed))
        print("Smoke test passed.")
    finally:
        await client.close()
        await cleanup_smoke_user()
        await database.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
