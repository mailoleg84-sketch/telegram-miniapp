"""aiohttp-сервер: статика Mini App + JSON API."""
import asyncio
import base64
from collections import defaultdict, deque
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database
from config import (
    ADMIN_USER_IDS,
    AGE_GROUPS,
    AI_RATE_LIMIT_PER_MINUTE,
    API_RATE_LIMIT_PER_MINUTE,
    APP_VERSION,
    BOT_RUN_MODE,
    CHAT_HISTORY_LIMIT,
    DAILY_LESSON_REWARD_POINTS,
    DAILY_LESSON_STEPS,
    ENGLISH_LEVELS,
    GAME_PERFECT_BONUS_POINTS,
    GAME_POINTS_CORRECT,
    LEARNING_GOALS,
    POINTS_CORRECT,
    POINTS_WRONG,
    TUTOR_DEFAULT_LEVEL,
    WORDS_PER_AGE_GROUP,
    WEBAPP_HOST,
    WEBAPP_PORT,
    WEBAPP_URL,
    OPENAI_IMAGE_MODEL,
)
from webapp.auth import verify_fallback_auth, verify_init_data
from webapp.lesson_engine import (
    advance_lesson_state,
    create_lesson_state,
    lesson_prompt_context,
    public_lesson_state,
)
from webapp.openai_service import (
    chat_reply,
    create_realtime_call,
    create_realtime_client_secret,
    generate_vocabulary_image,
    openai_config_status,
    public_openai_error,
    synthesize_speech,
    transcribe_audio,
)
from webapp.vocabulary_visualizer import build_vocabulary_visual, vocabulary_image_url

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
GENERATED_VOCAB_DIR = STATIC_DIR / "generated" / "vocabulary"
AUDIO_CACHE_DIR = STATIC_DIR / "generated" / "audio"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SDP_BYTES = 512 * 1024
PUBLIC_API_PATHS = {"/api/me", "/api/register"}
AI_API_PATHS = {
    "/api/chat/send",
    "/api/audio/transcribe",
    "/api/audio/speech",
    "/api/voice/text-turn",
    "/api/voice/turn",
    "/api/vocab/image/generate",
    "/api/realtime/token",
    "/api/realtime/call",
}
_rate_buckets: dict[tuple[int, str], deque[float]] = defaultdict(deque)


def _rate_limit_key(path: str) -> str:
    return "ai" if path in AI_API_PATHS else "api"


def _rate_limit_for_key(key: str) -> int:
    return AI_RATE_LIMIT_PER_MINUTE if key == "ai" else API_RATE_LIMIT_PER_MINUTE


def _rate_limit_ok(user_id: int, key: str) -> bool:
    limit = _rate_limit_for_key(key)
    if limit <= 0:
        return True
    now = time.monotonic()
    bucket = _rate_buckets[(user_id, key)]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


TOPIC_IMAGE_STYLES = {
    "animals": ("#eaf7ff", "#2f9df4", "paw"),
    "art": ("#fff0f6", "#ff5c8a", "music"),
    "body": ("#fff3e6", "#ff7a45", "heart"),
    "clothes": ("#f2efff", "#7c5cff", "shirt"),
    "communication": ("#eef8ff", "#2481cc", "bubble"),
    "culture": ("#f4f0ff", "#7c5cff", "book"),
    "everyday": ("#eefaf8", "#2ec4b6", "home"),
    "exams": ("#eef8ff", "#2481cc", "book"),
    "family": ("#fff0f6", "#ff5c8a", "heart"),
    "food": ("#fff7df", "#ff9500", "apple"),
    "friends": ("#fff0f6", "#ff5c8a", "heart"),
    "games": ("#eef8ff", "#2481cc", "game"),
    "grammar": ("#eef8ff", "#2481cc", "book"),
    "health": ("#fff3e6", "#ff7a45", "heart"),
    "hobbies": ("#f4f0ff", "#7c5cff", "game"),
    "home": ("#eefaf8", "#2ec4b6", "home"),
    "jobs": ("#eef8ff", "#2481cc", "book"),
    "learning": ("#eef8ff", "#2481cc", "book"),
    "music": ("#f4f0ff", "#7c5cff", "music"),
    "nature": ("#ecfbef", "#34c759", "sun"),
    "places": ("#eefaf8", "#2ec4b6", "home"),
    "reading": ("#eef8ff", "#2481cc", "book"),
    "school": ("#eef8ff", "#2481cc", "book"),
    "science": ("#eefaf8", "#2ec4b6", "atom"),
    "speaking": ("#eef8ff", "#2481cc", "bubble"),
    "sports": ("#fff7df", "#ff9500", "ball"),
    "stories": ("#f4f0ff", "#7c5cff", "book"),
    "study": ("#eef8ff", "#2481cc", "book"),
    "technology": ("#eef8ff", "#2481cc", "laptop"),
    "time": ("#f2efff", "#7c5cff", "clock"),
    "toys": ("#fff7df", "#ff9500", "game"),
    "transport": ("#eef8ff", "#2481cc", "plane"),
    "travel": ("#eef8ff", "#2481cc", "plane"),
    "work": ("#eef8ff", "#2481cc", "book"),
}


FALLBACK_IMAGE_ICONS = (
    "apple", "paw", "book", "sun", "plane", "home", "game", "laptop",
    "music", "heart", "shirt", "ball", "bubble", "atom", "clock",
)

WORD_ICON_OVERRIDES = {
    "airport": "plane",
    "apple": "apple",
    "baby": "person",
    "banana": "banana",
    "basket": "basket",
    "ball": "ball",
    "beach": "beach",
    "bedroom": "bed",
    "bike": "bike",
    "book": "book",
    "board": "book",
    "boat": "boat",
    "bottle": "bottle",
    "box": "box",
    "bread": "bread",
    "bus": "bus",
    "cake": "cake",
    "camera": "camera",
    "car": "car",
    "cat": "paw",
    "chair": "chair",
    "cheese": "cheese",
    "classroom": "book",
    "clock": "clock",
    "cloud": "cloud",
    "coat": "shirt",
    "computer": "laptop",
    "cookie": "cookie",
    "cup": "cup",
    "dog": "paw",
    "desk": "table",
    "dictionary": "book",
    "dress": "shirt",
    "bird": "paw",
    "duck": "paw",
    "egg": "egg",
    "email": "laptop",
    "farm": "farm",
    "fish": "paw",
    "flower": "flower",
    "folder": "book",
    "football": "ball",
    "frog": "paw",
    "game": "game",
    "garden": "tree",
    "goat": "paw",
    "grandma": "person",
    "grandpa": "person",
    "guitar": "guitar",
    "hat": "shirt",
    "home": "home",
    "homework": "book",
    "horse": "paw",
    "hospital": "hospital",
    "house": "home",
    "juice": "cup",
    "kite": "kite",
    "kitchen": "home",
    "lamp": "lamp",
    "leaf": "tree",
    "lesson": "book",
    "lion": "paw",
    "milk": "milk",
    "moon": "moon",
    "mouse": "paw",
    "movie": "camera",
    "music": "music",
    "notebook": "book",
    "orange": "orange",
    "page": "book",
    "park": "tree",
    "pen": "pencil",
    "pencil": "pencil",
    "phone": "laptop",
    "picture": "camera",
    "pig": "paw",
    "plane": "plane",
    "playground": "game",
    "postcard": "postcard",
    "rabbit": "paw",
    "rain": "rain",
    "river": "river",
    "robot": "robot",
    "school": "book",
    "shoe": "shirt",
    "shirt": "shirt",
    "skateboard": "skateboard",
    "song": "music",
    "star": "star",
    "story": "book",
    "sun": "sun",
    "table": "table",
    "teacher": "person",
    "ticket": "ticket",
    "time": "clock",
    "toy": "game",
    "train": "train",
    "tree": "tree",
    "village": "home",
    "window": "window",
}

PERSON_WORDS = {
    "aunt", "brother", "classmate", "cousin", "dad", "doctor", "friend",
    "mom", "parent", "sister", "uncle",
}

WORD_ICON_OVERRIDES.update({word: "person" for word in PERSON_WORDS})


def _word_image_icon(word: str) -> str:
    return WORD_ICON_OVERRIDES.get(str(word or "").strip().lower(), "")


def _word_image_url(word: str, topic: str = "") -> str:
    clean_word = " ".join(str(word or "").split())[:48]
    clean_topic = " ".join(str(topic or "basic").split())[:32]
    if _word_image_icon(clean_word):
        query = urlencode({
            "w": clean_word,
            "t": clean_topic,
        })
        return f"/word-image.svg?{query}"
    visual = build_vocabulary_visual(
        word=clean_word,
        translation="",
        example_sentence="",
        topic=clean_topic,
    )
    return visual.get("image_url") or vocabulary_image_url(clean_word, visual.get("visual_type", "no_good_visual"), clean_topic)


def _word_image_style(word: str, topic: str, seed: str):
    bg, color, icon = TOPIC_IMAGE_STYLES.get(topic, ("#eef8ff", "#2481cc", ""))
    icon = _word_image_icon(word) or icon
    if not icon or icon == "star":
        icon = FALLBACK_IMAGE_ICONS[int(seed[:2], 16) % len(FALLBACK_IMAGE_ICONS)]
    return bg, color, icon


