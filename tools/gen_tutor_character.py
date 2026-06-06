"""One-off: generate sample animated-style tutor character images via gpt-image-1.

Run: PYTHONPATH=<repo> .venv/Scripts/python.exe tools/gen_tutor_character.py
Saves PNGs into webapp/static/ for visual review. Not wired into the app.
"""
import asyncio
import base64
from pathlib import Path

from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_IMAGE_MODEL

OUT_DIR = Path(__file__).resolve().parent.parent / "webapp" / "static"

VARIANTS = {
    "tutor-girl-sample-a.png": (
        "A friendly 3D cartoon-style portrait of a kind young woman English teacher "
        "for children. Warm gentle smile, large expressive brown eyes, soft wavy "
        "shoulder-length brown hair, light skin, wearing a cozy lavender knit sweater. "
        "Head and shoulders, facing forward. Smooth Pixar / Disney 3D animation render "
        "style, soft studio lighting, clean plain cream-white background. Wholesome, "
        "approachable, suitable for young kids. No text, no watermark."
    ),
    "tutor-girl-sample-b.png": (
        "A cute friendly cartoon mascot teacher character, a cheerful young woman, "
        "big sparkly hazel eyes, rosy cheeks, soft rounded features, light brown hair "
        "in a neat style, wearing a pastel mint cardigan. Modern 3D animated movie "
        "style, soft clean lighting, simple solid pastel background, head and shoulders. "
        "Kind, warm, wholesome, designed to teach English to children. No text."
    ),
}


async def main() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is not set")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    for filename, prompt in VARIANTS.items():
        print(f"Generating {filename} ...", flush=True)
        request = {
            "model": OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": "1024x1024",
            "quality": "medium",
            "output_format": "png",
            "n": 1,
        }
        try:
            resp = await client.images.generate(**request)
        except Exception as exc:  # noqa: BLE001
            print(f"  quality=medium failed ({exc}); retrying without quality", flush=True)
            request.pop("quality", None)
            resp = await client.images.generate(**request)
        b64 = resp.data[0].b64_json
        out = OUT_DIR / filename
        out.write_bytes(base64.b64decode(b64))
        print(f"  saved -> {out} ({out.stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
