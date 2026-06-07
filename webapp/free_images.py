"""Free, child-safe image lookup via the Pixabay API.

Pixabay is a curated stock library, so results are clean and relevant for
vocabulary (unlike a raw CC aggregator). Safety choices for a kids product:
- ``safesearch=true`` so Pixabay excludes adult content.
- Prefer ``image_type=photo`` (universal, age-neutral for 5-18), fall back to
  illustrations (cartoon clipart skews childish for older learners).
- The caller skips a blocklist of words we never fetch imagery for.
- We only download from URLs Pixabay returns on the trusted ``pixabay.com`` host;
  the user word influences only the search query, never a download URL.

Per Pixabay's license the image must be cached on our server (not hotlinked),
which the caller does. Requires a free PIXABAY_API_KEY (else this returns None
and the caller falls back to the SVG scene).
"""
from __future__ import annotations

import logging

import aiohttp

from config import PIXABAY_API_KEY

log = logging.getLogger(__name__)

_PIXABAY_API = "https://pixabay.com/api/"
_TRUSTED_HOST = "pixabay.com"
_USER_AGENT = "AIEnglishTutorKids/1.0 (educational vocabulary app)"
_MAX_BYTES = 2_000_000


async def _download_image(session: aiohttp.ClientSession, url: str) -> tuple[bytes, str] | None:
    if _TRUSTED_HOST not in url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
            if resp.status != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            # SVG отклоняем (вектор XSS): нам нужны только растровые картинки.
            if not ctype.startswith("image/") or ctype == "image/svg+xml":
                return None
            clen = resp.headers.get("Content-Length")
            if clen and clen.isdigit() and int(clen) > _MAX_BYTES:
                return None
            body = await resp.read()
            if not body or len(body) > _MAX_BYTES or len(body) < 256:
                return None
            return body, ctype
    except Exception:  # noqa: BLE001
        return None


async def fetch_word_illustration(word: str) -> tuple[bytes, str] | None:
    """Returns (image_bytes, content_type) for a clean child-safe image, or None."""
    if not PIXABAY_API_KEY:
        return None
    clean = " ".join(str(word or "").split()).strip()
    if not clean:
        return None
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # Фото — универсальный «взрослый» стиль для всех возрастов (5–18);
            # illustration оставляем фолбэком (мультяшный стиль детскее).
            for image_type in ("photo", "illustration"):
                params = {
                    "key": PIXABAY_API_KEY,
                    "q": clean,
                    "image_type": image_type,
                    "safesearch": "true",
                    "order": "popular",
                    "per_page": "6",
                }
                try:
                    async with session.get(
                        _PIXABAY_API, params=params, timeout=aiohttp.ClientTimeout(total=6)
                    ) as resp:
                        if resp.status != 200:
                            log.info("Pixabay HTTP %s (%s) for %r", resp.status, image_type, clean)
                            continue
                        data = await resp.json()
                except Exception as exc:  # noqa: BLE001
                    log.info("Pixabay request failed (%s) for %r: %s", image_type, clean, exc)
                    continue
                for hit in (data.get("hits") or []):
                    img_url = str(hit.get("webformatURL") or hit.get("largeImageURL") or "")
                    if not img_url.startswith("https://"):
                        continue
                    got = await _download_image(session, img_url)
                    if got:
                        return got
    except Exception as exc:  # noqa: BLE001
        log.info("Pixabay fetch failed for %r: %s", clean, exc)
        return None
    return None