def _topic_icon_svg(icon: str, color: str) -> str:
    if icon == "apple":
        return f"""
        <circle cx="160" cy="108" r="42" fill="{color}"/>
        <circle cx="130" cy="108" r="38" fill="{color}" opacity=".92"/>
        <path d="M158 62 C174 38 197 39 211 50 C194 74 177 76 158 62Z" fill="#34c759"/>
        <rect x="157" y="50" width="8" height="25" rx="4" fill="#8a5a2b"/>"""
    if icon == "banana":
        return f"""
        <path d="M107 92 C125 186 220 232 305 151 C241 179 170 154 145 72 C132 72 117 78 107 92Z" fill="{color}"/>
        <path d="M111 91 C132 171 220 204 288 153" fill="none" stroke="#fff" stroke-width="10" opacity=".46" stroke-linecap="round"/>
        <path d="M139 69 l-28 16 M306 151 l24 5" stroke="#8a5a2b" stroke-width="10" stroke-linecap="round"/>"""
    if icon == "bread":
        return f"""
        <path d="M100 139 C100 84 132 52 196 52 C260 52 292 84 292 139 V220 H100Z" fill="{color}"/>
        <path d="M124 143 C124 103 146 78 196 78 C246 78 268 103 268 143" fill="none" stroke="#fff" stroke-width="9" opacity=".42"/>
        <path d="M122 171 h150" stroke="#8a5a2b" stroke-width="8" opacity=".35" stroke-linecap="round"/>"""
    if icon == "cake":
        return f"""
        <rect x="100" y="126" width="192" height="102" rx="22" fill="{color}"/>
        <path d="M100 151 C128 132 145 171 174 151 C204 130 219 171 248 151 C270 136 283 146 292 151" fill="#fff" opacity=".78"/>
        <path d="M196 72 v54" stroke="{color}" stroke-width="12" stroke-linecap="round"/>
        <circle cx="196" cy="62" r="14" fill="#ffcc00"/>"""
    if icon == "cheese":
        return f"""
        <path d="M88 185 L282 78 V220 H88Z" fill="{color}"/>
        <circle cx="174" cy="161" r="14" fill="#fff" opacity=".55"/>
        <circle cx="225" cy="133" r="11" fill="#fff" opacity=".5"/>
        <circle cx="238" cy="191" r="17" fill="#fff" opacity=".45"/>"""
    if icon == "cookie":
        return f"""
        <circle cx="196" cy="132" r="82" fill="{color}"/>
        <circle cx="161" cy="101" r="10" fill="#8a5a2b"/>
        <circle cx="218" cy="89" r="9" fill="#8a5a2b"/>
        <circle cx="230" cy="151" r="11" fill="#8a5a2b"/>
        <circle cx="174" cy="168" r="8" fill="#8a5a2b"/>"""
    if icon == "milk":
        return f"""
        <path d="M142 54 h88 l-13 46 v128 h-62 V100Z" fill="{color}"/>
        <path d="M155 116 h62 v72 h-62Z" fill="#fff" opacity=".88"/>
        <path d="M154 54 h74 l-17 25 h-41Z" fill="{color}" opacity=".7"/>"""
    if icon == "egg":
        return f"""
        <ellipse cx="196" cy="132" rx="68" ry="88" fill="{color}"/>
        <ellipse cx="176" cy="102" rx="18" ry="24" fill="#fff" opacity=".35"/>"""
    if icon == "orange":
        return f"""
        <circle cx="196" cy="132" r="76" fill="{color}"/>
        <path d="M195 61 C217 39 247 42 263 59 C240 81 217 83 195 61Z" fill="#34c759"/>
        <path d="M138 132 h116 M196 74 v116 M154 88 C181 105 213 105 239 88 M154 176 C181 159 213 159 239 176" stroke="#fff" stroke-width="7" opacity=".45" fill="none"/>"""
    if icon == "cup":
        return f"""
        <path d="M118 82 h132 v92 c0 37-30 67-66 67s-66-30-66-67Z" fill="{color}"/>
        <path d="M250 111 h33 c21 0 38 17 38 38s-17 38-38 38h-33v-24h31c8 0 14-6 14-14s-6-14-14-14h-31Z" fill="{color}" opacity=".72"/>
        <path d="M142 111 h84" stroke="#fff" stroke-width="9" opacity=".72" stroke-linecap="round"/>"""
    if icon == "basket":
        return f"""
        <path d="M102 120 h188 l-24 98 H126Z" fill="{color}"/>
        <path d="M145 120 C151 76 241 76 247 120" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M128 154 h136 M138 188 h116 M166 123 v92 M220 123 v92" stroke="#fff" stroke-width="7" opacity=".55"/>"""
    if icon == "box":
        return f"""
        <path d="M100 104 h196 v132 H100Z" fill="{color}"/>
        <path d="M100 104 l50-42 h146 l-46 42Z" fill="{color}" opacity=".7"/>
        <path d="M250 104 l46-42 v132 l-46 42Z" fill="{color}" opacity=".55"/>
        <path d="M150 62 l50 42 v132" stroke="#fff" stroke-width="8" opacity=".45"/>"""
    if icon == "paw":
        return f"""
        <circle cx="144" cy="117" r="31" fill="{color}"/>
        <circle cx="106" cy="83" r="17" fill="{color}" opacity=".88"/>
        <circle cx="138" cy="67" r="18" fill="{color}" opacity=".88"/>
        <circle cx="174" cy="75" r="17" fill="{color}" opacity=".88"/>
        <circle cx="201" cy="101" r="16" fill="{color}" opacity=".88"/>"""
    if icon == "book":
        return f"""
        <path d="M88 62 h82 c17 0 30 13 30 30 v82 h-82 c-17 0-30-13-30-30Z" fill="{color}"/>
        <path d="M200 62 h72 c17 0 30 13 30 30 v82 h-72 c-17 0-30-13-30-30Z" fill="{color}" opacity=".72"/>
        <path d="M200 78 v92" stroke="#fff" stroke-width="8" stroke-linecap="round"/>"""
    if icon == "sun":
        return f"""
        <circle cx="176" cy="102" r="43" fill="{color}"/>
        <path d="M70 180 C118 130 170 133 216 180Z" fill="#34c759" opacity=".55"/>
        <path d="M150 180 C198 123 260 126 314 180Z" fill="#2ec4b6" opacity=".42"/>"""
    if icon == "moon":
        return f"""
        <path d="M238 51 C190 67 158 112 158 164 C158 207 181 244 215 264 C146 260 94 204 94 135 C94 65 148 9 218 5 C204 17 196 35 196 58 C196 94 225 123 261 123 C274 123 287 119 297 112 C291 144 270 174 238 193 C255 146 255 93 238 51Z" fill="{color}"/>
        <circle cx="292" cy="58" r="13" fill="{color}" opacity=".55"/>
        <circle cx="320" cy="100" r="8" fill="{color}" opacity=".5"/>"""
    if icon == "star":
        return f"""
        <path d="M196 52 l24 51 l56 8 l-40 40 l9 56 l-49-26 l-50 26 l10-56 l-41-40 l56-8Z" fill="{color}"/>"""
    if icon == "cloud":
        return f"""
        <path d="M104 170 h174 c31 0 56-25 56-56s-25-56-56-56c-8 0-16 2-23 5C239 36 210 20 177 20c-47 0-86 36-90 82c-31 6-55 34-55 67c0 38 31 69 72 69Z" fill="{color}"/>
        <path d="M102 175 h176" stroke="#fff" stroke-width="12" opacity=".6" stroke-linecap="round"/>"""
    if icon == "rain":
        return f"""
        <path d="M111 119 h169c26 0 47-21 47-47s-21-47-47-47c-8 0-16 2-23 6c-15-19-39-31-66-31c-43 0-78 32-83 73c-29 2-52 26-52 56c0 31 25 56 55 56Z" fill="{color}"/>
        <path d="M126 211 l-18 42 M190 211 l-18 42 M254 211 l-18 42" stroke="{color}" stroke-width="13" stroke-linecap="round" opacity=".78"/>"""
    if icon == "tree":
        return f"""
        <circle cx="178" cy="82" r="49" fill="{color}"/>
        <circle cx="138" cy="125" r="44" fill="{color}" opacity=".88"/>
        <circle cx="221" cy="126" r="48" fill="{color}" opacity=".92"/>
        <rect x="168" y="142" width="28" height="87" rx="10" fill="#8a5a2b"/>
        <path d="M114 227 h166" stroke="#34c759" stroke-width="18" stroke-linecap="round" opacity=".45"/>"""
    if icon == "flower":
        return f"""
        <circle cx="196" cy="122" r="22" fill="#ffcc00"/>
        <circle cx="196" cy="78" r="30" fill="{color}"/>
        <circle cx="196" cy="166" r="30" fill="{color}" opacity=".86"/>
        <circle cx="152" cy="122" r="30" fill="{color}" opacity=".92"/>
        <circle cx="240" cy="122" r="30" fill="{color}" opacity=".92"/>
        <path d="M196 180 v70" stroke="#34c759" stroke-width="15" stroke-linecap="round"/>
        <path d="M195 214 C158 196 139 211 122 240" fill="none" stroke="#34c759" stroke-width="12" stroke-linecap="round"/>"""
    if icon == "river":
        return f"""
        <path d="M80 76 C142 100 151 145 122 190 C175 171 214 197 233 252 C246 198 290 165 330 150" fill="none" stroke="{color}" stroke-width="34" stroke-linecap="round"/>
        <path d="M75 204 C139 174 202 203 250 240" fill="none" stroke="#34c759" stroke-width="18" stroke-linecap="round" opacity=".42"/>"""
    if icon == "beach":
        return f"""
        <path d="M72 205 C133 160 237 160 320 210 V252 H72Z" fill="#ffcc66"/>
        <path d="M70 181 C146 151 244 151 326 181" stroke="{color}" stroke-width="16" stroke-linecap="round" fill="none"/>
        <circle cx="128" cy="72" r="34" fill="{color}"/>"""
    if icon == "farm":
        return f"""
        <path d="M88 135 l78-62 l78 62 v89 H88Z" fill="{color}"/>
        <path d="M142 224 v-58 h48 v58" fill="#fff" opacity=".9"/>
        <path d="M68 245 C132 215 221 215 306 245" stroke="#34c759" stroke-width="20" stroke-linecap="round"/>"""
    if icon == "plane":
        return f"""
        <path d="M74 132 L305 55 L242 188 L195 142 L135 181 L157 121Z" fill="{color}"/>
        <path d="M157 121 L305 55 L195 142" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".75"/>"""
    if icon == "car":
        return f"""
        <path d="M90 132 l34-54 h144 l34 54 v54 H90Z" fill="{color}"/>
        <path d="M139 94 h114 l20 38 H118Z" fill="#fff" opacity=".72"/>
        <circle cx="133" cy="190" r="24" fill="#1f2933"/>
        <circle cx="259" cy="190" r="24" fill="#1f2933"/>"""
    if icon == "bus":
        return f"""
        <rect x="82" y="70" width="228" height="138" rx="25" fill="{color}"/>
        <path d="M108 96 h176 v55 H108Z" fill="#fff" opacity=".78"/>
        <path d="M164 96 v55 M224 96 v55" stroke="{color}" stroke-width="8" opacity=".55"/>
        <circle cx="130" cy="211" r="22" fill="#1f2933"/>
        <circle cx="262" cy="211" r="22" fill="#1f2933"/>"""
    if icon == "train":
        return f"""
        <rect x="108" y="54" width="176" height="162" rx="26" fill="{color}"/>
        <path d="M132 82 h128 v58 H132Z" fill="#fff" opacity=".78"/>
        <path d="M150 237 l28-35 M242 237 l-28-35" stroke="{color}" stroke-width="14" stroke-linecap="round"/>
        <circle cx="154" cy="172" r="12" fill="#fff"/>
        <circle cx="238" cy="172" r="12" fill="#fff"/>"""
    if icon == "bike":
        return f"""
        <circle cx="123" cy="184" r="45" fill="none" stroke="{color}" stroke-width="13"/>
        <circle cx="270" cy="184" r="45" fill="none" stroke="{color}" stroke-width="13"/>
        <path d="M123 184 l52-70 h48 l47 70 M175 114 l36 70 h-88" fill="none" stroke="{color}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M210 91 h44" stroke="{color}" stroke-width="12" stroke-linecap="round"/>"""
    if icon == "skateboard":
        return f"""
        <path d="M91 159 C139 196 253 196 301 159" fill="none" stroke="{color}" stroke-width="24" stroke-linecap="round"/>
        <circle cx="132" cy="198" r="20" fill="#1f2933"/>
        <circle cx="260" cy="198" r="20" fill="#1f2933"/>
        <path d="M118 145 C164 165 228 165 274 145" fill="none" stroke="#fff" stroke-width="8" opacity=".48" stroke-linecap="round"/>"""
    if icon == "boat":
        return f"""
        <path d="M86 153 h222 l-38 64 H124Z" fill="{color}"/>
        <path d="M183 58 v96" stroke="{color}" stroke-width="13" stroke-linecap="round"/>
        <path d="M193 67 l78 70 h-78Z" fill="{color}" opacity=".72"/>
        <path d="M75 232 C122 214 168 214 215 232 C255 247 293 247 330 232" fill="none" stroke="#2ec4b6" stroke-width="13" stroke-linecap="round"/>"""
    if icon == "home":
        return f"""
        <path d="M88 132 L184 58 L280 132 V210 H106 V132Z" fill="{color}"/>
        <path d="M154 210 V152 H214 V210" fill="#fff" opacity=".9"/>
        <path d="M74 136 L184 50 L294 136" fill="none" stroke="{color}" stroke-width="18" stroke-linecap="round"/>"""
    if icon == "chair":
        return f"""
        <path d="M122 70 h130 v88 H122Z" fill="{color}"/>
        <path d="M108 151 h158 v32 H108Z" fill="{color}" opacity=".78"/>
        <path d="M132 183 v58 M242 183 v58" stroke="{color}" stroke-width="15" stroke-linecap="round"/>"""
    if icon == "table":
        return f"""
        <path d="M92 106 h208 v38 H92Z" fill="{color}"/>
        <path d="M122 144 v90 M270 144 v90" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M124 184 h146" stroke="{color}" stroke-width="12" opacity=".55"/>"""
    if icon == "lamp":
        return f"""
        <path d="M139 62 h114 l34 88 H105Z" fill="{color}"/>
        <path d="M196 150 v72" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M142 228 h108" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <path d="M132 150 h128" stroke="#fff" stroke-width="8" opacity=".56"/>"""
    if icon == "window":
        return f"""
        <rect x="104" y="68" width="184" height="156" rx="16" fill="{color}"/>
        <path d="M196 72 v148 M108 146 h176" stroke="#fff" stroke-width="11" opacity=".86"/>
        <path d="M88 238 h216" stroke="{color}" stroke-width="15" stroke-linecap="round" opacity=".65"/>"""
    if icon == "bed":
        return f"""
        <path d="M90 112 h92 c24 0 43 19 43 43 v34 H90Z" fill="{color}"/>
        <path d="M90 82 h42 v73 H90Z" fill="{color}" opacity=".72"/>
        <path d="M86 188 h226 v45" stroke="{color}" stroke-width="17" stroke-linecap="round"/>
        <rect x="142" y="122" width="56" height="33" rx="13" fill="#fff" opacity=".75"/>"""
    if icon == "bottle":
        return f"""
        <path d="M166 52 h60 v37 l25 36 v102 c0 18-15 33-33 33h-44c-18 0-33-15-33-33V125l25-36Z" fill="{color}"/>
        <rect x="173" y="51" width="46" height="23" rx="8" fill="{color}" opacity=".72"/>
        <path d="M158 144 h76 v60 h-76Z" fill="#fff" opacity=".72"/>"""
    if icon == "game":
        return f"""
        <rect x="88" y="94" width="216" height="92" rx="38" fill="{color}"/>
        <circle cx="144" cy="139" r="13" fill="#fff"/>
        <path d="M128 139 h32 M144 123 v32" stroke="#fff" stroke-width="8" stroke-linecap="round"/>
        <circle cx="244" cy="128" r="10" fill="#fff"/>
        <circle cx="270" cy="151" r="10" fill="#fff"/>"""
    if icon == "robot":
        return f"""
        <rect x="108" y="86" width="176" height="126" rx="30" fill="{color}"/>
        <path d="M196 86 v-38" stroke="{color}" stroke-width="14" stroke-linecap="round"/>
        <circle cx="156" cy="142" r="13" fill="#fff"/>
        <circle cx="236" cy="142" r="13" fill="#fff"/>
        <path d="M162 181 h68" stroke="#fff" stroke-width="10" stroke-linecap="round"/>"""
    if icon == "kite":
        return f"""
        <path d="M198 54 l76 88 l-76 88 l-76-88Z" fill="{color}"/>
        <path d="M198 54 v176 M122 142 h152" stroke="#fff" stroke-width="8" opacity=".72"/>
        <path d="M198 230 C168 254 229 274 196 302" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round"/>"""
    if icon == "laptop":
        return f"""
        <rect x="95" y="72" width="202" height="122" rx="15" fill="{color}"/>
        <rect x="118" y="94" width="156" height="78" rx="8" fill="#fff" opacity=".88"/>
        <path d="M70 206 h252 l-28 31 H98Z" fill="{color}" opacity=".72"/>"""
    if icon == "camera":
        return f"""
        <rect x="90" y="92" width="212" height="132" rx="28" fill="{color}"/>
        <path d="M139 92 l19-29 h76 l19 29Z" fill="{color}" opacity=".75"/>
        <circle cx="196" cy="158" r="43" fill="#fff" opacity=".86"/>
        <circle cx="196" cy="158" r="24" fill="{color}"/>
        <circle cx="268" cy="121" r="10" fill="#fff"/>"""
    if icon == "postcard":
        return f"""
        <rect x="92" y="78" width="208" height="134" rx="18" fill="{color}"/>
        <path d="M116 104 h72 M116 132 h72 M116 160 h48" stroke="#fff" stroke-width="9" opacity=".75" stroke-linecap="round"/>
        <rect x="220" y="104" width="48" height="40" rx="8" fill="#fff" opacity=".78"/>
        <path d="M212 82 v126" stroke="#fff" stroke-width="7" opacity=".42"/>"""
    if icon == "ticket":
        return f"""
        <path d="M86 116 h220 v39 c-17 5-29 20-29 39s12 34 29 39v35H86v-35c17-5 29-20 29-39s-12-34-29-39Z" fill="{color}"/>
        <path d="M164 127 v130" stroke="#fff" stroke-width="8" opacity=".55" stroke-dasharray="12 12"/>
        <path d="M194 157 h66 M194 195 h48" stroke="#fff" stroke-width="9" opacity=".72" stroke-linecap="round"/>"""
    if icon == "music":
        return f"""
        <path d="M210 62 v126" stroke="{color}" stroke-width="18" stroke-linecap="round"/>
        <path d="M210 70 l74 24 v34 l-74-24Z" fill="{color}"/>
        <circle cx="174" cy="190" r="34" fill="{color}"/>"""
    if icon == "guitar":
        return f"""
        <path d="M155 119 C128 106 99 121 89 149 C77 183 103 218 139 213 C145 248 184 269 214 247 C238 230 240 198 221 178 C254 169 267 132 247 105 C229 81 196 77 174 95 Z" fill="{color}"/>
        <path d="M218 98 l72-55" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <circle cx="164" cy="169" r="25" fill="#fff" opacity=".86"/>
        <path d="M140 204 L260 72" stroke="#fff" stroke-width="6" opacity=".72"/>"""
    if icon == "heart":
        return f"""
        <path d="M196 199 C108 145 83 107 111 75 C136 46 176 59 196 91 C216 59 256 46 281 75 C309 107 284 145 196 199Z" fill="{color}"/>"""
    if icon == "person":
        return f"""
        <circle cx="196" cy="88" r="43" fill="{color}"/>
        <path d="M105 235 C118 178 151 147 196 147 C241 147 274 178 287 235Z" fill="{color}" opacity=".78"/>
        <path d="M151 102 C170 123 224 123 242 102" stroke="#fff" stroke-width="8" opacity=".6" stroke-linecap="round"/>"""
    if icon == "hospital":
        return f"""
        <path d="M100 86 h192 v146 H100Z" fill="{color}"/>
        <path d="M174 114 h44 v32 h32 v44 h-32 v32 h-44 v-32 h-32 v-44 h32Z" fill="#fff"/>
        <path d="M82 232 h228" stroke="{color}" stroke-width="16" stroke-linecap="round" opacity=".7"/>"""
    if icon == "shirt":
        return f"""
        <path d="M132 62 l37 22 h54 l37-22 l54 50 l-38 42 l-24-21 v94 H140 v-94 l-24 21 l-38-42Z" fill="{color}"/>"""
    if icon == "pencil":
        return f"""
        <path d="M105 215 l29-75 L258 57 l51 51 l-123 83Z" fill="{color}"/>
        <path d="M258 57 l31-21 l41 41 l-21 31Z" fill="#8a5a2b"/>
        <path d="M105 215 l64-24 l-40-40Z" fill="#ffcc66"/>
        <path d="M142 140 l51 51" stroke="#fff" stroke-width="9" opacity=".7"/>"""
    if icon == "ball":
        return f"""
        <circle cx="196" cy="130" r="76" fill="{color}"/>
        <path d="M137 82 C171 103 217 103 255 82 M132 178 C171 154 222 154 260 178 M196 55 C180 91 180 165 196 205 M196 55 C214 94 214 166 196 205" fill="none" stroke="#fff" stroke-width="7" opacity=".78"/>"""
    if icon == "bubble":
        return f"""
        <path d="M95 82 h202 c23 0 41 18 41 41 v30 c0 23-18 41-41 41 h-86 l-62 42 v-42 H95 c-23 0-41-18-41-41 v-30 c0-23 18-41 41-41Z" fill="{color}"/>
        <circle cx="142" cy="138" r="9" fill="#fff"/><circle cx="196" cy="138" r="9" fill="#fff"/><circle cx="250" cy="138" r="9" fill="#fff"/>"""
    if icon == "atom":
        return f"""
        <circle cx="196" cy="130" r="16" fill="{color}"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10" transform="rotate(60 196 130)"/>
        <ellipse cx="196" cy="130" rx="100" ry="35" fill="none" stroke="{color}" stroke-width="10" transform="rotate(120 196 130)"/>"""
    if icon == "clock":
        return f"""
        <circle cx="196" cy="130" r="76" fill="{color}"/>
        <path d="M196 84 v51 l42 25" stroke="#fff" stroke-width="12" stroke-linecap="round" fill="none"/>"""
    return f"""
    <path d="M196 52 l24 51 l56 8 l-40 40 l9 56 l-49-26 l-50 26 l10-56 l-41-40 l56-8Z" fill="{color}"/>"""


