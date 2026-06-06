"""One-off: generate the two age-split tutor avatars via gpt-image-1.

Run: PYTHONPATH=<repo> .venv/Scripts/python.exe tools/gen_tutor_character.py
Saves resized JPGs straight into webapp/static/assets/. Not wired into the app.
"""
import asyncio
import base64
import io
from pathlib import Path

from PIL import Image
from openai import AsyncOpenAI
from config import OPENAI_API_KEY, OPENAI_IMAGE_MODEL

ASSETS = Path(__file__).resolve().parent.parent / "webapp" / "static" / "assets"

VARIANTS = {
    # 5-10: polished friendly 3D cartoon girl (lavender sweater, wavy hair)
    "tutor-kids-5_10.jpg": (
        "A friendly, pretty 3D cartoon-style portrait of a young woman English "
        "teacher for children. Soft warm smile, large expressive brown eyes, long "
        "wavy chestnut-brown hair, light skin, gentle rosy cheeks, wearing a soft "
        "lavender knit sweater. Head and shoulders, facing forward. Polished "
        "Pixar / Disney 3D animation render, soft studio lighting, clean plain "
        "off-white background. Wholesome, kind, approachable. No text, no watermark."
    ),
    # 11-18: warm photorealistic young female teacher (hair up, blue blouse, office)
    "tutor-teen-11_18.jpg": (
        "A warm, photorealistic portrait of a friendly young woman English teacher, "
        "mid-20s, gentle natural smile, brown hair softly pulled up, light skin, "
        "wearing a light blue blouse with a soft collar. Head and shoulders, facing "
        "forward, looking at the camera. Bright, soft, slightly blurred modern "
        "home-office background with a light bookshelf and a small plant. Natural "
        "soft daylight, professional, approachable, wholesome, realistic photography. "
        "No text, no watermark."
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
            "quality": "high",
            "output_format": "png",
            "n": 1,
        }
        try:
            resp = await client.images.generate(**request)
        except Exception as exc:  # noqa: BLE001
            print(f"  quality=high failed ({exc}); retrying without quality", flush=True)
            request.pop("quality", None)
            resp = await client.images.generate(**request)
        raw = base64.b64decode(resp.data[0].b64_json)
        im = Image.open(io.BytesIO(raw)).convert("RGB").resize((512, 512), Image.LANCZOS)
        out = ASSETS / filename
        im.save(out, "JPEG", quality=88, optimize=True, progressive=True)
        print(f"  saved -> {out} ({out.stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
