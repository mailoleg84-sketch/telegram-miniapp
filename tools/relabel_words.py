"""Re-label the 5000-word bank by real difficulty using gpt-4o-mini.

Scores each word 1-100 for how advanced it is for a child ESL learner, then sorts
all words by score and splits into 4 equal buckets of 1250 -> age groups
(5_7 = easiest ... 14_18 = hardest). Keeps word/translation/example/topic, only
rewrites age_group. Result: 5000 unique, exactly 1250 per age (tests stay green).

Run: PYTHONPATH=<repo> .venv/Scripts/python.exe tools/relabel_words.py
"""
import asyncio
import json
import re
from pathlib import Path

from openai import AsyncOpenAI
from config import OPENAI_API_KEY
from data.single_words_5000 import SINGLE_WORDS_5000

OUT = Path(__file__).resolve().parent.parent / "data" / "single_words_5000.py"
AGES = ["5_7", "8_10", "11_13", "14_18"]
BATCH = 60
CONCURRENCY = 8

RUBRIC = (
    "You grade English vocabulary difficulty for Russian CHILDREN learning English. "
    "Score each word 1-100 by how advanced/abstract it is for a child learner:\n"
    "1-25: very basic, concrete, high-frequency in a young child's world "
    "(cat, dog, run, red, mom, ball, sun, apple, jump, big).\n"
    "26-50: common everyday A1-A2 (school, friend, breakfast, kitchen, rabbit, window, happy).\n"
    "51-75: more abstract or A2-B1 (weekend, because, hobby, question, weather, practice, future).\n"
    "76-100: abstract, formal, academic, or B1-B2 (production, clearly, experience, confident, "
    "interview, policy, economy, although, however, definition).\n"
    "Lower = more concrete/frequent/childish. Higher = more abstract/formal/advanced. "
    "Return ONLY a JSON object mapping each given lowercase word to its integer score."
)


async def score_batch(client, sem, words):
    async with sem:
        for attempt in range(3):
            try:
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": RUBRIC},
                        {"role": "user", "content": "Score these words:\n" + json.dumps(words, ensure_ascii=False)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                return {str(k).strip().lower(): int(v) for k, v in data.items()
                        if isinstance(v, (int, float)) or str(v).strip().isdigit()}
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f"  batch failed: {exc}", flush=True)
                    return {}
                await asyncio.sleep(1.5 * (attempt + 1))
    return {}


async def main():
    if not OPENAI_API_KEY:
        raise SystemExit("no OPENAI_API_KEY")
    words = [w[0] for w in SINGLE_WORDS_5000]
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    sem = asyncio.Semaphore(CONCURRENCY)
    batches = [words[i:i + BATCH] for i in range(0, len(words), BATCH)]
    print(f"Scoring {len(words)} words in {len(batches)} batches ...", flush=True)
    results = await asyncio.gather(*(score_batch(client, sem, b) for b in batches))
    scores = {}
    for r in results:
        scores.update(r)
    missing = [w for w in words if w.lower() not in scores]
    print(f"Got scores for {len(scores)}/{len(words)}; missing {len(missing)} (defaulted to 50)", flush=True)

    # Order by (score, word). Tie-break by word for determinism.
    ordered = sorted(SINGLE_WORDS_5000, key=lambda t: (scores.get(t[0].lower(), 50), t[0]))
    per = len(ordered) // 4  # 1250
    relabeled = []
    for idx, (word, tr, ex, topic, _old_age) in enumerate(ordered):
        bucket = min(idx // per, 3)
        relabeled.append((word, tr, ex, topic, AGES[bucket]))

    # Sanity: print a sample of each new bucket (easiest / hardest words).
    by_age = {a: [t for t in relabeled if t[4] == a] for a in AGES}
    for a in AGES:
        sample = [t[0] for t in by_age[a][:10]]
        print(f"  {a} ({len(by_age[a])}): {sample}", flush=True)

    # Re-sort to a stable order for the file (by age then word) and serialize.
    relabeled.sort(key=lambda t: (AGES.index(t[4]), t[0]))
    lines = ['"""Generated single-word vocabulary used by learning modes."""', "",
             "from __future__ import annotations", "", "SINGLE_WORDS_5000 = ["]
    for word, tr, ex, topic, age in relabeled:
        lines.append(f"    ({word!r}, {tr!r}, {ex!r}, {topic!r}, {age!r}),")
    lines.append("]")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(relabeled)} words -> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