def _word_image_svg(word: str, topic: str) -> str:
    clean_word = " ".join(str(word or "word").split())[:48]
    clean_topic = " ".join(str(topic or "basic").split())[:32]
    seed = hashlib.sha1(f"{clean_word}:{clean_topic}".encode("utf-8")).hexdigest()
    bg, color, icon = _word_image_style(clean_word, clean_topic, seed)
    accent = f"#{seed[:6]}"
    icon_svg = _topic_icon_svg(icon, color)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="word picture">
  <rect width="512" height="512" rx="54" fill="{bg}"/>
  <circle cx="426" cy="78" r="54" fill="{accent}" opacity=".14"/>
  <circle cx="80" cy="420" r="78" fill="{color}" opacity=".10"/>
  <circle cx="256" cy="256" r="168" fill="#fff" opacity=".72"/>
  <g transform="translate(60 126) scale(1.02)">{icon_svg}</g>
</svg>"""


def _vocabulary_visual_svg(word: str, topic: str, visual_type: str) -> str:
    clean_word = " ".join(str(word or "word").split()).lower()[:48]
    clean_topic = " ".join(str(topic or "basic").split()).lower()[:32]
    clean_type = " ".join(str(visual_type or "object").split()).lower()
    seed = hashlib.sha1(f"{clean_word}:{clean_topic}:{clean_type}".encode("utf-8")).hexdigest()
    bg, color, icon = _word_image_style(clean_word, clean_topic, seed)
    accent = f"#{seed[:6]}"
    icon_svg = _topic_icon_svg(icon, color)

    def panel(x: int, y: int, w: int = 156, h: int = 210) -> str:
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="28" fill="#fff" opacity=".82" stroke="{color}" stroke-opacity=".14"/>'

    if clean_type == "object":
        return _word_image_svg(clean_word, clean_topic)
    if clean_type == "action":
        scene = f"""
        <circle cx="190" cy="128" r="36" fill="{color}"/>
        <path d="M190 164 l-38 70 M190 164 l50 58 M188 178 l-65 10 M188 178 l76-22" stroke="{color}" stroke-width="18" stroke-linecap="round"/>
        <path d="M78 218 C124 202 166 202 214 218 C250 230 294 230 334 218" fill="none" stroke="#34c759" stroke-width="14" opacity=".55" stroke-linecap="round"/>
        <path d="M92 124 h46 M78 164 h54 M280 106 h42" stroke="{accent}" stroke-width="12" opacity=".42" stroke-linecap="round"/>
        <g transform="translate(214 62) scale(.42)">{icon_svg}</g>"""
    elif clean_type == "contrast":
        scene = f"""
        <circle cx="156" cy="174" r="82" fill="{color}" opacity=".86"/>
        <circle cx="286" cy="205" r="34" fill="{accent}" opacity=".62"/>
        <path d="M108 274 h220" stroke="#34c759" stroke-width="14" opacity=".45" stroke-linecap="round"/>
        <path d="M130 130 C146 106 176 106 193 130" fill="none" stroke="#fff" stroke-width="9" opacity=".6" stroke-linecap="round"/>"""
    elif clean_type == "emotion":
        mouth = "M162 174 C178 206 226 206 242 174" if clean_word not in {"sad", "angry", "scared", "worried", "tired"} else "M162 199 C182 176 222 176 242 199"
        brows = "M139 120 l45-12 M208 108 l45 12" if clean_word in {"angry", "worried"} else "M139 110 h45 M208 110 h45"
        scene = f"""
        <circle cx="196" cy="164" r="96" fill="{color}" opacity=".9"/>
        <circle cx="160" cy="148" r="12" fill="#1f2933"/>
        <circle cx="232" cy="148" r="12" fill="#1f2933"/>
        <path d="{mouth}" fill="none" stroke="#1f2933" stroke-width="12" stroke-linecap="round"/>
        <path d="{brows}" stroke="#1f2933" stroke-width="9" stroke-linecap="round" opacity=".7"/>
        <circle cx="302" cy="88" r="34" fill="{accent}" opacity=".18"/>"""
    elif clean_type == "spatial_relation":
        positions = {
            "in": (180, 160),
            "on": (190, 88),
            "under": (190, 248),
            "behind": (146, 156),
            "between": (196, 160),
            "above": (190, 70),
        }
        bx, by = positions.get(clean_word, (196, 160))
        extra_box = '<rect x="252" y="128" width="90" height="90" rx="16" fill="#bfe7ff" stroke="#2481cc" stroke-width="8" opacity=".72"/>' if clean_word == "between" else ""
        scene = f"""
        <rect x="112" y="126" width="132" height="112" rx="22" fill="#dff3ff" stroke="{color}" stroke-width="10"/>
        {extra_box}
        <circle cx="{bx}" cy="{by}" r="34" fill="{accent}"/>
        <path d="M92 276 h230" stroke="#34c759" stroke-width="14" opacity=".42" stroke-linecap="round"/>"""
    elif clean_type == "situation":
        if clean_word == "honest":
            prop = '<rect x="186" y="166" width="48" height="34" rx="8" fill="#8a5a2b"/><circle cx="222" cy="176" r="6" fill="#ffcc00"/>'
        elif clean_word == "careful":
            prop = '<path d="M184 150 h54 v74 c0 15-12 27-27 27s-27-12-27-27Z" fill="#bfe7ff" stroke="#2481cc" stroke-width="7"/><path d="M190 184 h42" stroke="#fff" stroke-width="8" opacity=".8"/>'
        elif clean_word == "proud":
            prop = '<rect x="168" y="135" width="74" height="60" rx="10" fill="#fff" stroke="#ffcc00" stroke-width="8"/><circle cx="205" cy="165" r="15" fill="#ffcc00"/>'
        elif clean_word == "worried":
            prop = '<circle cx="218" cy="152" r="38" fill="#fff" stroke="#7c5cff" stroke-width="8"/><path d="M218 130 v25 l18 12" stroke="#7c5cff" stroke-width="8" stroke-linecap="round"/>'
        else:
            prop = '<path d="M196 158 C154 126 113 164 144 202 C163 226 186 223 196 245 C206 223 229 226 248 202 C279 164 238 126 196 158Z" fill="#ff5c8a"/>'
        scene = f"""
        <circle cx="136" cy="124" r="34" fill="{color}"/>
        <path d="M82 248 C92 196 111 168 136 168 C164 168 184 197 194 248Z" fill="{color}" opacity=".78"/>
        <circle cx="270" cy="124" r="34" fill="{accent}" opacity=".7"/>
        <path d="M216 248 C226 196 245 168 270 168 C298 168 318 197 328 248Z" fill="{accent}" opacity=".5"/>
        {prop}
        <path d="M118 270 h172" stroke="#34c759" stroke-width="13" opacity=".38" stroke-linecap="round"/>"""
    elif clean_type == "cause_effect":
        scene = f"""
        {panel(74, 66)}{panel(244, 66)}
        <path d="M104 120 h95c21 0 38-17 38-38s-17-38-38-38c-7 0-14 2-20 5c-12-18-33-29-56-29c-36 0-65 27-69 62c-24 3-42 23-42 47c0 26 21 47 47 47Z" fill="{color}" opacity=".78"/>
        <path d="M112 190 l-13 31 M162 190 l-13 31 M210 190 l-13 31" stroke="{color}" stroke-width="9" stroke-linecap="round"/>
        <circle cx="306" cy="122" r="31" fill="{accent}" opacity=".72"/>
        <path d="M306 153 v58 M306 170 l-42 36 M306 170 l42 36" stroke="{accent}" stroke-width="13" stroke-linecap="round"/>
        <path d="M206 172 h48" stroke="#1f2933" stroke-width="10" opacity=".35" stroke-linecap="round"/>"""
    elif clean_type == "two_panel_comic":
        scene = f"""
        {panel(72, 58)}{panel(246, 58)}
        <path d="M104 116 h104c18 0 32-14 32-32s-14-32-32-32c-7 0-14 2-20 6c-11-16-29-26-50-26c-33 0-60 24-65 57" fill="{color}" opacity=".7"/>
        <path d="M114 170 l-12 30 M158 170 l-12 30 M202 170 l-12 30" stroke="{color}" stroke-width="8" stroke-linecap="round"/>
        <circle cx="320" cy="124" r="55" fill="#ffcc00"/>
        <circle cx="302" cy="110" r="7" fill="#1f2933"/><circle cx="338" cy="110" r="7" fill="#1f2933"/>
        <path d="M298 136 C311 154 334 154 347 136" fill="none" stroke="#1f2933" stroke-width="8" stroke-linecap="round"/>
        <path d="M224 162 h38" stroke="#1f2933" stroke-width="10" opacity=".22" stroke-linecap="round"/>"""
    elif clean_type == "grammar_diagram":
        scene = f"""
        <circle cx="156" cy="126" r="35" fill="{color}"/>
        <path d="M156 160 v68 M156 182 l-52 40 M156 182 l62 34" stroke="{color}" stroke-width="16" stroke-linecap="round"/>
        <circle cx="272" cy="196" r="48" fill="none" stroke="{accent}" stroke-width="14"/>
        <path d="M250 160 C262 128 301 128 314 160" fill="{accent}" opacity=".55"/>
        <path d="M245 106 C262 78 304 78 321 106" fill="none" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>
        <path d="M103 262 h205" stroke="#34c759" stroke-width="14" opacity=".4" stroke-linecap="round"/>"""
    else:
        scene = f"""
        <rect x="102" y="86" width="188" height="140" rx="24" fill="#fff" stroke="{color}" stroke-width="10" opacity=".86"/>
        <circle cx="328" cy="118" r="38" fill="{accent}" opacity=".32"/>
        <path d="M138 132 h82 M138 170 h118" stroke="{color}" stroke-width="13" stroke-linecap="round" opacity=".28"/>
        <g transform="translate(144 142) scale(.38)">{icon_svg}</g>
        <path d="M92 260 h220" stroke="#34c759" stroke-width="14" opacity=".38" stroke-linecap="round"/>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512" role="img" aria-label="vocabulary visual scene">
  <rect width="512" height="512" rx="54" fill="{bg}"/>
  <circle cx="428" cy="80" r="58" fill="{accent}" opacity=".12"/>
  <circle cx="84" cy="418" r="82" fill="{color}" opacity=".09"/>
  <circle cx="256" cy="256" r="176" fill="#fff" opacity=".64"/>
  <g transform="translate(60 94) scale(1.02)">{scene}</g>
</svg>"""


# ---------- Middleware ----------

@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Проверяет initData для всех /api/* эндпоинтов."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = verify_init_data(init_data)
    if not parsed:
        parsed = verify_fallback_auth(request.headers.get("X-App-Fallback-Auth", ""))
    if not parsed or "user" not in parsed:
        return web.json_response({"error": "unauthorized"}, status=401)

    request["tg_user"] = parsed["user"]
    user_id = int(parsed["user"]["id"])
    key = _rate_limit_key(request.path)
    if not _rate_limit_ok(user_id, key):
        return web.json_response({
            "error": "Слишком много запросов. Подожди минуту и попробуй снова.",
        }, status=429)
    if request.path not in PUBLIC_API_PATHS and not await database.user_exists(user_id):
        return web.json_response({"error": "Сначала нужно зарегистрироваться"}, status=403)
    return await handler(request)


# ---------- Helpers ----------

def _vocabulary_image_prompt_hash(visual: dict) -> str:
    payload = {
        key: str(visual.get(key) or "")
        for key in (
            "word",
            "translation",
            "visual_type",
            "image_prompt",
            "example_sentence",
            "simple_meaning",
            "russian_hint",
        )
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _generated_vocab_url_exists(url: str) -> bool:
    if not url or not url.startswith("/static/generated/vocabulary/"):
        return False
    filename = url.rsplit("/", 1)[-1]
    if not filename or "/" in filename or "\\" in filename:
        return False
    return (GENERATED_VOCAB_DIR / filename).is_file()


def _generated_vocab_extension(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get((content_type or "").lower(), "png")


def _generated_vocab_static_url(filename: str) -> str:
    return f"/static/generated/vocabulary/{filename}"


def _cacheable_word_audio(text: str, mode: str) -> bool:
    clean_text = " ".join(str(text or "").split())
    return mode == "word" and 0 < len(clean_text) <= 120


def _word_audio_cache_path(text: str, mode: str, speed) -> Path | None:
    if not _cacheable_word_audio(text, mode):
        return None
    clean_text = " ".join(str(text or "").split()).lower()
    speed_key = "" if speed in (None, "") else str(speed)
    raw = json.dumps({
        "mode": mode,
        "text": clean_text,
        "speed": speed_key,
        "format": "mp3",
        "v": 1,
    }, ensure_ascii=False, sort_keys=True)
    return AUDIO_CACHE_DIR / f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.mp3"


def _word_dict(word, learner_level: str = "beginner") -> dict:
    if not word:
        return {}
    def value(key: str, default=""):
        try:
            item = word[key]
        except (KeyError, IndexError, TypeError):
            return default
        return default if item is None else item

    transcription = value("transcription", "")
    topic = word["topic"] or "basic"
    visual = build_vocabulary_visual(
        word=value("word", ""),
        translation=value("translation", ""),
        example_sentence=value("example", ""),
        topic=topic,
        age_group=value("age_group", ""),
        level=learner_level,
    )
    visual.update({
        "word": value("word", ""),
        "translation": value("translation", ""),
    })
    fallback_image_url = visual["image_url"]
    image_prompt_hash = _vocabulary_image_prompt_hash(visual)
    generated_image_url = value("generated_image_url", "")
    generated_image_status = value("generated_image_status", "missing") or "missing"
    generated_prompt_hash = value("generated_image_prompt_hash", "")
    if (
        generated_image_url
        and generated_prompt_hash == image_prompt_hash
        and generated_image_status in {"generated", "needs_review"}
        and _generated_vocab_url_exists(generated_image_url)
    ):
        image_url = generated_image_url
    else:
        image_url = fallback_image_url
        if generated_image_status in {"generated", "needs_review"}:
            generated_image_status = "missing"

    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": transcription,
        "example": word["example"] or "",
        "topic": topic,
        "age_group": word["age_group"] or "",
        "part_of_speech": visual["part_of_speech"],
        "visual_type": visual["visual_type"],
        "image_prompt": visual["image_prompt"],
        "image_url": image_url,
        "fallback_image_url": fallback_image_url,
        "generated_image_url": generated_image_url if image_url == generated_image_url else "",
        "image_can_generate": True,
        "image_generation_status": generated_image_status,
        "image_prompt_hash": image_prompt_hash,
        "image_alt": visual["image_alt"],
        "example_sentence": visual["example_sentence"],
        "simple_meaning": visual["simple_meaning"],
        "russian_hint": visual["russian_hint"],
        "image_confidence": visual["image_confidence"],
        "image_needs_review": visual["needs_review"],
        "needs_review": visual["needs_review"],
        "generation_status": visual["generation_status"],
        "show_russian_hint": visual["show_russian_hint"],
    }


def _dictionary_word_dict(word) -> dict:
    data = _word_dict(word)
    correct_count = int(word["correct_count"] or 0)
    wrong_count = int(word["wrong_count"] or 0)
    mastered = bool(word["mastered"])
    needs_review = bool(word["needs_review"])
    if mastered:
        status = "mastered"
        status_label = "выучено"
    elif needs_review:
        status = "review"
        status_label = "повторить"
    else:
        status = "learning"
        status_label = "учим"
    data.update({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "needs_review": needs_review,
        "mastered": mastered,
        "status": status,
        "status_label": status_label,
    })
    return data


def _problem_word_dict(word) -> dict:
    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": _word_dict(word).get("transcription", ""),
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "correct_count": int(word["correct_count"] or 0),
        "wrong_count": int(word["wrong_count"] or 0),
    }


async def _safe_json(request: web.Request) -> dict:
    if request.body_exists:
        try:
            return await request.json()
        except Exception:
            return {}
    return {}


async def _read_audio_upload(request: web.Request) -> tuple[bytes, str, str]:
    try:
        reader = await request.multipart()
        field = await reader.next()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Нужно отправить аудиофайл") from exc

    if not field or field.name != "audio":
        raise web.HTTPBadRequest(text="Поле audio не найдено")

    chunks = []
    total = 0
    while True:
        chunk = await field.read_chunk(size=64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_AUDIO_BYTES,
                actual_size=total,
                text="Голосовое сообщение слишком большое",
            )
        chunks.append(chunk)

    audio = b"".join(chunks)
    if not audio:
        raise web.HTTPBadRequest(text="Пустое голосовое сообщение")

    return (
        audio,
        field.filename or "voice.webm",
        field.headers.get("Content-Type", "audio/webm"),
    )


def _chat_usage_payload(stats) -> dict:
    used = int(stats["requests"] if stats else 0)
    return {
        "used_today": used,
        "daily_limit": None,
        "remaining_today": None,
        "unlimited": True,
        "input_tokens_today": int(stats["input_tokens"] if stats else 0),
        "output_tokens_today": int(stats["output_tokens"] if stats else 0),
        "total_tokens_today": int(stats["total_tokens"] if stats else 0),
        "cost_usd_today": round(float(stats["cost_usd"] if stats else 0), 6),
    }


def _daily_lesson_payload(status, reward_points: int = 0, points: int | None = None) -> dict:
    completed_steps = int(status["completed_steps"] if status else 0)
    return {
        "lesson_date": status["lesson_date"] if status else "",
        "completed_steps": completed_steps,
        "total_steps": DAILY_LESSON_STEPS,
        "completed": bool(status["completed"] if status else False),
        "rewarded": bool(status["rewarded"] if status else False),
        "reward_points": reward_points,
        "points": points,
    }


def _date_text(value) -> str:
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _is_admin_user_id(user_id) -> bool:
    try:
        return int(user_id) in ADMIN_USER_IDS
    except (TypeError, ValueError):
        return False


def _is_admin_request(request: web.Request) -> bool:
    return _is_admin_user_id(request["tg_user"]["id"])


def _admin_forbidden_response() -> web.Response:
    return web.json_response({"error": "Доступ только для администратора"}, status=403)


def _file_cache_summary(path: Path) -> dict:
    files = [item for item in path.glob("*") if item.is_file()] if path.exists() else []
    return {
        "files": len(files),
        "size_mb": round(sum(item.stat().st_size for item in files) / 1024 / 1024, 2),
    }


def _safe_int(row, key: str, default: int = 0) -> int:
    try:
        return int(_record_value(row, key, default) or 0)
    except (TypeError, ValueError):
        return default


def _safe_float(row, key: str, default: float = 0.0) -> float:
    try:
        return float(_record_value(row, key, default) or 0)
    except (TypeError, ValueError):
        return default


def _admin_overview_payload(overview: dict) -> dict:
    users = overview.get("users")
    words = overview.get("words")
    learning = overview.get("learning")
    ai_today = overview.get("ai_today")
    openai_status = openai_config_status()
    admin_ids_count = len(ADMIN_USER_IDS)
    failed_images = _safe_int(words, "failed_images")
    missing_images = _safe_int(words, "missing_images")
    health = []
    if admin_ids_count <= 0:
        health.append({
            "level": "critical",
            "title": "Администратор не настроен",
            "text": "Добавьте ADMIN_USER_IDS в Render, иначе панель не будет доступна владельцу.",
        })
    if not openai_status.get("configured"):
        health.append({
            "level": "critical",
            "title": "OpenAI не настроен",
            "text": "OPENAI_API_KEY отсутствует. Репетитор, озвучка и AI-картинки работать не будут.",
        })
    if failed_images > 0:
        health.append({
            "level": "warning",
            "title": "Есть ошибки генерации картинок",
            "text": f"{failed_images} слов имеют статус failed. После исправления billing/API сбросьте ошибки картинок.",
        })
    if missing_images > 0:
        health.append({
            "level": "info",
            "title": "Картинки ещё не сгенерированы",
            "text": f"{missing_images} слов ждут AI-картинки. Это нормально, если генерация идёт постепенно.",
        })
    if not health:
        health.append({
            "level": "ok",
            "title": "Система выглядит нормально",
            "text": "Критичных проблем в админской диагностике сейчас не видно.",
        })
    return {
        "health": health,
        "users": {
            "total": _safe_int(users, "total_users"),
            "new_today": _safe_int(users, "new_users_today"),
            "active_today": int(overview.get("active_today") or 0),
            "total_points": _safe_int(users, "total_points"),
        },
        "learning": {
            "completed_daily_lessons": _safe_int(learning, "completed_daily_lessons"),
            "completed_word_tests": _safe_int(learning, "completed_word_tests"),
            "completed_games": _safe_int(learning, "completed_games"),
            "training_attempts": _safe_int(learning, "training_attempts"),
            "learned_word_links": _safe_int(learning, "learned_word_links"),
        },
        "words": {
            "total": _safe_int(words, "total_words"),
            "generated_images": _safe_int(words, "generated_images"),
            "images_needing_review": _safe_int(words, "images_needing_review"),
            "failed_images": _safe_int(words, "failed_images"),
            "missing_images": _safe_int(words, "missing_images"),
            "semantic_review_words": _safe_int(words, "semantic_review_words"),
        },
        "ai_today": {
            "requests": _safe_int(ai_today, "requests"),
            "input_tokens": _safe_int(ai_today, "input_tokens"),
            "output_tokens": _safe_int(ai_today, "output_tokens"),
            "total_tokens": _safe_int(ai_today, "total_tokens"),
            "cost_usd": round(_safe_float(ai_today, "cost_usd"), 6),
        },
        "cache": {
            "generated_images": _file_cache_summary(GENERATED_VOCAB_DIR),
            "word_audio": _file_cache_summary(AUDIO_CACHE_DIR),
        },
        "config": {
            "app_version": APP_VERSION,
            "webapp_url": WEBAPP_URL,
            "bot_run_mode": BOT_RUN_MODE,
            "api_rate_limit_per_minute": API_RATE_LIMIT_PER_MINUTE,
            "ai_rate_limit_per_minute": AI_RATE_LIMIT_PER_MINUTE,
            "admin_ids_configured": admin_ids_count,
            "openai": openai_status,
        },
    }


def _admin_user_dict(row) -> dict:
    total_answers = _safe_int(row, "total_correct") + _safe_int(row, "total_wrong")
    accuracy = round(_safe_int(row, "total_correct") / total_answers * 100) if total_answers else 0
    age_group = _record_value(row, "age_group", "")
    return {
        "id": _safe_int(row, "user_id"),
        "child_name": _record_value(row, "name", ""),
        "parent_name": _record_value(row, "parent_name", "") or "",
        "child_age": _record_value(row, "child_age", None),
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "goal_label": _goal_label(_record_value(row, "goal", "")),
        "level_label": _level_label(_record_value(row, "english_level", "")),
        "level_test_score": _record_value(row, "level_test_score", None),
        "level_test_completed": bool(_record_value(row, "level_test_completed_at")),
        "points": _safe_int(row, "points"),
        "registered_at": _date_text(_record_value(row, "registered_at")),
        "words_learned": _safe_int(row, "words_learned"),
        "total_correct": _safe_int(row, "total_correct"),
        "total_wrong": _safe_int(row, "total_wrong"),
        "accuracy": accuracy,
        "completed_lessons": _safe_int(row, "completed_lessons"),
        "completed_word_tests": _safe_int(row, "completed_word_tests"),
        "completed_games": _safe_int(row, "completed_games"),
    }


def _admin_failed_image_dict(row) -> dict:
    raw_review = _record_value(row, "generated_image_review", "") or ""
    reason = ""
    try:
        parsed = json.loads(raw_review)
        reason = str(parsed.get("reason") or "")
    except Exception:
        reason = raw_review[:180]
    return {
        "id": _safe_int(row, "id"),
        "word": _record_value(row, "word", ""),
        "translation": _record_value(row, "translation", ""),
        "topic": _record_value(row, "topic", ""),
        "age_group": _record_value(row, "age_group", ""),
        "status": _record_value(row, "generated_image_status", "failed"),
        "reason": reason,
        "checked_at": _date_text(_record_value(row, "generated_image_checked_at")),
    }


def _admin_user_detail_payload(user, stats, report, dictionary_summary, problem_words, history, ai_today, streak) -> dict:
    level = _level_for_user(user)
    age_group = _normalized_age_group_for_user(user)
    stats_payload = {
        "words_learned": _safe_int(stats, "words_learned"),
        "total_correct": _safe_int(stats, "total_correct"),
        "total_wrong": _safe_int(stats, "total_wrong"),
    }
    total_answers = stats_payload["total_correct"] + stats_payload["total_wrong"]
    report_payload = {
        "completed_lessons": _safe_int(report, "completed_lessons"),
        "completed_word_tests": _safe_int(report, "completed_word_tests"),
        "avg_word_test_score": _safe_int(report, "avg_word_test_score"),
        "completed_games": _safe_int(report, "completed_games"),
        "avg_game_score": _safe_int(report, "avg_game_score"),
    }
    return {
        "user": {
            "id": _safe_int(user, "user_id"),
            "child_name": _record_value(user, "name", ""),
            "parent_name": _record_value(user, "parent_name", "") or "",
            "child_age": _record_value(user, "child_age", None),
            "age_group": age_group,
            "age_label": _age_label(age_group),
            "goal_label": _goal_label(_record_value(user, "goal", "")),
            "level": level,
            "level_label": _level_label(level),
            "level_test_score": _record_value(user, "level_test_score", None),
            "level_test_completed": bool(_record_value(user, "level_test_completed_at")),
            "points": _safe_int(user, "points"),
            "registered_at": _date_text(_record_value(user, "registered_at")),
        },
        "stats": {
            **stats_payload,
            "accuracy": round(stats_payload["total_correct"] / total_answers * 100) if total_answers else 0,
        },
        "report": report_payload,
        "dictionary": {
            "total_words": _safe_int(dictionary_summary, "total_words"),
            "mastered_words": _safe_int(dictionary_summary, "mastered_words"),
            "review_words": _safe_int(dictionary_summary, "review_words"),
        },
        "streak": streak or {},
        "problem_words": [_problem_word_dict(row) for row in problem_words],
        "history": [_activity_event_dict(row) for row in history],
        "ai_today": _chat_usage_payload(ai_today),
    }


def _activity_event_dict(row) -> dict:
    event_type = row["event_type"]
    if event_type == "daily_lesson":
        title = "Урок дня"
        description = "Урок завершён"
    elif event_type == "word_game":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Игровая практика"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type == "word_test":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Учим слова"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type in {"review_training", "word_training"}:
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Работа над ошибками" if event_type == "review_training" else "Тренировка слов"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    else:
        title = "Тест уровня"
        description = f"Результат: {int(row['score'] or 0)}%"

    return {
        "type": event_type,
        "date": row["event_date"] or "",
        "event_at": _date_text(row["event_at"]),
        "title": title,
        "description": description,
        "score": row["score"],
    }


def _game_title(game_type: str) -> str:
    titles = {
        "word_hunt": "Словесная охота",
    }
    return titles.get(game_type, "Игра со словами")


def _parent_recommendations(report: dict, dictionary_summary: dict, problem_words: list[dict]) -> list[dict]:
    words_learned = int(report.get("words_learned") or 0)
    completed_lessons = int(report.get("completed_lessons") or 0)
    completed_word_tests = int(report.get("completed_word_tests") or 0)
    avg_score = int(report.get("avg_word_test_score") or 0)
    total_wrong = int(report.get("total_wrong") or 0)
    review_words = int((dictionary_summary or {}).get("review_words") or 0)
    recommendations = []

    if completed_lessons == 0:
        recommendations.append({
            "title": "Начать с короткого урока",
            "text": "Пусть ребенок пройдет ежедневный урок на 5 минут: слова, мини-тест и простая фраза.",
            "action": "daily",
        })
    if words_learned == 0:
        recommendations.append({
            "title": "Добавить первые слова",
            "text": "Запустите набор новых слов с тестом, чтобы появился базовый словарь и первые результаты.",
            "action": "vocab",
        })
    if review_words > 0:
        recommendations.append({
            "title": "Повторить слабые слова",
            "text": f"В словаре есть {review_words} слов на повторение. Лучше закрепить их до новых тем.",
            "action": "review",
        })
    if completed_word_tests > 0 and avg_score < 70:
        recommendations.append({
            "title": "Снизить сложность на один шаг",
            "text": "Средний результат тестов ниже 70%. Дайте больше повторения и короткие задания без спешки.",
            "action": "review",
        })
    if problem_words and total_wrong > 0:
        sample = ", ".join(word["word"] for word in problem_words[:3])
        recommendations.append({
            "title": "Фокус на конкретных словах",
            "text": f"Чаще всего ошибается в словах: {sample}. Их стоит повторить в короткой тренировке.",
            "action": "dictionary",
        })
    if not recommendations:
        recommendations.append({
            "title": "Продолжать текущий темп",
            "text": "Прогресс выглядит ровно. Достаточно 5-10 минут в день: урок, повторение и короткая устная практика.",
            "action": "daily",
        })
    return recommendations[:4]


def _age_label(age_group: str) -> str:
    return next((label for label, value in AGE_GROUPS if value == age_group), age_group)


def _goal_label(goal: str | None) -> str:
    return next((label for label, value in LEARNING_GOALS if value == goal), goal or "")


def _record_value(row, key: str, default=None):
    if not row:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return value if value not in (None, "") else default


def _level_label(level: str | None) -> str:
    return next((label for label, value in ENGLISH_LEVELS if value == level), level or "Не определен")


def _estimated_level_for_user(user) -> str:
    goal = _record_value(user, "goal", "")
    age_group = _record_value(user, "age_group", "")
    if goal in {"exams", "travel"} or age_group == "14_18":
        return "elementary"
    if age_group in {"5_7", "8_10"} or goal == "first_steps":
        return "beginner"
    return "beginner"


def _level_for_user(user) -> str:
    return _record_value(user, "english_level") or _estimated_level_for_user(user) or TUTOR_DEFAULT_LEVEL


def _style_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    if age_group in {"5_7", "8_10"}:
        return "игровой, очень доброжелательный, с простыми фразами и мини-играми"
    if age_group == "14_18":
        return "спокойный, дружелюбный, с диалогами и реальными ситуациями"
    return "дружелюбный, короткими репликами, с понятными примерами"


def _topics_for_user(user) -> str:
    goal = user["goal"] if user else ""
    age_group = user["age_group"] if user else ""
    if goal == "travel":
        return "путешествия, аэропорт, кафе, покупки, знакомство, карта города"
    if goal == "exams":
        return "школа, хобби, планы, короткие диалоги, экзаменационные темы без стресса"
    if goal == "speaking":
        return "игры, друзья, спорт, музыка, фильмы, хобби, повседневные диалоги"
    if age_group in {"5_7", "8_10"}:
        return "животные, цвета, еда, игрушки, игры, школа, сказочные истории"
    return "школа, игры, спорт, путешествия, хобби, истории, повседневные ситуации"


def _normalized_age_group_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    try:
        child_age = int(user["child_age"] or 0) if user else 0
    except (TypeError, ValueError):
        child_age = 0
    if age_group in {"5_7", "8_10", "11_13", "14_18"}:
        return age_group
    if 5 <= child_age <= 7:
        return "5_7"
    if 8 <= child_age <= 10:
        return "8_10"
    if 11 <= child_age <= 13:
        return "11_13"
    if 14 <= child_age <= 18:
        return "14_18"
    if age_group in {"under_12", "under12", "under_10"}:
        return "8_10"
    return "8_10"


def _prompt_context_for_user(user) -> dict:
    return {
        "age": str(user["child_age"] or _age_label(user["age_group"])) if user else "не указан",
        "age_group": _normalized_age_group_for_user(user),
        "level": _level_for_user(user),
        "goal": _goal_label(user["goal"]) if user else "устная практика",
        "style": _style_for_user(user),
        "topics": _topics_for_user(user),
    }


def _voice_topic_bank(user) -> list[str]:
    age_group = user["age_group"] if user else ""
    goal = user["goal"] if user else ""
    if goal == "travel":
        return [
            "airport adventure", "hotel check-in", "cafe order", "city map",
            "souvenir shop", "beach day", "train station", "lost backpack",
            "photo walk", "weather talk", "ice cream kiosk", "museum quest",
            "passport helper", "bus stop", "theme park", "family trip",
            "restaurant mistake", "ask for directions",
        ]
    if goal == "exams":
        return [
            "school day", "favorite hobby", "weekend plans", "short interview",
            "picture description", "study routine", "sports club", "my room",
            "healthy food", "future job", "friendship", "small presentation",
            "compare two pictures", "tell a mini story", "opinion practice",
            "exam calm-down", "daily routine challenge", "question cards",
        ]
    if age_group in {"5_7", "8_10"}:
        return [
            "magic shop", "space picnic", "robot friend", "treasure map",
            "funny cafe", "toy store", "school bag", "secret door",
            "superhero training", "rainbow colors", "little chef", "sports day",
            "pet doctor", "birthday party", "snowy park", "music game",
            "dragon library", "pirate bakery", "dino museum", "jungle camera",
            "monster picnic", "art studio", "weather machine", "lost teddy",
            "train of words", "moon playground", "detective game", "tiny theater",
        ]
    if age_group == "11_13":
        return [
            "school project", "gaming club", "sports practice", "music playlist",
            "movie scene", "travel vlog", "cafe dialogue", "new classmate",
            "weekend plan", "pet story", "shopping challenge", "mystery quest",
            "YouTube plan", "comic book idea", "science fair", "escape room",
            "football commentary", "birthday planning", "school club pitch",
            "phone call practice",
        ]
    return [
        "real conversation", "travel problem", "school debate", "job interview mini",
        "movie discussion", "music and hobbies", "daily routine", "exam warm-up",
        "ordering food", "city directions", "online safety", "future plans",
        "small talk practice", "opinion challenge", "presentation opener",
        "friendly disagreement", "study abroad scene", "interview with a blogger",
    ]


def _choose_voice_topics(user, messages: list[dict], count: int = 3) -> list[str]:
    bank = _voice_topic_bank(user)
    recent_text = " ".join(m["content"] for m in messages[-10:]).lower()
    fresh = [topic for topic in bank if topic.lower() not in recent_text]
    if len(fresh) < count:
        fresh = bank[:]
    random.shuffle(fresh)
    return fresh[:count]


def _voice_lesson_focus(messages: list[dict]) -> str:
    recent = [
        " ".join(str(message.get("content") or "").split())
        for message in messages[-6:]
        if str(message.get("content") or "").strip()
    ]
    if not recent:
        return "урок только начинается"
    return (
        "Текущая линия урока — последние реплики: "
        + " | ".join(recent[-4:])
        + ". Продолжай эту тему и мини-сцену, пока ребенок сам не попросит сменить тему."
    )


def _voice_prompt_context(user, messages: list[dict], lesson_state: dict | None = None) -> dict:
    topics = _choose_voice_topics(user, messages)
    lesson_focus = _voice_lesson_focus(messages)
    has_history = any(str(message.get("content") or "").strip() for message in messages)
    recent_user_messages = [m["content"] for m in messages if m["role"] == "user"][-3:]
    recent_assistant_messages = [m["content"] for m in messages if m["role"] == "assistant"][-3:]
    context = {
        "lesson_focus": lesson_focus,
        "topic_suggestions": (
            "не меняй текущую тему; запасные темы только если ребенок явно просит сменить тему: "
            + ", ".join(topics)
            if has_history else ", ".join(topics)
        ),
        "avoid_topics": (
            "Не меняй тему по таймеру и не начинай новый урок сам. "
            "Продолжай текущую линию урока 8-10 реплик или до явной просьбы ребенка сменить тему. "
            "Не перечисляй новые темы, если ребенок уже находится в мини-сцене."
        ),
        "recent_user_messages": " | ".join(recent_user_messages) or "пока нет",
        "recent_assistant_messages": " | ".join(recent_assistant_messages) or "пока нет",
        "activity_menu": (
            "роль: продавец/покупатель, мини-квест, угадай слово, естественный вопрос, "
            "выбор из двух вариантов, вопрос про день ребенка, короткая смешная сценка, "
            "мини-история на 2 реплики, возвращение к слову из прошлой реплики"
        ),
        "lesson_loop": (
            "Сначала живо отреагируй на смысл реплики ребенка. Затем обязательно добавь маленькую учебную пользу: "
            "одну английскую фразу вроде I want..., I like..., Can I have...?, одно слово, мягкое исправление "
            "или выбор из двух вариантов. Не требуй повторения каждый раз; иногда задай естественный вопрос "
            "или продолжи сцену. Держи одну тему урока, пока ребенок сам не сменит ее. Через несколько реплик верни одно старое слово."
        ),
        "conversation_plan": (
            "1) Сначала понять настоящий запрос ребенка: вопрос, просьба, выбор темы, усталость или ошибка. "
            "2) Ответить по сути на этот запрос, не игнорировать его ради плана урока. "
            "3) Всегда связать ответ с короткой учебной пользой: фразой, словом, исправлением, выбором или мини-практикой. "
            "4) Продолжить текущую мини-сцену 8-10 ходов, если ребенок не просит сменить тему. "
            "5) Каждые 3-4 реплики можно менять активность внутри той же темы: мини-диалог, угадай слово, роль, вопрос, исправление. "
            "6) Если ребенок отвечает коротко, упростить и дать выбор из двух вариантов. "
            "7) Если ребенок спрашивает по-русски, ответить по-русски и дать одну маленькую английскую фразу."
        ),
    }
    if lesson_state:
        context.update(lesson_prompt_context(lesson_state))
    return context


async def _ensure_voice_lesson_state(user_id: int, user) -> dict:
    row = await database.get_voice_lesson_state(user_id)
    age_group = _normalized_age_group_for_user(user)
    if row and row["age_group"] == age_group:
        return dict(row)
    state = create_lesson_state(
        age_group=age_group,
        goal=user["goal"] if user else "",
        seed=str(user_id),
    )
    await database.save_voice_lesson_state(user_id, state)
    return state


async def _advance_voice_lesson_state(user_id: int, user, role: str, text: str) -> dict:
    state = await _ensure_voice_lesson_state(user_id, user)
    previous_phase = state.get("phase")
    state = advance_lesson_state(state, role, text)
    await database.save_voice_lesson_state(user_id, state)
    if previous_phase != "wrapup" and state.get("phase") == "wrapup":
        await database.save_completed_voice_lesson(user_id, state)
    return state


async def _current_user_or_404(request: web.Request):
    user = await database.get_user(request["tg_user"]["id"])
    if not user:
        raise web.HTTPBadRequest(text="user is not registered")
    return user


async def _build_vocab_question(word, age_group: str) -> dict:
    wrong = await database.get_word_options(word["id"], age_group, count=3)
    options = [{"id": word["id"], "translation": word["translation"]}]
    options += [{"id": item["id"], "translation": item["translation"]} for item in wrong]
    random.shuffle(options)
    return {
        "word_id": word["id"],
        "word": word["word"],
        "transcription": word["transcription"] or "",
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "type": "picture" if age_group == "5_7" else "translation",
        "prompt": "Выбери перевод",
        "options": options,
    }


async def _build_word_hunt_round(word, age_group: str) -> dict:
    wrong = await database.get_random_words(3, exclude_id=word["id"], age_group=age_group)
    options = [{"id": word["id"], "word": word["word"]}]
    options += [{"id": item["id"], "word": item["word"]} for item in wrong]
    random.shuffle(options)
    return {
        "word_id": word["id"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "prompt": f"Поймай английское слово для: {word['translation']}",
        "options": options,
    }


LEVEL_TESTS = {
    "5_7": [
        {
            "id": "5_7_cat",
            "prompt": "Что значит cat?",
            "options": [("cat", "кошка"), ("dog", "собака"), ("sun", "солнце")],
            "correct_id": "cat",
        },
        {
            "id": "5_7_blue",
            "prompt": "Какой цвет blue?",
            "options": [("red", "красный"), ("blue", "синий"), ("green", "зеленый")],
            "correct_id": "blue",
        },
        {
            "id": "5_7_hello",
            "prompt": "Что можно ответить на Hello?",
            "options": [("hi", "Hi!"), ("bye", "Bye!"), ("thanks", "Thanks!")],
            "correct_id": "hi",
        },
        {
            "id": "5_7_three",
            "prompt": "One, two, ...",
            "options": [("five", "five"), ("three", "three"), ("red", "red")],
            "correct_id": "three",
        },
        {
            "id": "5_7_like",
            "prompt": "Как сказать: Я люблю яблоки?",
            "options": [("like", "I like apples."), ("am", "I am apples."), ("go", "I go apples.")],
            "correct_id": "like",
        },
    ],
    "8_10": [
        {
            "id": "8_10_like",
            "prompt": "Выбери правильную фразу.",
            "options": [("like", "I like pizza."), ("likes", "I likes pizza."), ("am", "I am pizza.")],
            "correct_id": "like",
        },
        {
            "id": "8_10_can",
            "prompt": "Что значит I can swim?",
            "options": [("can", "Я умею плавать"), ("want", "Я хочу плавать"), ("had", "Я плавал вчера")],
            "correct_id": "can",
        },
        {
            "id": "8_10_plural",
            "prompt": "Как правильно: две кошки?",
            "options": [("cats", "two cats"), ("cat", "two cat"), ("caties", "two caties")],
            "correct_id": "cats",
        },
        {
            "id": "8_10_question",
            "prompt": "Выбери вопрос.",
            "options": [("do", "Do you like games?"), ("you", "You like do games?"), ("likes", "Does you like games?")],
            "correct_id": "do",
        },
        {
            "id": "8_10_yesterday",
            "prompt": "Вчера я играл.",
            "options": [("played", "I played yesterday."), ("play", "I play yesterday."), ("playing", "I am play yesterday.")],
            "correct_id": "played",
        },
        {
            "id": "8_10_place",
            "prompt": "The book is under the table. Где книга?",
            "options": [("under", "под столом"), ("on", "на столе"), ("near", "рядом со столом")],
            "correct_id": "under",
        },
    ],
    "11_13": [
        {
            "id": "11_13_present",
            "prompt": "He ___ football every Sunday.",
            "options": [("plays", "plays"), ("play", "play"), ("playing", "playing")],
            "correct_id": "plays",
        },
        {
            "id": "11_13_past",
            "prompt": "We ___ to school yesterday.",
            "options": [("went", "went"), ("go", "go"), ("goes", "goes")],
            "correct_id": "went",
        },
        {
            "id": "11_13_question",
            "prompt": "Выбери правильный порядок слов.",
            "options": [("where", "Where do you live?"), ("do", "Where you do live?"), ("live", "Where live you?")],
            "correct_id": "where",
        },
        {
            "id": "11_13_future",
            "prompt": "Tomorrow I ___ visit my friend.",
            "options": [("will", "will"), ("was", "was"), ("did", "did")],
            "correct_id": "will",
        },
        {
            "id": "11_13_comparative",
            "prompt": "My room is ___ than my brother's room.",
            "options": [("bigger", "bigger"), ("big", "big"), ("biggest", "biggest")],
            "correct_id": "bigger",
        },
        {
            "id": "11_13_meaning",
            "prompt": "I have already done my homework.",
            "options": [("already", "Я уже сделал домашку"), ("tomorrow", "Я сделаю домашку завтра"), ("never", "Я никогда не делал домашку")],
            "correct_id": "already",
        },
        {
            "id": "11_13_advice",
            "prompt": "Как дать совет?",
            "options": [("should", "You should rest."), ("musted", "You musted rest."), ("are", "You are rest.")],
            "correct_id": "should",
        },
    ],
    "14_18": [
        {
            "id": "14_18_perfect",
            "prompt": "I ___ just finished my project.",
            "options": [("have", "have"), ("did", "did"), ("am", "am")],
            "correct_id": "have",
        },
        {
            "id": "14_18_condition",
            "prompt": "If I had more time, I ___ travel more.",
            "options": [("would", "would"), ("will", "will"), ("can", "can")],
            "correct_id": "would",
        },
        {
            "id": "14_18_natural",
            "prompt": "Выбери самый естественный ответ на Thanks a lot!",
            "options": [("welcome", "You're welcome!"), ("fine", "I'm fine."), ("later", "See you later.")],
            "correct_id": "welcome",
        },
        {
            "id": "14_18_reported",
            "prompt": "She said that she ___ tired.",
            "options": [("was", "was"), ("is", "is"), ("be", "be")],
            "correct_id": "was",
        },
        {
            "id": "14_18_phrase",
            "prompt": "Что значит I am looking forward to it?",
            "options": [("wait", "Я этого с нетерпением жду"), ("look", "Я смотрю вперед"), ("lost", "Я это потерял")],
            "correct_id": "wait",
        },
        {
            "id": "14_18_email",
            "prompt": "Какая фраза лучше для вежливого письма?",
            "options": [("could", "Could you please help me?"), ("give", "Give me help."), ("must", "You must help.")],
            "correct_id": "could",
        },
        {
            "id": "14_18_passive",
            "prompt": "English ___ in many countries.",
            "options": [("spoken", "is spoken"), ("speaks", "speaks"), ("spoke", "is spoke")],
            "correct_id": "spoken",
        },
        {
            "id": "14_18_opinion",
            "prompt": "Как начать мнение?",
            "options": [("opinion", "In my opinion, ..."), ("because", "Because my opinion, ..."), ("think", "I thinking that ...")],
            "correct_id": "opinion",
        },
    ],
}


def _level_questions_for_age(age_group: str) -> list[dict]:
    return LEVEL_TESTS.get(age_group) or LEVEL_TESTS["8_10"]


def _public_level_question(question: dict) -> dict:
    return {
        "id": question["id"],
        "prompt": question["prompt"],
        "options": [
            {"id": option_id, "text": text}
            for option_id, text in question["options"]
        ],
    }


def _level_from_score(age_group: str, correct_count: int, total: int) -> str:
    if total <= 0:
        return _estimated_level_for_user({"age_group": age_group})
    score = correct_count / total
    if age_group == "5_7":
        return "beginner" if score >= 0.65 else "starter"
    if age_group == "8_10":
        if score < 0.35:
            return "starter"
        if score < 0.75:
            return "beginner"
        return "elementary"
    if score < 0.35:
        return "beginner"
    if score < 0.75:
        return "elementary"
    return "pre_intermediate"


def _level_result_message(level: str) -> str:
    messages = {
        "starter": "Начнем очень мягко: первые слова, короткие фразы и много поддержки.",
        "beginner": "Хорошая база для простых диалогов. Будем уверенно строить фразы.",
        "elementary": "Можно добавлять больше грамматики, мини-диалоги и школьные темы.",
        "pre_intermediate": "Отлично, можно тренировать живую речь, объяснения и более длинные ответы.",
    }
    return messages.get(level, "Репетитор подстроит задания под этот уровень.")


def _path_step(step_id: str, title: str, text: str, action: str, status: str) -> dict:
    return {
        "id": step_id,
        "title": title,
        "text": text,
        "action": action,
        "status": status,
    }


def _learning_path_payload(user, daily_status, stats, dictionary_summary, report) -> dict:
    level_done = bool(_record_value(user, "level_test_completed_at"))
    daily_steps = int(_record_value(daily_status, "completed_steps", 0) or 0)
    daily_done = bool(_record_value(daily_status, "completed", False))
    words_learned = int(_record_value(stats, "words_learned", 0) or 0)
    review_words = int(_record_value(dictionary_summary, "review_words", 0) or 0)

    if not level_done:
        next_action = "level"
        next_title = "Сначала узнаем уровень"
        next_text = "Короткий тест поможет давать задания не слишком легкие и не слишком сложные."
    elif not daily_done:
        next_action = "daily"
        next_title = f"Продолжить урок: шаг {min(daily_steps + 1, DAILY_LESSON_STEPS)} из {DAILY_LESSON_STEPS}"
        next_text = "Сегодняшний маршрут: слова, мини-тест, фраза и награда."
    elif words_learned == 0:
        next_action = "vocab"
        next_title = "Добавить первые слова"
        next_text = "Небольшой набор слов даст основу для игр и устной практики."
    elif review_words > 0:
        next_action = "review"
        next_title = f"Повторить {review_words} слов"
        next_text = "Лучше закрепить ошибки короткой тренировкой, пока они свежие."
    else:
        next_action = "learn"
        next_title = "Выбрать следующую тренировку"
        next_text = "Маршрут дня готов. Можно взять новые слова или повторить сложные."

    steps = [
        _path_step(
            "level",
            "Уровень",
            _level_label(_level_for_user(user)),
            "level",
            "done" if level_done else "current",
        ),
        _path_step(
            "daily",
            "Урок дня",
            f"{daily_steps}/{DAILY_LESSON_STEPS} шагов",
            "daily",
            "done" if daily_done else ("current" if level_done else "ready"),
        ),
        _path_step(
            "vocab",
            "Слова",
            f"{words_learned} в словаре",
            "vocab",
            "done" if words_learned > 0 else ("current" if daily_done else "ready"),
        ),
        _path_step(
            "review",
            "Повторение",
            f"{review_words} слов ждут",
            "review",
            "current" if review_words > 0 else ("done" if words_learned > 0 else "ready"),
        ),
    ]
    done_count = sum(1 for step in steps if step["status"] == "done")
    return {
        "title": "Маршрут дня",
        "next_action": next_action,
        "next_title": next_title,
        "next_text": next_text,
        "progress_percent": round(done_count / len(steps) * 100),
        "steps": steps,
    }


def _motivation_badge(
    badge_id: str,
    title: str,
    text: str,
    value: int,
    target: int,
    action: str,
) -> dict:
    target = max(1, target)
    value = max(0, value)
    return {
        "id": badge_id,
        "title": title,
        "text": text,
        "value": value,
        "target": target,
        "progress_percent": min(100, round(value / target * 100)),
        "unlocked": value >= target,
        "action": action,
    }


def _motivation_payload(user, stats, dictionary_summary, report, streak) -> dict:
    words_learned = int(_record_value(stats, "words_learned", 0) or 0)
    total_correct = int(_record_value(stats, "total_correct", 0) or 0)
    total_wrong = int(_record_value(stats, "total_wrong", 0) or 0)
    review_words = int(_record_value(dictionary_summary, "review_words", 0) or 0)
    completed_lessons = int(_record_value(report, "completed_lessons", 0) or 0)
    completed_word_tests = int(_record_value(report, "completed_word_tests", 0) or 0)
    completed_games = int(_record_value(report, "completed_games", 0) or 0)
    current_streak = int((streak or {}).get("current_streak") or 0)
    longest_streak = int((streak or {}).get("longest_streak") or 0)
    completed_days = int((streak or {}).get("completed_days") or 0)
    today_completed = bool((streak or {}).get("today_completed"))

    badges = [
        _motivation_badge("first_lesson", "Первый урок", "Завершить один ежедневный урок.", completed_lessons, 1, "daily"),
        _motivation_badge("three_day_streak", "Три дня подряд", "Учиться три дня без перерыва.", current_streak, 3, "daily"),
        _motivation_badge("seven_day_streak", "Неделя английского", "Собрать серию из семи дней.", current_streak, 7, "daily"),
        _motivation_badge("word_collector", "10 слов", "Добавить первые десять слов в обучение.", words_learned, 10, "vocab"),
        _motivation_badge("word_builder", "50 слов", "Уверенно расширять словарь.", words_learned, 50, "vocab"),
        _motivation_badge("test_starter", "Первый тест", "Пройти тест по новым словам.", completed_word_tests, 1, "vocab"),
        _motivation_badge("game_player", "Игровая практика", "Закрепить слова в игровой практике.", completed_games, 3, "learn"),
        _motivation_badge("careful_answer", "30 верных ответов", "Набрать 30 правильных ответов.", total_correct, 30, "training"),
    ]
    unlocked_count = sum(1 for badge in badges if badge["unlocked"])

    if not today_completed:
        next_action = "daily"
        next_title = "Сделать урок дня"
        next_text = "Короткий урок сохранит серию и даст новые слова без перегруза."
    elif review_words > 0:
        next_action = "review"
        next_title = f"Повторить {review_words} слов"
        next_text = "Лучше закрепить свежие ошибки сразу, пока они хорошо помнятся."
    elif words_learned < 10:
        next_action = "vocab"
        next_title = "Собрать первые 10 слов"
        next_text = "Небольшой словарь даст материал для игр и устной практики."
    elif current_streak < 3:
        next_action = "learn"
        next_title = "Дополнительная тренировка"
        next_text = "Сегодняшний урок уже зачтен. Можно потренироваться еще, а серия продолжится завтра."
    elif completed_games < 3:
        next_action = "learn"
        next_title = "Закрепить слова"
        next_text = "Открой учебный раздел и выбери подходящую тренировку."
    elif completed_word_tests < 3:
        next_action = "vocab"
        next_title = "Пройти еще один тест"
        next_text = "Мини-тест покажет, какие слова уже стали уверенными."
    else:
        next_action = "learn"
        next_title = "Выбрать учебную тренировку"
        next_text = "Можно взять новые слова или повторить сложные."

    accuracy_total = total_correct + total_wrong
    accuracy = round(total_correct / accuracy_total * 100) if accuracy_total else 0
    coach_message = (
        "Сегодня урок уже засчитан. Можно сделать легкое повторение или короткую тренировку."
        if today_completed else
        "Лучший темп для ребенка: 5 минут сегодня, без длинной теории."
    )

    return {
        "title": "Достижения",
        "coach_message": coach_message,
        "next_action": next_action,
        "next_title": next_title,
        "next_text": next_text,
        "streak": {
            "current": current_streak,
            "longest": longest_streak,
            "completed_days": completed_days,
            "today_completed": today_completed,
        },
        "summary": {
            "unlocked_badges": unlocked_count,
            "total_badges": len(badges),
            "words_learned": words_learned,
            "completed_lessons": completed_lessons,
            "completed_word_tests": completed_word_tests,
            "completed_games": completed_games,
            "accuracy": accuracy,
        },
        "badges": badges,
    }


# ---------- API: профиль и регистрация ----------

async def api_me(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user["id"]
    is_admin = _is_admin_user_id(user_id)

    user = await database.get_user(user_id)
    if not user:
        return web.json_response({
            "registered": False,
            "is_admin": is_admin,
            "tg_user": {
                "id": tg_user["id"],
                "first_name": tg_user.get("first_name", ""),
            },
            "age_groups": [{"value": v, "label": l} for l, v in AGE_GROUPS],
            "goals": [{"value": v, "label": l} for l, v in LEARNING_GOALS],
            "levels": [{"value": v, "label": l} for l, v in ENGLISH_LEVELS],
        })

    stats = await database.get_user_stats(user_id)
    level = _level_for_user(user)
    age_group = _normalized_age_group_for_user(user)
    return web.json_response({
        "registered": True,
        "is_admin": is_admin,
        "user": {
            "id":         user["user_id"],
            "child_name": user["name"],
            "parent_name": user["parent_name"] or "",
            "child_age": user["child_age"],
            "age_group":  age_group,
            "age_label":  _age_label(age_group),
            "goal": user["goal"] or "",
            "goal_label": _goal_label(user["goal"]),
            "level": level,
            "level_label": _level_label(level),
            "level_test_score": _record_value(user, "level_test_score"),
            "level_test_completed": bool(_record_value(user, "level_test_completed_at")),
            "points":     user["points"],
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong":   stats["total_wrong"],
        },
    })


async def api_admin_overview(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    overview = await database.get_admin_overview()
    failed_images = await database.get_admin_failed_image_words(limit=8)
    payload = _admin_overview_payload(overview)
    payload["failed_image_words"] = [_admin_failed_image_dict(row) for row in failed_images]
    return web.json_response(payload)


async def api_admin_users(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    search = (request.query.get("q") or "").strip()[:80]
    try:
        limit = int(request.query.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    rows = await database.get_admin_users(search=search, limit=limit)
    return web.json_response({
        "query": search,
        "users": [_admin_user_dict(row) for row in rows],
    })


async def api_admin_user_detail(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    try:
        target_user_id = int(request.query.get("user_id") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "Некорректный user_id"}, status=400)
    user = await database.get_user(target_user_id)
    if not user:
        return web.json_response({"error": "Пользователь не найден"}, status=404)
    stats = await database.get_user_stats(target_user_id)
    report = await database.get_parent_report(target_user_id)
    dictionary_summary = await database.get_dictionary_summary(target_user_id)
    problem_words = await database.get_problem_words(target_user_id, limit=8)
    history = await database.get_activity_history(target_user_id, limit=12)
    ai_today = await database.get_ai_usage_today(target_user_id)
    streak = await database.get_learning_streak(target_user_id)
    return web.json_response(_admin_user_detail_payload(
        user,
        stats,
        report,
        dictionary_summary,
        problem_words,
        history,
        ai_today,
        streak,
    ))


async def api_admin_reset_user_results(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    body = await _safe_json(request)
    if body.get("confirm") != "reset_user_results":
        return web.json_response({"error": "Нужно подтвердить сброс результатов пользователя"}, status=400)
    try:
        target_user_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        return web.json_response({"error": "Некорректный user_id"}, status=400)
    if not await database.user_exists(target_user_id):
        return web.json_response({"error": "Пользователь не найден"}, status=404)
    await database.reset_learning_results(target_user_id)
    return web.json_response({"ok": True, "user_id": target_user_id})


async def api_admin_reset_image_failures(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    body = await _safe_json(request)
    if body.get("confirm") != "reset_image_failures":
        return web.json_response({"error": "Нужно подтвердить сброс статусов картинок"}, status=400)
    updated = await database.reset_failed_generated_images()
    return web.json_response({"ok": True, "updated": updated})


async def api_leaderboard(request: web.Request):
    user_id = request["tg_user"]["id"]
    rows = await database.get_leaderboard(limit=10)

    leaders = []
    for index, row in enumerate(rows, start=1):
        age_label = next((l for l, v in AGE_GROUPS if v == row["age_group"]), row["age_group"])
        leaders.append({
            "rank": index,
            "id": row["user_id"],
            "name": row["name"],
            "age_label": age_label,
            "points": row["points"],
            "is_me": row["user_id"] == user_id,
        })

    return web.json_response({"leaders": leaders})


async def api_learning_path(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    daily_status = await database.get_daily_lesson_status(user_id)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    report = await database.get_parent_report(user_id)
    return web.json_response(
        _learning_path_payload(user, daily_status, stats, dictionary_summary, report)
    )


async def api_motivation_status(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    report = await database.get_parent_report(user_id)
    streak = await database.get_learning_streak(user_id)
    return web.json_response(
        _motivation_payload(user, stats, dictionary_summary, report, streak)
    )


async def api_register(request: web.Request):
    tg_user = request["tg_user"]
    body = await _safe_json(request)
    name = (body.get("child_name") or body.get("name") or "").strip()
    parent_name = (body.get("parent_name") or "").strip()
    age_group = body.get("age_group", "")
    goal = body.get("goal", "")
    try:
        child_age = int(body.get("child_age") or 0)
    except (TypeError, ValueError):
        child_age = 0

    if len(name) < 2 or len(name) > 30:
        return web.json_response({"error": "Имя ребенка должно быть от 2 до 30 символов"}, status=400)
    if parent_name and (len(parent_name) < 2 or len(parent_name) > 30):
        return web.json_response({"error": "Имя родителя должно быть от 2 до 30 символов"}, status=400)
    if age_group not in {v for _, v in AGE_GROUPS}:
        return web.json_response({"error": "Некорректная возрастная группа"}, status=400)
    if goal and goal not in {v for _, v in LEARNING_GOALS}:
        return web.json_response({"error": "Некорректная цель обучения"}, status=400)
    if child_age and (child_age < 5 or child_age > 18):
        return web.json_response({"error": "Возраст ребенка должен быть от 5 до 18 лет"}, status=400)

    await database.add_user(
        tg_user["id"],
        name,
        age_group,
        parent_name=parent_name or tg_user.get("first_name", ""),
        child_age=child_age or None,
        goal=goal or None,
        english_level=_level_from_score(age_group, 0, 0),
    )
    return web.json_response({"ok": True})


async def api_level_test(request: web.Request):
    user = await _current_user_or_404(request)
    age_group = _normalized_age_group_for_user(user)
    level = _level_for_user(user)
    questions = _level_questions_for_age(age_group)
    return web.json_response({
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "level": level,
        "level_label": _level_label(level),
        "questions": [_public_level_question(question) for question in questions],
    })


async def api_level_submit(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    answers = body.get("answers") or []
    if not isinstance(answers, list):
        return web.json_response({"error": "bad payload"}, status=400)

    age_group = _normalized_age_group_for_user(user)
    questions = _level_questions_for_age(age_group)
    by_id = {question["id"]: question for question in questions}
    selected_by_question = {}
    for raw in answers:
        if not isinstance(raw, dict):
            continue
        question_id = str(raw.get("question_id") or "")
        selected_id = str(raw.get("selected_id") or "")
        if question_id in by_id and selected_id:
            selected_by_question[question_id] = selected_id

    results = []
    correct_count = 0
    for question in questions:
        selected_id = selected_by_question.get(question["id"])
        correct = selected_id == question["correct_id"]
        if correct:
            correct_count += 1
        results.append({
            "question_id": question["id"],
            "correct": correct,
            "selected_id": selected_id,
            "correct_id": question["correct_id"],
        })

    total = len(questions)
    score = round(correct_count / total * 100) if total else 0
    level = _level_from_score(age_group, correct_count, total)
    await database.update_user_level(user_id, level, score)
    return web.json_response({
        "correct_count": correct_count,
        "total": total,
        "score": score,
        "level": level,
        "level_label": _level_label(level),
        "message": _level_result_message(level),
        "results": results,
    })


async def api_parent_report(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    report = await database.get_parent_report(user_id)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    problem_word_rows = await database.get_problem_words(user_id, limit=6)
    problem_words = [_problem_word_dict(row) for row in problem_word_rows]
    level = _level_for_user(user)
    report_payload = {
        "words_learned": int((report or stats)["words_learned"] or 0),
        "total_correct": int((report or stats)["total_correct"] or 0),
        "total_wrong": int((report or stats)["total_wrong"] or 0),
        "completed_lessons": int(report["completed_lessons"] if report else 0),
        "completed_word_tests": int(report["completed_word_tests"] if report else 0),
        "avg_word_test_score": int(report["avg_word_test_score"] if report else 0),
        "completed_games": int(report["completed_games"] if report else 0),
        "avg_game_score": int(report["avg_game_score"] if report else 0),
    }
    return web.json_response({
        "child": {
            "name": user["name"],
            "age_group": user["age_group"],
            "age_label": _age_label(user["age_group"]),
            "goal_label": _goal_label(user["goal"]),
            "level_label": _level_label(level),
            "points": user["points"],
        },
        "report": report_payload,
        "dictionary": {
            "total_words": int(dictionary_summary["total_words"] if dictionary_summary else 0),
            "mastered_words": int(dictionary_summary["mastered_words"] if dictionary_summary else 0),
            "review_words": int(dictionary_summary["review_words"] if dictionary_summary else 0),
        },
        "problem_words": problem_words,
        "recommendations": _parent_recommendations(report_payload, dictionary_summary, problem_words),
    })


async def api_results_reset(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    if body.get("confirm") != "reset_results":
        return web.json_response({"error": "Нужно подтвердить сброс результатов"}, status=400)

    await database.reset_learning_results(user_id)
    user = await database.get_user(user_id)
    stats = await database.get_user_stats(user_id)
    return web.json_response({
        "ok": True,
        "user": {
            "points": user["points"] if user else 0,
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong": stats["total_wrong"],
        },
    })


async def api_activity_history(request: web.Request):
    user_id = request["tg_user"]["id"]
    try:
        limit = int(request.query.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(5, min(limit, 80))
    rows = await database.get_activity_history(user_id, limit=limit)
    events = [_activity_event_dict(row) for row in rows]
    return web.json_response({
        "events": events,
        "summary": {
            "total_events": len(events),
            "active_days": len({event["date"] for event in events if event["date"]}),
        },
    })


# ---------- API: ежедневный урок ----------

async def api_daily_status(request: web.Request):
    user_id = request["tg_user"]["id"]
    status = await database.get_daily_lesson_status(user_id)
    return web.json_response(_daily_lesson_payload(status))


async def api_daily_progress(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        completed_steps = int(body.get("completed_steps", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad payload"}, status=400)

    status = await database.update_daily_lesson_progress(
        user_id,
        completed_steps=completed_steps,
        total_steps=DAILY_LESSON_STEPS,
    )
    reward_points = 0
    points = None

    if status["completed"]:
        rewarded = await database.claim_daily_lesson_reward(user_id)
        if rewarded:
            reward_points = DAILY_LESSON_REWARD_POINTS
            await database.update_points(user_id, DAILY_LESSON_REWARD_POINTS)
            user = await database.get_user(user_id)
            points = user["points"] if user else None
            status = await database.get_daily_lesson_status(user_id)

    return web.json_response(_daily_lesson_payload(status, reward_points, points))


# ---------- API: обучение ----------

async def api_learn_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    exclude_id = body.get("current_id")
    age_group = _normalized_age_group_for_user(user)
    word = await database.get_practice_word(user_id, exclude_id=exclude_id, age_group=age_group)
    return web.json_response(_word_dict(word, _level_for_user(user)))


async def api_vocab_image_generate(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    try:
        word_id = int(body.get("word_id"))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad payload"}, status=400)

    force = bool(body.get("force"))
    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    word_payload = _word_dict(word, _level_for_user(user))
    fallback_image_url = word_payload["fallback_image_url"]
    prompt_hash = word_payload["image_prompt_hash"]
    stored_url = word_payload.get("generated_image_url", "")
    stored_status = word_payload.get("image_generation_status", "missing")
    if not force and stored_url and _generated_vocab_url_exists(stored_url):
        return web.json_response({
            "image_url": stored_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": stored_status,
            "image_review": {},
            "cached": True,
        })

    if not force and GENERATED_VOCAB_DIR.exists():
        for cached_path in GENERATED_VOCAB_DIR.glob(f"{prompt_hash}.*"):
            if not cached_path.is_file():
                continue
            cached_url = _generated_vocab_static_url(cached_path.name)
            await database.update_word_generated_image(
                word_id,
                image_url=cached_url,
                prompt_hash=prompt_hash,
                review_json="{}",
                status="generated",
                model="local-cache",
            )
            return web.json_response({
                "image_url": cached_url,
                "fallback_image_url": fallback_image_url,
                "generation_status": "generated",
                "image_review": {},
                "cached": True,
            })

    try:
        result = await asyncio.wait_for(generate_vocabulary_image(word_payload, user_id), timeout=75)
    except Exception as exc:
        log.exception("Vocabulary image generation failed for word_id=%s", word_id)
        public_error = public_openai_error(exc)
        review_json = json.dumps({"reason": public_error}, ensure_ascii=False)
        try:
            await database.update_word_generated_image(
                word_id,
                image_url="",
                prompt_hash=prompt_hash,
                review_json=review_json,
                status="failed",
                model=OPENAI_IMAGE_MODEL,
            )
        except Exception:
            log.exception("Failed to persist vocabulary image failure for word_id=%s", word_id)
        return web.json_response({
            "error": public_error,
            "image_url": fallback_image_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": "failed",
            "image_review": {"reason": public_error},
        }, status=502)

    review_json = json.dumps(result.review, ensure_ascii=False)
    if result.generation_status == "failed" or not result.image_bytes:
        await database.update_word_generated_image(
            word_id,
            image_url="",
            prompt_hash=prompt_hash,
            review_json=review_json,
            status="failed",
            model=result.model,
        )
        return web.json_response({
            "image_url": fallback_image_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": "failed",
            "image_review": result.review,
            "attempts": result.attempts,
        })

    GENERATED_VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    extension = _generated_vocab_extension(result.content_type)
    filename = f"{prompt_hash}.{extension}"
    image_path = GENERATED_VOCAB_DIR / filename
    image_path.write_bytes(result.image_bytes)
    image_url = _generated_vocab_static_url(filename)
    await database.update_word_generated_image(
        word_id,
        image_url=image_url,
        prompt_hash=prompt_hash,
        review_json=review_json,
        status=result.generation_status,
        model=result.model,
    )
    return web.json_response({
        "image_url": image_url,
        "fallback_image_url": fallback_image_url,
        "generation_status": result.generation_status,
        "image_review": result.review,
        "attempts": result.attempts,
        "cached": False,
    })


async def api_dictionary(request: web.Request):
    user_id = request["tg_user"]["id"]
    filter_mode = (request.query.get("filter") or "all").strip()
    if filter_mode not in {"all", "review", "mastered"}:
        filter_mode = "all"
    try:
        limit = int(request.query.get("limit") or 5000)
    except (TypeError, ValueError):
        limit = 5000
    limit = max(10, min(limit, 5000))

    rows = await database.get_user_dictionary(user_id, filter_mode=filter_mode, limit=limit)
    summary = await database.get_dictionary_summary(user_id)
    total_words = await database.get_words_count()
    return web.json_response({
        "filter": filter_mode,
        "summary": {
            "total_words": int(total_words or 0),
            "mastered_words": int(summary["mastered_words"] if summary else 0),
            "review_words": int(summary["review_words"] if summary else 0),
        },
        "words": [_dictionary_word_dict(row) for row in rows],
    })


async def api_vocab_start(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    topic = (body.get("topic") or "").strip() or None
    age_group = _normalized_age_group_for_user(user)
    count = WORDS_PER_AGE_GROUP.get(age_group, 6)
    words = await database.get_words_for_age(age_group, count=count, topic=topic)
    if not words:
        log.error("No vocabulary words available for user=%s age_group=%s", user_id, age_group)
        return web.json_response({
            "error": "Пока не удалось загрузить слова. Попробуй открыть профиль и проверить возраст ребенка.",
        }, status=500)

    session = await database.create_vocabulary_session(
        user_id=user_id,
        age_group=age_group if age_group in WORDS_PER_AGE_GROUP else "8_10",
        topic=topic,
        word_ids=[w["id"] for w in words],
    )
    return web.json_response({
        "session_id": session["id"],
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "words": [_word_dict(w, _level_for_user(user)) for w in words],
    })


async def api_vocab_quiz(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_vocabulary_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "session not found"}, status=404)
    words = await database.get_words_by_ids(list(session["word_ids"]))
    questions = [await _build_vocab_question(word, session["age_group"]) for word in words]
    return web.json_response({
        "session_id": session_id,
        "questions": questions,
    })


async def api_vocab_finish(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
        answers = body["answers"]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_vocabulary_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "session not found"}, status=404)
    if session["completed"]:
        return web.json_response({"error": "Этот тест уже завершен"}, status=400)

    words = await database.get_words_by_ids(list(session["word_ids"]))
    words_by_id = {w["id"]: w for w in words}
    results = []
    latest_result_by_word_id: dict[int, dict] = {}
    correct_count = 0
    wrong_count = 0
    total_delta = 0

    for raw in answers:
        try:
            word_id = int(raw.get("word_id"))
            selected_id = int(raw.get("selected_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        word = words_by_id.get(word_id)
        if not word:
            continue
        correct = selected_id == word_id
        if correct:
            correct_count += 1
            total_delta += POINTS_CORRECT
        else:
            wrong_count += 1
            total_delta += POINTS_WRONG
        await database.update_progress(user_id, word_id, correct=correct)
        result_item = {
            "word_id": word_id,
            "word": word["word"],
            "translation": word["translation"],
            "transcription": word["transcription"] or "",
            "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
            "correct": correct,
        }
        results.append(result_item)
        latest_result_by_word_id[word_id] = result_item

    await database.finish_vocabulary_session(session_id, user_id, correct_count, wrong_count)
    await database.update_points(user_id, total_delta)
    user = await database.get_user(user_id)
    total = correct_count + wrong_count
    return web.json_response({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "total": total,
        "score": round(correct_count / total * 100) if total else 0,
        "delta": total_delta,
        "points": user["points"] if user else 0,
        "results": [
            latest_result_by_word_id[word["id"]]
            for word in words
            if word["id"] in latest_result_by_word_id
        ],
        "attempts": results,
    })


async def api_word_hunt_start(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    age_group = _normalized_age_group_for_user(user)
    count = min(6, max(4, WORDS_PER_AGE_GROUP.get(age_group, 6)))
    words = await database.get_words_for_age(age_group, count=count)
    if not words:
        return web.json_response({"error": "Пока не удалось загрузить слова для игры"}, status=500)

    session = await database.create_game_session(
        user_id=user_id,
        game_type="word_hunt",
        age_group=age_group,
        word_ids=[word["id"] for word in words],
    )
    rounds = [await _build_word_hunt_round(word, age_group) for word in words]
    return web.json_response({
        "session_id": session["id"],
        "game_type": "word_hunt",
        "title": _game_title("word_hunt"),
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "rounds": rounds,
        "points_correct": GAME_POINTS_CORRECT,
        "perfect_bonus": GAME_PERFECT_BONUS_POINTS,
    })


async def api_word_hunt_finish(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
        answers = body["answers"]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_game_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "game not found"}, status=404)
    if session["completed"]:
        return web.json_response({"error": "Эта игра уже завершена"}, status=400)

    words = await database.get_words_by_ids(list(session["word_ids"]))
    answer_by_word: dict[int, int] = {}
    for raw in answers:
        try:
            word_id = int(raw.get("word_id"))
            selected_id = int(raw.get("selected_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        answer_by_word[word_id] = selected_id

    results = []
    correct_count = 0
    wrong_count = 0

    for word in words:
        word_id = int(word["id"])
        selected_id = answer_by_word.get(word_id)
        correct = selected_id == word_id
        if correct:
            correct_count += 1
        else:
            wrong_count += 1
        await database.update_progress(user_id, word_id, correct=correct)
        results.append({
            "word_id": word_id,
            "word": word["word"],
            "translation": word["translation"],
            "transcription": word["transcription"] or "",
            "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
            "selected_id": selected_id,
            "correct": correct,
        })

    total = correct_count + wrong_count
    perfect_bonus = GAME_PERFECT_BONUS_POINTS if total > 0 and correct_count == total else 0
    total_delta = correct_count * GAME_POINTS_CORRECT + perfect_bonus
    await database.finish_game_session(session_id, user_id, correct_count, wrong_count)
    await database.update_points(user_id, total_delta)
    user = await database.get_user(user_id)
    return web.json_response({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "total": total,
        "score": round(correct_count / total * 100) if total else 0,
        "delta": total_delta,
        "perfect_bonus": perfect_bonus,
        "points": user["points"] if user else 0,
        "results": results,
    })


async def api_choice_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    focus = "review" if body.get("focus") == "review" else "all"
    age_group = _normalized_age_group_for_user(user)
    exclude_ids = []
    for item in body.get("exclude_ids") or []:
        try:
            exclude_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    correct = None
    requested_word_id = body.get("word_id")
    if requested_word_id is not None:
        try:
            correct = await database.get_word_by_id(int(requested_word_id))
        except (TypeError, ValueError):
            return web.json_response({"error": "bad payload"}, status=400)
        if not correct:
            return web.json_response({"error": "word not found"}, status=404)

    if not correct:
        correct = await database.get_review_word(user_id, age_group=age_group, exclude_ids=exclude_ids) if focus == "review" else None
    review_empty = focus == "review" and not correct
    if not correct:
        correct = await database.get_practice_word(user_id, age_group=age_group, exclude_ids=exclude_ids)
    if not correct and exclude_ids:
        correct = await database.get_review_word(user_id, age_group=age_group) if focus == "review" else None
        if not correct:
            correct = await database.get_practice_word(user_id, age_group=age_group)
    if not correct:
        return web.json_response({"error": "Нет слов"}, status=500)

    wrong = await database.get_random_words(3, exclude_id=correct["id"], age_group=age_group)
    options = [{"id": correct["id"], "translation": correct["translation"]}]
    options += [{"id": w["id"], "translation": w["translation"]} for w in wrong]
    random.shuffle(options)

    return web.json_response({
        "word":    correct["word"],
        "word_id": correct["id"],
        "transcription": correct["transcription"] or "",
        "image_url": _word_image_url(correct["word"], correct["topic"] or "basic"),
        "options": options,
        "focus": focus,
        "review_empty": review_empty,
    })


async def api_choice_answer(request: web.Request):
    body = await _safe_json(request)
    user_id = request["tg_user"]["id"]
    try:
        word_id     = int(body["word_id"])
        selected_id = int(body["selected_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    correct = selected_id == word_id
    focus = "review" if body.get("focus") == "review" else "all"
    delta = POINTS_CORRECT if correct else POINTS_WRONG
    await database.update_points(user_id, delta)
    await database.update_progress(user_id, word_id, correct=correct)
    await database.add_training_attempt(user_id, "choice", focus, correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "word_id":     word_id,
        "correct":     correct,
        "word":        word["word"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "delta":       delta,
        "points":      user["points"],
    })


async def api_input_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    focus = "review" if body.get("focus") == "review" else "all"
    age_group = _normalized_age_group_for_user(user)
    exclude_ids = []
    for item in body.get("exclude_ids") or []:
        try:
            exclude_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    word = None
    requested_word_id = body.get("word_id")
    if requested_word_id is not None:
        try:
            word = await database.get_word_by_id(int(requested_word_id))
        except (TypeError, ValueError):
            return web.json_response({"error": "bad payload"}, status=400)
        if not word:
            return web.json_response({"error": "word not found"}, status=404)

    if not word:
        word = await database.get_review_word(user_id, age_group=age_group, exclude_ids=exclude_ids) if focus == "review" else None
    review_empty = focus == "review" and not word
    if not word:
        word = await database.get_practice_word(user_id, age_group=age_group, exclude_ids=exclude_ids)
    if not word and exclude_ids:
        word = await database.get_review_word(user_id, age_group=age_group) if focus == "review" else None
        if not word:
            word = await database.get_practice_word(user_id, age_group=age_group)
    if not word:
        return web.json_response({"error": "Нет слов"}, status=500)
    return web.json_response({
        "word_id":     word["id"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "focus": focus,
        "review_empty": review_empty,
    })


async def api_input_answer(request: web.Request):
    body = await _safe_json(request)
    user_id = request["tg_user"]["id"]
    try:
        word_id = int(body["word_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    answer = (body.get("answer") or "").strip().lower()

    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    correct = answer == word["word"].lower()
    focus = "review" if body.get("focus") == "review" else "all"
    delta = POINTS_CORRECT if correct else POINTS_WRONG
    await database.update_points(user_id, delta)
    await database.update_progress(user_id, word_id, correct=correct)
    await database.add_training_attempt(user_id, "input", focus, correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "word_id":     word_id,
        "correct":     correct,
        "word":        word["word"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "delta":       delta,
        "points":      user["points"],
    })


# ---------- API: ИИ-репетитор ----------

async def api_chat_history(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT * 2)
    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    stats = await database.get_ai_usage_today(user_id)
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    return web.json_response({
        "messages": messages,
        "usage": _chat_usage_payload(stats),
        "lesson_state": public_lesson_state(lesson_state),
    })


async def api_chat_send(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    text = (body.get("message") or "").strip()
    mode = "voice" if body.get("mode") == "voice" else "chat"
    if not text:
        return web.json_response({"error": "empty message"}, status=400)
    if len(text) > 1000:
        text = text[:1000]

    stats = await database.get_ai_usage_today(user_id)

    user = await database.get_user(user_id)
    user_name = user["name"] if user else "друг"

    # Сохраняем сообщение пользователя
    await database.add_message(user_id, "user", text)
    lesson_state = None
    if mode == "voice":
        lesson_state = await _advance_voice_lesson_state(user_id, user, "user", text)

    # Берём последние сообщения как контекст для модели
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = mode
    if mode == "voice":
        prompt_context.update(_voice_prompt_context(user, history, lesson_state))
    reply = await chat_reply(history, user_name, age_label, prompt_context)

    await database.add_message(user_id, "assistant", reply.text)
    if mode == "voice":
        lesson_state = await _advance_voice_lesson_state(user_id, user, "assistant", reply.text)
    if reply.total_tokens > 0:
        await database.add_ai_usage(
            user_id=user_id,
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            total_tokens=reply.total_tokens,
            cost_usd=reply.cost_usd,
        )
        stats = await database.get_ai_usage_today(user_id)

    return web.json_response({
        "reply": reply.text,
        "usage": _chat_usage_payload(stats),
        "lesson_state": public_lesson_state(lesson_state),
    })


async def api_audio_transcribe(request: web.Request):
    try:
        audio, filename, content_type = await _read_audio_upload(request)
    except web.HTTPRequestEntityTooLarge as e:
        return web.json_response({"error": e.text}, status=413)
    except web.HTTPBadRequest as e:
        return web.json_response({"error": e.text}, status=400)

    try:
        text = await transcribe_audio(
            audio,
            filename=filename,
            content_type=content_type,
        )
    except Exception as e:
        log.exception("Audio transcription failed")
        return web.json_response({"error": f"Не удалось распознать голос. {public_openai_error(e)}"}, status=502)

    return web.json_response({"text": text})


async def api_audio_speech(request: web.Request):
    body = await _safe_json(request)
    text = (body.get("text") or "").strip()
    mode = body.get("mode") if body.get("mode") in {"voice", "word"} else "chat"
    speed = body.get("speed")
    if not text:
        return web.json_response({"error": "Нет текста для озвучки"}, status=400)
    if len(text) > 1200:
        text = text[:1200]

    cache_path = _word_audio_cache_path(text, mode, speed)
    if cache_path and cache_path.is_file():
        return web.Response(
            body=cache_path.read_bytes(),
            content_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Audio-Cache": "hit",
            },
        )

    try:
        audio = await synthesize_speech(text, mode=mode, speed=speed)
    except Exception as e:
        log.exception("Speech synthesis failed")
        return web.json_response({"error": f"Не удалось озвучить ответ. {public_openai_error(e)}"}, status=502)

    cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    }
    if cache_path:
        try:
            AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(audio)
            cache_headers = {
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Audio-Cache": "miss",
            }
        except OSError:
            log.exception("Failed to store word audio cache")

    return web.Response(
        body=audio,
        content_type="audio/mpeg",
        headers=cache_headers,
    )


async def _voice_text_turn_payload(user_id: int, text: str) -> dict:
    stats = await database.get_ai_usage_today(user_id)
    user = await database.get_user(user_id)
    user_name = user["name"] if user else "друг"

    await database.add_message(user_id, "user", text)
    lesson_state = await _advance_voice_lesson_state(user_id, user, "user", text)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context.update(_voice_prompt_context(user, history, lesson_state))

    reply = await chat_reply(history, user_name, age_label, prompt_context)
    await database.add_message(user_id, "assistant", reply.text)
    lesson_state = await _advance_voice_lesson_state(user_id, user, "assistant", reply.text)
    if reply.total_tokens > 0:
        await database.add_ai_usage(
            user_id=user_id,
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            total_tokens=reply.total_tokens,
            cost_usd=reply.cost_usd,
        )
        stats = await database.get_ai_usage_today(user_id)

    audio_b64 = ""
    audio_error = ""
    if not reply.text.startswith("Ошибка:") and not reply.text.startswith("⚠️"):
        try:
            speech = await synthesize_speech(reply.text, mode="voice")
            audio_b64 = base64.b64encode(speech).decode("ascii")
        except Exception as e:
            log.exception("Hybrid voice speech synthesis failed")
            audio_error = public_openai_error(e)

    return {
        "text": text,
        "reply": reply.text,
        "audio_base64": audio_b64,
        "audio_content_type": "audio/mpeg" if audio_b64 else "",
        "audio_error": audio_error,
        "usage": _chat_usage_payload(stats),
        "lesson_state": public_lesson_state(lesson_state),
    }


async def _voice_unclear_payload(user_id: int, reply_text: str | None = None) -> dict:
    user = await database.get_user(user_id)
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    age_group = _normalized_age_group_for_user(user)
    if reply_text:
        reply = reply_text
    elif age_group == "5_7":
        reply = "Я не очень хорошо услышал. Повтори одно слово, пожалуйста."
    else:
        reply = "Я не очень хорошо услышал. Повтори, пожалуйста, короткой фразой."

    audio_b64 = ""
    audio_error = ""
    try:
        speech = await synthesize_speech(reply, mode="voice")
        audio_b64 = base64.b64encode(speech).decode("ascii")
    except Exception as e:
        log.exception("Unclear voice fallback speech synthesis failed")
        audio_error = public_openai_error(e)

    return {
        "text": "",
        "reply": reply,
        "audio_base64": audio_b64,
        "audio_content_type": "audio/mpeg" if audio_b64 else "",
        "audio_error": audio_error,
        "usage": _chat_usage_payload(await database.get_ai_usage_today(user_id)),
        "lesson_state": public_lesson_state(lesson_state),
        "voice_fallback": "unclear",
    }


async def api_voice_text_turn(request: web.Request):
    """Stable hybrid turn when speech was already transcribed by Realtime."""
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    text = " ".join((body.get("message") or body.get("text") or "").split())
    if not text:
        payload = await _voice_unclear_payload(user_id)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})
    if len(text) > 1000:
        text = text[:1000]

    try:
        payload = await _voice_text_turn_payload(user_id, text)
    except Exception as e:
        log.exception("Hybrid voice text turn failed")
        return web.json_response({"error": public_openai_error(e)}, status=502)
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def api_voice_turn(request: web.Request):
    """Stable hybrid voice turn: transcribe, reply, and synthesize in one request."""
    user_id = request["tg_user"]["id"]
    try:
        audio, filename, content_type = await _read_audio_upload(request)
    except web.HTTPRequestEntityTooLarge as e:
        return web.json_response({"error": e.text}, status=413)
    except web.HTTPBadRequest as e:
        return web.json_response({"error": e.text}, status=400)

    try:
        text = await transcribe_audio(audio, filename=filename, content_type=content_type)
    except Exception as e:
        log.exception("Hybrid voice transcription failed")
        return web.json_response({"error": f"Не удалось распознать голос. {public_openai_error(e)}"}, status=502)

    text = " ".join(text.split())
    if not text:
        payload = await _voice_unclear_payload(user_id)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})
    if len(text) > 1000:
        text = text[:1000]

    try:
        payload = await _voice_text_turn_payload(user_id, text)
    except Exception as e:
        log.exception("Hybrid voice turn failed")
        return web.json_response({"error": public_openai_error(e)}, status=502)
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def api_realtime_call(request: web.Request):
    user_id = request["tg_user"]["id"]
    raw_body = await request.read()
    sdp_offer = raw_body.decode("utf-8", errors="replace").strip()
    log.info(
        "Realtime SDP: content_type=%s body_len=%d sdp_starts=%s",
        request.content_type, len(raw_body), repr(sdp_offer[:40]) if sdp_offer else "EMPTY",
    )
    if not sdp_offer or len(raw_body) > MAX_SDP_BYTES:
        return web.json_response({"error": f"Некорректный SDP: len={len(raw_body)}, starts={repr(sdp_offer[:30])}"}, status=400)

    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    age_label = _age_label(user["age_group"]) if user else ""
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    prompt_context = _realtime_prompt_context(user, history, lesson_state)

    try:
        answer_sdp = await create_realtime_call(
            sdp_offer=sdp_offer,
            user_id=user_id,
            user_name=user["name"] if user else "друг",
            age_label=age_label,
            prompt_context=prompt_context,
        )
    except Exception as e:
        log.exception("Realtime call setup failed: %s", e)
        return web.json_response({"error": public_openai_error(e)}, status=502)

    return web.Response(
        text=answer_sdp,
        content_type="application/sdp",
        headers={"Cache-Control": "no-store"},
    )


def _realtime_prompt_context(user, history: list[dict], lesson_state: dict | None = None) -> dict:
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context["age_group"] = _normalized_age_group_for_user(user) if user else "8_10"
    prompt_context.update(_voice_prompt_context(user, history, lesson_state))
    return prompt_context


async def api_realtime_token(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    age_label = _age_label(user["age_group"]) if user else ""
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    prompt_context = _realtime_prompt_context(user, history, lesson_state)

    try:
        token = await create_realtime_client_secret(
            user_id=user_id,
            user_name=user["name"] if user else "друг",
            age_label=age_label,
            prompt_context=prompt_context,
        )
    except Exception as e:
        log.exception("Realtime token setup failed: %s", e)
        return web.json_response({"error": public_openai_error(e)}, status=502)

    return web.json_response(token, headers={"Cache-Control": "no-store"})


async def api_realtime_log(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    role = "assistant" if body.get("role") == "assistant" else "user"
    content = " ".join(str(body.get("content") or "").split())
    if not content:
        return web.json_response({"ok": True})
    if len(content) > 1000:
        content = content[:1000]
    await database.add_message(user_id, role, content)
    lesson_state = await _advance_voice_lesson_state(user_id, user, role, content)
    return web.json_response({
        "ok": True,
        "lesson_state": public_lesson_state(lesson_state),
    })


async def api_chat_reset(request: web.Request):
    user_id = request["tg_user"]["id"]
    await database.clear_conversation(user_id)
    await database.clear_voice_lesson_state(user_id)
    return web.json_response({"ok": True})


# ---------- Static ----------

async def index_handler(request: web.Request):
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    text = text.replace("__APP_VERSION__", APP_VERSION)
    return web.Response(
        text=text,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


async def word_image_handler(request: web.Request):
    word = " ".join((request.query.get("w") or "word").split())[:48]
    topic = " ".join((request.query.get("t") or "basic").split())[:32]
    return web.Response(
        text=_word_image_svg(word, topic),
        content_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=604800",
        },
    )


async def vocabulary_visual_handler(request: web.Request):
    word = " ".join((request.query.get("w") or "word").split())[:48]
    topic = " ".join((request.query.get("t") or "basic").split())[:32]
    visual_type = " ".join((request.query.get("v") or "object").split())[:32]
    return web.Response(
        text=_vocabulary_visual_svg(word, topic, visual_type),
        content_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=604800",
        },
    )


# ---------- App factory ----------

def create_app(
    bot=None,
    dispatcher=None,
    webhook_path: str | None = None,
    webhook_secret: str | None = None,
) -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=MAX_AUDIO_BYTES + 1024 * 1024)

    app.router.add_get("/",        index_handler)
    app.router.add_get("/word-image.svg", word_image_handler)
    app.router.add_get("/vocabulary-visual.svg", vocabulary_visual_handler)
    app.router.add_get("/api/me",  api_me)
    app.router.add_get("/api/admin/overview",           api_admin_overview)
    app.router.add_get("/api/admin/users",              api_admin_users)
    app.router.add_get("/api/admin/users/detail",       api_admin_user_detail)
    app.router.add_post("/api/admin/users/reset-results", api_admin_reset_user_results)
    app.router.add_post("/api/admin/images/reset-failed", api_admin_reset_image_failures)
    app.router.add_get("/api/leaderboard",              api_leaderboard)
    app.router.add_get("/api/learning/path",            api_learning_path)
    app.router.add_get("/api/motivation/status",        api_motivation_status)
    app.router.add_get("/api/parent/report",            api_parent_report)
    app.router.add_post("/api/results/reset",           api_results_reset)
    app.router.add_get("/api/activity/history",         api_activity_history)
    app.router.add_get("/api/level/test",               api_level_test)
    app.router.add_post("/api/level/submit",            api_level_submit)
    app.router.add_get("/api/daily/status",             api_daily_status)
    app.router.add_post("/api/daily/progress",          api_daily_progress)
    app.router.add_post("/api/register",               api_register)
    app.router.add_get("/api/dictionary",              api_dictionary)
    app.router.add_post("/api/learn/next",             api_learn_next)
    app.router.add_post("/api/vocab/image/generate",   api_vocab_image_generate)
    app.router.add_post("/api/vocab/start",            api_vocab_start)
    app.router.add_post("/api/vocab/quiz",             api_vocab_quiz)
    app.router.add_post("/api/vocab/finish",           api_vocab_finish)
    app.router.add_post("/api/game/word-hunt/start",   api_word_hunt_start)
    app.router.add_post("/api/game/word-hunt/finish",  api_word_hunt_finish)
    app.router.add_post("/api/training/choice/next",   api_choice_next)
    app.router.add_post("/api/training/choice/answer", api_choice_answer)
    app.router.add_post("/api/training/input/next",    api_input_next)
    app.router.add_post("/api/training/input/answer",  api_input_answer)
    app.router.add_get("/api/chat/history",            api_chat_history)
    app.router.add_post("/api/chat/send",              api_chat_send)
    app.router.add_post("/api/audio/transcribe",       api_audio_transcribe)
    app.router.add_post("/api/audio/speech",           api_audio_speech)
    app.router.add_post("/api/voice/text-turn",        api_voice_text_turn)
    app.router.add_post("/api/voice/turn",             api_voice_turn)
    app.router.add_post("/api/realtime/token",         api_realtime_token)
    app.router.add_post("/api/realtime/call",          api_realtime_call)
    app.router.add_post("/api/realtime/log",           api_realtime_log)
    app.router.add_post("/api/chat/reset",             api_chat_reset)

    if bot is not None and dispatcher is not None and webhook_path:
        SimpleRequestHandler(
            dispatcher=dispatcher,
            bot=bot,
            secret_token=webhook_secret or None,
        ).register(app, path=webhook_path)
        setup_application(app, dispatcher, bot=bot)

    app.router.add_static("/static", STATIC_DIR)

    return app


async def run_webapp(
    bot=None,
    dispatcher=None,
    webhook_path: str | None = None,
    webhook_secret: str | None = None,
) -> web.AppRunner:
    """Запускает aiohttp в текущем event loop. Возвращает runner для cleanup."""
    app = create_app(
        bot=bot,
        dispatcher=dispatcher,
        webhook_path=webhook_path,
        webhook_secret=webhook_secret,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    log.info("Mini App сервер слушает http://%s:%s", WEBAPP_HOST, WEBAPP_PORT)
    return runner
